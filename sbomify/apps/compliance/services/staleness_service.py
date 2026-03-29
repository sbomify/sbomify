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
        DocumentKind.RISK_ASSESSMENT,
        DocumentKind.USER_INSTRUCTIONS,
        DocumentKind.DECOMMISSIONING_GUIDE,
        DocumentKind.DECLARATION_OF_CONFORMITY,
        DocumentKind.EARLY_WARNING,
        DocumentKind.FULL_NOTIFICATION,
        DocumentKind.FINAL_REPORT,
    ],
    "security_contact": [
        DocumentKind.SECURITY_TXT,
        DocumentKind.VDP,
        DocumentKind.USER_INSTRUCTIONS,
        DocumentKind.EARLY_WARNING,
        DocumentKind.FULL_NOTIFICATION,
        DocumentKind.FINAL_REPORT,
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
    """Check which documents are stale.

    Returns:
        {
            "stale_documents": ["vdp", "security_txt", ...],
            "stale_steps": [],  # always empty — see NOTE below
            "has_new_sbom": False,
        }
    """
    stale_docs = list(
        CRAGeneratedDocument.objects.filter(
            assessment=assessment,
            is_stale=True,
        ).values_list("document_kind", flat=True)
    )

    # NOTE: We intentionally do not reverse-map stale documents to steps here.
    # Because document kinds overlap across sources (e.g., VDP appears in both
    # "product" and "vuln_handling"), reverse-mapping would produce false
    # positives. Accurate step-level staleness requires tracking the change
    # source — a future enhancement. For now, stale_steps is empty and the
    # UI relies on stale_documents for display.
    stale_steps: set[int] = set()

    # Check for new SBOMs since last assessment update (single query)
    from django.db.models import Max

    from sbomify.apps.sboms.models import SBOM

    latest_sbom_date = (
        SBOM.objects.filter(component__projects__products__id=assessment.product_id)
        .aggregate(latest=Max("created_at"))
        .get("latest")
    )
    has_new_sbom = latest_sbom_date is not None and latest_sbom_date > assessment.updated_at

    return ServiceResult.success(
        {
            "stale_documents": stale_docs,
            "stale_steps": sorted(stale_steps),
            "has_new_sbom": has_new_sbom,
        }
    )
