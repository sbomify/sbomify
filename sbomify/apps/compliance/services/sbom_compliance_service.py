"""SBOM compliance service for BSI TR-03183-2 assessment status.

Provides functions to check BSI compliance status per product component
and evaluate overall SBOM compliance gates.
"""

from __future__ import annotations

from django.db.models import Prefetch
from packaging.version import Version

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

BSI_PLUGIN_NAME = "bsi-tr03183-v2.1-compliance"

# Minimum format versions for BSI TR-03183-2 compliance
_MIN_FORMAT_VERSIONS: dict[str, str] = {
    "cyclonedx": "1.6",
    "spdx": "3.0.1",
}


def _is_format_compliant(sbom_format: str | None, format_version: str | None) -> bool:
    """Check whether the SBOM format version meets BSI TR-03183-2 requirements.

    CycloneDX >= 1.6 or SPDX >= 3.0.1 is required.
    """
    if not sbom_format or not format_version:
        return False

    min_version_str = _MIN_FORMAT_VERSIONS.get(sbom_format.lower())
    if not min_version_str:
        return False

    try:
        return Version(format_version) >= Version(min_version_str)
    except (ValueError, TypeError):
        return False


def _build_bsi_assessment_dict(run: AssessmentRun) -> dict[str, object]:
    """Build the bsi_assessment dict from an AssessmentRun."""
    result = run.result or {}
    summary = result.get("summary", {})
    raw_findings = result.get("findings", [])

    # Extract failing findings with fix guidance
    failing_checks: list[dict[str, str]] = []
    for f in raw_findings:
        if f.get("status") == "fail":
            failing_checks.append(
                {
                    "id": f.get("id", ""),
                    "title": f.get("title", ""),
                    "description": f.get("description", ""),
                    "remediation": f.get("remediation", ""),
                }
            )

    return {
        "status": run.status,
        "pass_count": summary.get("pass_count", 0),
        "fail_count": summary.get("fail_count", 0),
        "warning_count": summary.get("warning_count", 0),
        "assessed_at": run.created_at.isoformat() if run.created_at else None,
        "failing_checks": failing_checks,
    }


def get_bsi_assessment_status(product: Product) -> ServiceResult[dict[str, object]]:
    """Query AssessmentRun for BSI plugin per product component.

    Returns a ServiceResult containing component-level BSI assessment
    details and an overall summary.

    """
    from django.db.models import OuterRef, Subquery

    # Annotate each component with its latest SBOM id to avoid loading all history
    latest_sbom_subquery = SBOM.objects.filter(component=OuterRef("pk")).order_by("-created_at").values("pk")[:1]

    components = list(
        Component.objects.filter(projects__products=product)
        .order_by("name")
        .distinct()
        .annotate(latest_sbom_id=Subquery(latest_sbom_subquery))
    )

    # Batch-fetch the latest SBOMs and their BSI runs
    sbom_ids = [c.latest_sbom_id for c in components if c.latest_sbom_id]
    sboms_by_id: dict[str, SBOM] = {}
    if sbom_ids:
        sbom_qs = SBOM.objects.filter(pk__in=sbom_ids).prefetch_related(
            Prefetch(
                "assessment_runs",
                queryset=AssessmentRun.objects.filter(plugin_name=BSI_PLUGIN_NAME).order_by("-created_at"),
                to_attr="prefetched_bsi_runs",
            )
        )
        sboms_by_id = {s.pk: s for s in sbom_qs}

    component_results: list[dict[str, object]] = []
    components_with_sbom = 0
    components_passing_bsi = 0

    for component in components:
        latest_sbom: SBOM | None = sboms_by_id.get(component.latest_sbom_id) if component.latest_sbom_id else None

        has_sbom = latest_sbom is not None
        sbom_format: str | None = latest_sbom.format if latest_sbom else None
        sbom_format_version: str | None = latest_sbom.format_version if latest_sbom else None
        format_compliant = _is_format_compliant(sbom_format, sbom_format_version)

        bsi_assessment: dict[str, object] | None = None
        is_passing = False

        if has_sbom:
            components_with_sbom += 1

            prefetched_runs = getattr(latest_sbom, "prefetched_bsi_runs", [])
            latest_run = prefetched_runs[0] if prefetched_runs else None

            if latest_run:
                bsi_assessment = _build_bsi_assessment_dict(latest_run)
                if latest_run.status == "completed" and bsi_assessment["fail_count"] == 0 and format_compliant:
                    is_passing = True

        if is_passing:
            components_passing_bsi += 1

        bsi_status: str | None = None
        if bsi_assessment:
            bsi_status = str(bsi_assessment.get("status")) if bsi_assessment.get("status") is not None else None

        component_results.append(
            {
                "component_id": component.id,
                "component_name": component.name,
                "component_url": f"/component/{component.id}/",
                "has_sbom": has_sbom,
                "sbom_format": sbom_format,
                "sbom_format_version": sbom_format_version or None,
                "format_compliant": format_compliant,
                "bsi_assessment": bsi_assessment,
                "bsi_status": bsi_status,
            }
        )

    total_components = len(component_results)
    overall_gate = components_passing_bsi > 0

    return ServiceResult.success(
        {
            "components": component_results,
            "summary": {
                "total_components": total_components,
                "components_with_sbom": components_with_sbom,
                "components_passing_bsi": components_passing_bsi,
                "overall_gate": overall_gate,
            },
        }
    )


def check_sbom_gate(product: Product) -> ServiceResult[bool]:
    """Check whether the product passes the SBOM compliance gate.

    At least one component must have a passing BSI assessment.
    Passing means AssessmentRun with status=completed and fail_count=0.
    """
    result = get_bsi_assessment_status(product)
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to get BSI assessment status")

    if not result.value:
        return ServiceResult.success(False)
    summary = result.value["summary"]
    gate_passes = bool(isinstance(summary, dict) and summary.get("overall_gate", False))
    return ServiceResult.success(gate_passes)
