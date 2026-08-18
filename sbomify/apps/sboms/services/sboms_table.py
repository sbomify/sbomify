from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from sbomify.apps.core.apis import get_component, list_component_sboms
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.forms import SbomDeleteForm
from sbomify.apps.sboms.services.sboms import delete_sbom_record
from sbomify.apps.teams.apis import get_team


def _attach_vulnerability_counts(sbom_items: list[dict[str, Any]], component_id: str, *, merged: bool = True) -> None:
    """Attach each SBOM's severity counts as ``item['vuln']``.

    ``merged=True`` (the compact card, a handful of rows): the latest run per
    (sbom, provider) merged by advisory alias, so the chips agree with the
    header badge and the drill-down. ``merged=False`` (the full history
    listing, potentially hundreds of rows): each SBOM's newest run summary read
    from the STORED ``result_summary`` generated columns — no result blob is
    ever de-TOASTed, at the cost of showing that single run's counts.
    Rows with no completed security run get ``vuln = None``.
    """
    from sbomify.apps.vulnerability_scanning.utils import (
        RESULT_SUMMARY_COLUMNS,
        extract_finding_rows,
        extract_severity_counts,
        merge_findings_by_alias,
        reconstruct_result_summary,
        result_scanned_nothing,
    )
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    sbom_ids = [item["sbom"]["id"] for item in sbom_items if item.get("sbom", {}).get("id")]
    if not sbom_ids:
        return

    if not merged:
        latest_summaries = (
            AssessmentRun.objects.filter(sbom_id__in=sbom_ids, category="security", status="completed")
            .order_by("sbom_id", "-created_at")
            .distinct("sbom_id")
            .values("sbom_id", *RESULT_SUMMARY_COLUMNS)
        )
        counts_by_sbom = {}
        for row in latest_summaries:
            reconstructed = reconstruct_result_summary(row)
            counts = extract_severity_counts(reconstructed)
            # A skipped run stores zero findings, which is what a clean scan
            # stores. Without this the row reads "Clean" for an artifact nothing
            # could be matched against.
            counts["scanned_nothing"] = result_scanned_nothing(reconstructed)
            counts_by_sbom[str(row["sbom_id"])] = counts
        for item in sbom_items:
            item["vuln"] = counts_by_sbom.get(str(item.get("sbom", {}).get("id", "")))
        return

    # DISTINCT ON (sbom_id, plugin_name) with newest-first ordering returns each
    # provider's latest run per SBOM — never every historical result blob.
    latest_runs = (
        AssessmentRun.objects.filter(sbom_id__in=sbom_ids, category="security", status="completed")
        .order_by("sbom_id", "plugin_name", "-created_at")
        .distinct("sbom_id", "plugin_name")
        .values("sbom_id", "result")
    )
    results_by_sbom: dict[str, list[dict[str, Any] | None]] = {}
    for run in latest_runs:
        results_by_sbom.setdefault(str(run["sbom_id"]), []).append(run["result"])

    vex_statements = load_vex_suppressions(component_id) if results_by_sbom else []
    for item in sbom_items:
        provider_results = results_by_sbom.get(str(item.get("sbom", {}).get("id", "")))
        if not provider_results:
            item["vuln"] = None
            continue
        # Only when EVERY provider skipped. One scanner failing while another
        # scanned the same artifact still leaves a real verdict, and marking
        # that "Nothing scanned" would hide the scan that worked.
        scanned_nothing = all(result_scanned_nothing(result) for result in provider_results)
        rows = extract_finding_rows(merge_findings_by_alias(provider_results), vex_statements)
        if rows:
            item["vuln"] = {
                "total": len(rows),
                "critical": sum(1 for row in rows if row["severity"] == "critical"),
                "high": sum(1 for row in rows if row["severity"] == "high"),
                "medium": sum(1 for row in rows if row["severity"] == "medium"),
                "low": sum(1 for row in rows if row["severity"] == "low"),
            }
        else:
            # A result can carry a summary but no findings list (summary-only
            # providers, legacy blobs). Fall back to the stored summary — the
            # same fallback the header badge uses — so the row never reads
            # "Clean" while the badge shows counts.
            item["vuln"] = max(
                (extract_severity_counts(result) for result in provider_results),
                key=lambda c: c["total"],
            )
        item["vuln"]["scanned_nothing"] = scanned_nothing


def _summary_artifacts(sbom_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The compact card view: the newest artifact of each (format, bom_type).

    Keyed the same way as ``Component.get_latest_sboms_by_format``, so the card
    and the release rollup agree on what "latest" means. Both halves of the key
    earn their place: a component published as CycloneDX and SPDX has two
    artifacts of bom_type ``sbom``, and a VEX or CBOM shares the cyclonedx
    format with the SBOM. Dropping either half hides a current artifact behind
    an unrelated one.

    VEX resolution is latest-wins, so the card shows just the newest VEX; the
    superseded ones (and the full SBOM history) live behind the "View all"
    toggle (``?full=1``).
    """
    by_date = sorted(
        sbom_items,
        key=lambda x: x["sbom"]["created_at"].timestamp() if x["sbom"].get("created_at") else 0.0,
        reverse=True,
    )
    seen: set[tuple[str, str]] = set()
    summary: list[dict[str, Any]] = []
    for item in by_date:
        key = (item["sbom"].get("format") or "", item["sbom"].get("bom_type") or "sbom")
        if key not in seen:
            seen.add(key)
            summary.append(item)
    return summary


def build_sboms_table_context(
    request: HttpRequest, component_id: str, is_public_view: bool
) -> ServiceResult[dict[str, Any]]:
    status_code, component = get_component(request, component_id)
    if status_code != 200:
        return ServiceResult.failure(component.get("detail", "Unknown error"))

    status_code, sboms = list_component_sboms(request, component_id, page=1, page_size=-1, include_all_types=True)
    if status_code != 200:
        return ServiceResult.failure(sboms.get("detail", "Failed to load SBOMs"))

    sbom_items = sboms.get("items", [])

    # Sort SBOMs by name (alphabetically) then by created_at (newest first)
    sbom_items = sorted(
        sbom_items,
        key=lambda x: (
            x["sbom"]["name"].lower(),
            -x["sbom"]["created_at"].timestamp() if x["sbom"]["created_at"] else 0,
        ),
    )

    # ``assessments`` is already populated by ``list_component_sboms`` from a
    # single batched query (including ``skipped_count``), so no per-SBOM
    # enrichment loop is needed here. The earlier
    # ``get_sbom_assessment_badge``-per-row loop reissued the same latest-runs
    # subquery and display-name lookup that the batched API path had already
    # done — ~3 extra queries per row on top of the inner N+1 — and was the
    # dominant slow path on the component detail page.

    # The component card shows only the latest artifact of each type; ?full=1
    # (the "View all" toggle) returns the complete history.
    full_view = request.GET.get("full") == "1"
    total_artifact_count = len(sbom_items)
    if not full_view:
        sbom_items = _summary_artifacts(sbom_items)

    if not is_public_view:
        _attach_vulnerability_counts(sbom_items, component_id, merged=not full_view)

    context = {
        "component_id": component_id,
        "sboms": sbom_items,
        "is_public_view": is_public_view,
        "has_crud_permissions": component.get("has_crud_permissions", False),
        "full_view": full_view,
        "show_view_all": not full_view and total_artifact_count > len(sbom_items),
        "total_artifact_count": total_artifact_count,
    }

    if not is_public_view:
        team_key = number_to_random_token(component.get("team_id"))
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return ServiceResult.failure(team.get("detail", "Failed to load team"))

        context.update(
            {
                "team_billing_plan": team.billing_plan,
                "team_key": team_key,
                "delete_form": SbomDeleteForm(),
            }
        )

    return ServiceResult.success(context)


def delete_sbom_from_request(request: HttpRequest) -> ServiceResult[None]:
    form = SbomDeleteForm(request.POST)
    if not form.is_valid():
        return ServiceResult.failure(form.errors.as_text())

    result = delete_sbom_record(request, form.cleaned_data["sbom_id"])
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to delete SBOM", status_code=result.status_code)

    return ServiceResult.success()
