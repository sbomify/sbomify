"""The shared component security snapshot for overview and inventory pages."""

from __future__ import annotations

from datetime import timedelta
from math import ceil
from typing import Any

from django.utils import timezone

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK as _SEVERITY_RANK
from sbomify.apps.vulnerability_scanning.utils import state_label


def build_component_security_picture(
    component_ids: list[str],
    component_names: dict[str, str],
    sla_matrix: dict[str, Any],
    sbom_overrides: dict[str, list[str]] | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Worst non-suppressed findings across the given components.

    Each component is read at its newest SBOM unless ``sbom_overrides`` names
    the SBOMs to read for it instead: the ones a release shipped, or one
    version picked by hand. ``release_id`` names the release those SBOMs came
    from, so each is read at the newest run that covers that release.
    """
    from django.db.models import Q

    from sbomify.apps.plugins.latest import latest_run_ids
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.models import Finding
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        extract_severity_counts,
        merge_findings_by_alias,
        package_scopes,
        result_scanned_nothing,
        severity_counts_from_rows,
        vulnerability_findings,
    )

    overrides = {key: value for key, value in (sbom_overrides or {}).items() if key in set(component_ids)}
    latest_sboms = (
        SBOM.objects.filter(
            component_id__in=[cid for cid in component_ids if cid not in overrides], bom_type=SBOM.BomType.SBOM
        )
        .order_by("component_id", "-created_at")
        .distinct("component_id")
        .values("id", "component_id", "version", "created_at")
    )
    chosen_sboms = SBOM.objects.filter(
        id__in=[sbom_id for ids in overrides.values() for sbom_id in ids],
        component_id__in=list(overrides),
        bom_type=SBOM.BomType.SBOM,
    ).values("id", "component_id", "version", "created_at")
    sbom_meta = {str(row["id"]): row for row in [*latest_sboms, *chosen_sboms]}
    security_runs = AssessmentRun.objects.filter(category="security", status="completed")
    latest_ids = latest_run_ids(security_runs, sbom_meta.keys())
    # Two releases can share an SBOM yet each hold a live run of one scanner, because a
    # run is annotated with its own releases' VEX. The newest run overall may then carry
    # another release's suppressions, so a release reads the newest run that covers it,
    # and falls back to the newest run for a scanner none of whose runs name it.
    release_ids = set(
        latest_run_ids(
            security_runs.filter(releases=release_id), [sbom_id for ids in overrides.values() for sbom_id in ids]
        )
        if release_id
        else []
    )
    candidates = list(
        AssessmentRun.objects.filter(id__in=[*latest_ids, *release_ids])
        .order_by("sbom_id", "plugin_name")
        .values("id", "sbom_id", "plugin_name", "result_summary", "result_skipped", "created_at")
    )
    release_pairs = {(run["sbom_id"], run["plugin_name"]) for run in candidates if run["id"] in release_ids}
    runs = [
        run
        for run in candidates
        if run["id"] in release_ids or (run["sbom_id"], run["plugin_name"]) not in release_pairs
    ]
    results_by_sbom: dict[str, list[dict[str, Any] | None]] = {}
    scanned_at_by_sbom: dict[str, Any] = {}
    for run in runs:
        sbom_key = str(run["sbom_id"])
        results_by_sbom.setdefault(sbom_key, []).append(
            {"summary": run["result_summary"], "metadata": {"skipped": run["result_skipped"]}}
        )
        if sbom_key not in scanned_at_by_sbom or run["created_at"] > scanned_at_by_sbom[sbom_key]:
            scanned_at_by_sbom[sbom_key] = run["created_at"]

    # Workspace metrics need every occurrence, but never the full scanner blobs.
    # Use the projection maintained by scan completion and VEX re-annotation,
    # scoped to the same latest runs as the summary and assessment state above. A
    # release's own run need not be the newest, so its rows are read without is_current.
    indexed_by_sbom: dict[str, list[dict[str, Any]]] = {}
    malicious_ids: set[str] = set()
    plugin_by_run = {run["id"]: run["plugin_name"] for run in runs}
    run_ids = [run["id"] for run in runs]
    for finding in Finding.objects.filter(
        Q(run_id__in=[rid for rid in run_ids if rid not in release_ids], is_current=True)
        | Q(run_id__in=[rid for rid in run_ids if rid in release_ids])
    ).values(
        "run_id",
        "sbom_id",
        "advisory_id",
        "aliases",
        "severity",
        "cvss_score",
        "package_name",
        "package_version",
        "ecosystem",
        "purl",
        "vex_state",
        "malicious",
    ):
        if finding["malicious"]:
            malicious_ids.update(alias.lower() for alias in (finding["advisory_id"], *finding["aliases"]))
        indexed_by_sbom.setdefault(str(finding["sbom_id"]), []).append(
            {
                "id": finding["advisory_id"],
                "aliases": finding["aliases"],
                "plugin": plugin_by_run.get(finding["run_id"], ""),
                "severity": finding["severity"],
                "cvss_score": finding["cvss_score"],
                "analysis_state": finding["vex_state"],
                "component": {
                    "name": finding["package_name"],
                    "version": finding["package_version"],
                    "ecosystem": finding["ecosystem"],
                    # package_scopes keeps two groupIds with one artifact name apart by it.
                    "purl": finding["purl"],
                },
            }
        )
    findings: list[dict[str, Any]] = []
    counts_by_component: dict[str, dict[str, int]] = {}
    unassessed: set[str] = set(component_ids)
    summary_only: set[str] = set()
    # A component counts as totals-only when none of its SBOMs read here lists findings.
    itemised: set[str] = set()
    kev_ids = kev_ids_for_serialization() if results_by_sbom else frozenset()
    for sbom_id, provider_results in results_by_sbom.items():
        meta = sbom_meta[sbom_id]
        component_id = meta["component_id"]
        # One pass over the SBOM, as its card merges: package_scopes keys on the
        # canonical ecosystem, so OSV's "PyPI" and a purl's "pypi" meet here.
        indexed = vulnerability_findings([{"findings": indexed_by_sbom.get(sbom_id, [])}])
        rows = extract_finding_rows(merge_findings_by_alias([{"findings": indexed}]), kev_ids=kev_ids)
        # Which scanners reported each row, keyed by every id and alias in the package scope
        # the merge used, so OSV's "com.foo:shared" without a purl and Dependency-Track's
        # "shared" with one meet here as they did there. Each row is scoped alongside the
        # findings it came from: it carries one of their purls, so it joins their scope.
        row_components = [
            {
                "component": {
                    "name": row["package"],
                    "version": row["version"],
                    "ecosystem": row["ecosystem"],
                    "purl": row["purl"],
                }
            }
            for row in rows
        ]
        scopes = package_scopes([*indexed, *row_components])
        sources: dict[tuple[str, tuple[str, ...]], set[str]] = {}
        for occurrence, scope in zip(indexed, scopes[: len(indexed)], strict=True):
            for identifier in (occurrence["id"], *occurrence["aliases"]):
                sources.setdefault((identifier.lower(), scope), set()).add(occurrence["plugin"])
        if not all(result_scanned_nothing(result) for result in provider_results):
            unassessed.discard(component_id)
        # Keep summary-only providers visible, as on the product detail page. A component
        # whose scans report totals but no finding rows at all is recorded as such: it has
        # no details to list, unlike one whose findings are all suppressed.
        if rows:
            itemised.add(component_id)
        elif any(extract_severity_counts(result)["total"] for result in provider_results):
            summary_only.add(component_id)
        counts = (
            severity_counts_from_rows(rows)
            if rows
            else max(
                (extract_severity_counts(result) for result in provider_results), key=lambda counts: counts["total"]
            )
        )
        # A release can read several SBOMs of one component, usually one build in two
        # formats. Keep the largest report rather than whichever SBOM came last: adding
        # them would count one build twice, and order must not decide the number.
        previous = counts_by_component.get(component_id)
        if previous is None or counts["total"] > previous["total"]:
            counts_by_component[component_id] = counts
        for row, scope in zip(rows, scopes[len(indexed) :], strict=True):
            if row.get("vex_suppressed"):
                continue
            row["malicious"] = any(alias.lower() in malicious_ids for alias in (row["id"], *row["aliases"]))
            reported_by: set[str] = set()
            for alias in (row["id"], *row["aliases"]):
                reported_by |= sources.get((alias.lower(), scope), set())
            row["sources"] = sorted(reported_by - {""})
            findings.append(
                {
                    **row,
                    "component_id": component_id,
                    "component_name": component_names.get(component_id, ""),
                    "sbom_id": sbom_id,
                    "sbom_version": meta["version"],
                    "scanned_at": scanned_at_by_sbom.get(sbom_id),
                }
            )
    _attach_patch_sla(findings, component_ids, sla_matrix)
    # Active exploitation leads, followed by a breached SLA and severity. The
    # trailing identity makes the order total: without it, ties kept the query's
    # order, which follows random SBOM ids, and a paged list could repeat a row.
    findings.sort(
        key=lambda r: (
            not r["malicious"],
            not r["kev"],
            not r["sla"]["overdue"],
            _SEVERITY_RANK.get(r["severity"], 5),
            r["sla"]["remaining_seconds"] if r["sla"]["remaining_seconds"] is not None else float("inf"),
            -(r["scanned_at"].timestamp() if r["scanned_at"] else 0.0),
            -(r.get("cvss_score") or 0),
            r["id"].casefold(),
            r["component_name"].casefold(),
            r["component_id"],
            (r.get("package") or "").casefold(),
            r.get("version") or "",
        )
    )
    return {
        "findings": findings,
        "counts": counts_by_component,
        "summary_only": summary_only - itemised,
        "unassessed": unassessed,
        "latest_sboms": {row["component_id"]: row for row in sbom_meta.values()},
        "last_scans": {
            sbom_meta[sbom_id]["component_id"]: scanned_at for sbom_id, scanned_at in scanned_at_by_sbom.items()
        },
    }


def _attach_patch_sla(findings: list[dict[str, Any]], component_ids: list[str], matrix: dict[str, Any]) -> None:
    """Join current findings to real first sightings, including provider aliases.

    A new SBOM never resets the clock. Missing history is explicitly unknown;
    resolved lifecycle rows cannot lend an old deadline to a current finding.
    """
    from sbomify.apps.plugins.models import VulnerabilityLifecycle
    from sbomify.apps.vulnerability_scanning.kpis import sla_days_for_severity

    if not findings:
        return
    first_seen = {
        (row.component_id, row.advisory_id.lower()): row.first_seen_at
        for row in VulnerabilityLifecycle.objects.filter(component_id__in=component_ids, resolved_at__isnull=True).only(
            "component_id", "advisory_id", "first_seen_at"
        )
    }
    now = timezone.now()
    for finding in findings:
        days = sla_days_for_severity(matrix, finding["severity"])
        sightings = [
            first_seen[(finding["component_id"], alias.lower())]
            for alias in (finding["id"], *finding["aliases"])
            if (finding["component_id"], alias.lower()) in first_seen
        ]
        seconds = (
            (min(sightings) + timedelta(days=days) - now).total_seconds() if days is not None and sightings else None
        )
        overdue = seconds is not None and seconds < 0
        if days is None:
            label = "Best effort"
        elif seconds is None:
            label = "Awaiting history"
        elif overdue:
            count = ceil(abs(seconds) / 86400)
            label = f"{count} day{'s' if count != 1 else ''} over"
        elif seconds == 0:
            label = "Due today"
        else:
            count = ceil(seconds / 86400)
            label = f"{count} day{'s' if count != 1 else ''} left"
        finding["sla"] = {"label": label, "overdue": overdue, "remaining_seconds": seconds}
        # One wording for an analysis state across the product; a finding nobody
        # has triaged carries no state at all, which is its own answer.
        finding["decision"] = state_label(finding["vex_state"]) or "Not reviewed"
