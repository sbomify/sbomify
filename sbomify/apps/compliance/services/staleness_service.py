"""Staleness detection and document refresh for CRA Compliance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sbomify.apps.compliance.models import CRAGeneratedDocument
from sbomify.apps.core.services.results import ServiceResult

if TYPE_CHECKING:
    from sbomify.apps.compliance.models import CRAAssessment

DocumentKind = CRAGeneratedDocument.DocumentKind

# Which data sources affect which document kinds
STALENESS_MAP: dict[str, list[str]] = {
    "product": [
        DocumentKind.VDP,
        DocumentKind.RISK_ASSESSMENT,
        DocumentKind.USER_INSTRUCTIONS,
        DocumentKind.DECLARATION_OF_CONFORMITY,
        DocumentKind.SECURITY_TXT,
    ],
    "manufacturer_contact": [
        DocumentKind.VDP,
        DocumentKind.SECURITY_TXT,
        DocumentKind.DECLARATION_OF_CONFORMITY,
        DocumentKind.EARLY_WARNING,
        DocumentKind.FULL_NOTIFICATION,
        DocumentKind.FINAL_REPORT,
    ],
    "security_contact": [
        DocumentKind.SECURITY_TXT,
        DocumentKind.VDP,
        DocumentKind.EARLY_WARNING,
    ],
    "sbom": [
        DocumentKind.RISK_ASSESSMENT,
    ],
    "vuln_handling": [
        DocumentKind.VDP,
        DocumentKind.SECURITY_TXT,
    ],
    "article_14": [
        DocumentKind.EARLY_WARNING,
        DocumentKind.FULL_NOTIFICATION,
        DocumentKind.FINAL_REPORT,
    ],
    "user_info": [
        DocumentKind.USER_INSTRUCTIONS,
        DocumentKind.DECOMMISSIONING_GUIDE,
    ],
}

# Steps affected by each change source
_STEP_MAP: dict[str, list[int]] = {
    "product": [1],
    "sbom": [2],
    "manufacturer_contact": [4],
    "security_contact": [3, 4],
    "vuln_handling": [3],
    "article_14": [3],
    "user_info": [4],
}


def mark_stale_documents(assessment: CRAAssessment, change_source: str) -> int:
    """Set is_stale=True on affected CRAGeneratedDocument records.

    Only marks documents that actually exist (have been generated at least once).
    Returns count of documents marked stale.
    """
    affected_kinds = STALENESS_MAP.get(change_source, [])
    if not affected_kinds:
        return 0

    return CRAGeneratedDocument.objects.filter(
        assessment=assessment,
        document_kind__in=affected_kinds,
        is_stale=False,
    ).update(is_stale=True)


def check_staleness(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Check which documents and steps are stale.

    Returns:
        {
            "stale_documents": ["vdp", "security_txt", ...],
            "stale_steps": [1, 3],
            "has_new_sbom": False,
        }
    """
    stale_docs = list(
        CRAGeneratedDocument.objects.filter(
            assessment=assessment,
            is_stale=True,
        ).values_list("document_kind", flat=True)
    )

    # Determine which steps are stale based on which doc kinds are stale
    stale_steps: set[int] = set()
    for source, kinds in STALENESS_MAP.items():
        if any(k in stale_docs for k in kinds):
            stale_steps.update(_STEP_MAP.get(source, []))

    # Check for new SBOMs since last assessment update
    from sbomify.apps.sboms.models import Component

    components = Component.objects.filter(projects__products=assessment.product).distinct()
    has_new_sbom = False
    for component in components:
        latest = component.sbom_set.order_by("-created_at").first()
        if latest and latest.created_at > assessment.updated_at:
            has_new_sbom = True
            break

    return ServiceResult.success(
        {
            "stale_documents": stale_docs,
            "stale_steps": sorted(stale_steps),
            "has_new_sbom": has_new_sbom,
        }
    )
