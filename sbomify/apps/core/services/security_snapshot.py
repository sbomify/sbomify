"""The shared component security snapshot for overview and inventory pages."""

from __future__ import annotations

from datetime import timedelta
from math import ceil
from typing import Any

from django.utils import timezone

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK as _SEVERITY_RANK


def build_component_security_picture(
    component_ids: list[str], component_names: dict[str, str], sla_matrix: dict[str, Any]
) -> dict[str, Any]:
    """Worst non-suppressed findings across the given components."""
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.models import Finding
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        extract_severity_counts,
        merge_findings_by_alias,
        result_scanned_nothing,
        severity_counts_from_rows,
    )

    latest_sboms = (
        SBOM.objects.filter(component_id__in=component_ids, bom_type=SBOM.BomType.SBOM)
        .order_by("component_id", "-created_at")
        .distinct("component_id")
        .values("id", "component_id", "version", "created_at")
    )
    sbom_meta = {str(row["id"]): row for row in latest_sboms}
    runs = (
        AssessmentRun.objects.filter(sbom_id__in=sbom_meta.keys(), category="security", status="completed")
        .order_by("sbom_id", "plugin_name", "-created_at", "-id")
        .distinct("sbom_id", "plugin_name")
        .values("id", "sbom_id", "result_summary", "result_skipped", "created_at")
    )
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
    # scoped to the same latest runs as the summary and assessment state above.
    indexed_by_sbom: dict[str, dict[str, list[dict[str, Any]]]] = {}
    malicious_ids: set[str] = set()
    for finding in Finding.objects.filter(run_id__in=[run["id"] for run in runs], is_current=True).values(
        "sbom_id",
        "advisory_id",
        "aliases",
        "severity",
        "cvss_score",
        "package_name",
        "package_version",
        "ecosystem",
        "vex_state",
        "malicious",
    ):
        if finding["malicious"]:
            malicious_ids.update(alias.lower() for alias in (finding["advisory_id"], *finding["aliases"]))
        indexed_by_sbom.setdefault(str(finding["sbom_id"]), {}).setdefault(finding["ecosystem"], []).append(
            {
                "id": finding["advisory_id"],
                "aliases": finding["aliases"],
                "severity": finding["severity"],
                "cvss_score": finding["cvss_score"],
                "analysis_state": finding["vex_state"],
                "component": {
                    "name": finding["package_name"],
                    "version": finding["package_version"],
                    "ecosystem": finding["ecosystem"],
                },
            }
        )
    findings: list[dict[str, Any]] = []
    counts_by_component: dict[str, dict[str, int]] = {}
    unassessed: set[str] = set(component_ids)
    kev_ids = kev_ids_for_serialization() if results_by_sbom else frozenset()
    for sbom_id, provider_results in results_by_sbom.items():
        meta = sbom_meta[sbom_id]
        component_id = meta["component_id"]
        rows = [
            row
            for ecosystem_findings in indexed_by_sbom.get(sbom_id, {}).values()
            for row in extract_finding_rows(
                merge_findings_by_alias([{"findings": ecosystem_findings}]), kev_ids=kev_ids
            )
        ]
        if not all(result_scanned_nothing(result) for result in provider_results):
            unassessed.discard(component_id)
        # Keep summary-only providers visible, as on the product detail page.
        counts_by_component[component_id] = (
            severity_counts_from_rows(rows)
            if rows
            else max(
                (extract_severity_counts(result) for result in provider_results), key=lambda counts: counts["total"]
            )
        )
        for row in rows:
            if row.get("vex_suppressed"):
                continue
            row["malicious"] = any(alias.lower() in malicious_ids for alias in (row["id"], *row["aliases"]))
            findings.append(
                {
                    **row,
                    "component_id": component_id,
                    "component_name": component_names.get(component_id, ""),
                    "sbom_version": meta["version"],
                    "scanned_at": scanned_at_by_sbom.get(sbom_id),
                }
            )
    _attach_patch_sla(findings, component_ids, sla_matrix)
    # Active exploitation leads, followed by a breached SLA and severity.
    findings.sort(
        key=lambda r: (
            not r["malicious"],
            not r["kev"],
            not r["sla"]["overdue"],
            _SEVERITY_RANK.get(r["severity"], 5),
            r["sla"]["remaining_seconds"] if r["sla"]["remaining_seconds"] is not None else float("inf"),
            -(r["scanned_at"].timestamp() if r["scanned_at"] else 0.0),
            -(r.get("cvss_score") or 0),
        )
    )
    return {
        "findings": findings,
        "counts": counts_by_component,
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
        seconds = (min(sightings) + timedelta(days=days) - now).total_seconds() if days and sightings else None
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
        finding["decision"] = {
            "exploitable": "Exploitable",
            "in_triage": "In triage",
            "false_positive": "False positive",
            "not_affected": "Not affected",
            "resolved": "Resolved",
            "resolved_with_pedigree": "Resolved",
        }.get(finding["vex_state"], "Not reviewed")
