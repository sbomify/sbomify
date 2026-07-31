"""The dashboard's security picture: the needs-attention digest.

The digest reuses the component drill-down's pipeline (provider-latest runs
merged by advisory alias, VEX-aware), so a finding reads identically on the
dashboard, the component page, and the product page — suppressed findings
never appear here.
"""

from __future__ import annotations

from typing import Any, cast

from django.core.cache import cache as django_cache

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK as _SEVERITY_RANK

_CACHE_TTL_SECONDS = 60
_DIGEST_LIMIT = 3


def _digest_rows(component_ids: list[str], component_names: dict[str, str]) -> list[dict[str, Any]]:
    """Worst non-suppressed findings across the given components."""
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.vulnerability_scanning.utils import extract_finding_rows, merge_findings_by_alias
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    latest_sboms = (
        SBOM.objects.filter(component_id__in=component_ids, bom_type=SBOM.BomType.SBOM)
        .order_by("component_id", "-created_at")
        .distinct("component_id")
        .values("id", "component_id", "version")
    )
    sbom_meta = {str(row["id"]): row for row in latest_sboms}
    runs = (
        AssessmentRun.objects.filter(sbom_id__in=sbom_meta.keys(), category="security", status="completed")
        .order_by("sbom_id", "plugin_name", "-created_at")
        .distinct("sbom_id", "plugin_name")
        .values("sbom_id", "result", "created_at")
    )
    results_by_sbom: dict[str, list[dict[str, Any] | None]] = {}
    scanned_at_by_sbom: dict[str, Any] = {}
    for run in runs:
        sbom_key = str(run["sbom_id"])
        results_by_sbom.setdefault(sbom_key, []).append(run["result"])
        if sbom_key not in scanned_at_by_sbom or run["created_at"] > scanned_at_by_sbom[sbom_key]:
            scanned_at_by_sbom[sbom_key] = run["created_at"]

    vex_cache: dict[Any, list[dict[str, Any]]] = {}
    findings: list[dict[str, Any]] = []
    for sbom_id, provider_results in results_by_sbom.items():
        meta = sbom_meta[sbom_id]
        component_id = meta["component_id"]
        merged = merge_findings_by_alias(provider_results)
        # VEX lives in S3; skip the fetch entirely for clean components.
        statements = load_vex_suppressions(component_id, cache=vex_cache) if merged["findings"] else []
        for row in extract_finding_rows(merged, statements):
            if row.get("vex_suppressed"):
                continue
            findings.append(
                {
                    **row,
                    "component_id": component_id,
                    "component_name": component_names.get(component_id, ""),
                    "sbom_version": meta["version"],
                    "scanned_at": scanned_at_by_sbom.get(sbom_id),
                }
            )
    # Worst severity first; within a severity band, the most recently updated
    # component leads, so a critical from today's scan outranks one from last
    # month's.
    findings.sort(
        key=lambda r: (
            _SEVERITY_RANK.get(r["severity"], 5),
            -(r["scanned_at"].timestamp() if r["scanned_at"] else 0.0),
            -(r.get("cvss_score") or 0),
        )
    )
    return findings[:_DIGEST_LIMIT]


def build_dashboard_context(team_id: int) -> dict[str, Any]:
    cache_key = f"dashboard-page:{team_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return cast("dict[str, Any]", cached)

    components = dict(Component.objects.filter(team_id=team_id).values_list("id", "name"))
    has_artifacts = SBOM.objects.filter(component__team_id=team_id).exists()

    context = {
        "is_first_visit": not has_artifacts,
        "needs_attention": _digest_rows(list(components), components) if has_artifacts else [],
    }
    django_cache.set(cache_key, context, _CACHE_TTL_SECONDS)
    return context
