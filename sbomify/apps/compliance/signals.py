"""Staleness signals for CRA Compliance documents.

When upstream data changes (product info, contacts, SBOMs), mark affected
generated documents as stale so they can be regenerated.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.compliance.models import CRAAssessment

logger = logging.getLogger(__name__)


def _mark_stale_for_assessments(assessments: QuerySet[CRAAssessment], change_source: str) -> None:
    """Mark stale documents for all assessments in a single batch UPDATE."""
    from sbomify.apps.compliance.models import CRAGeneratedDocument
    from sbomify.apps.compliance.services.staleness_service import STALENESS_MAP

    affected_kinds = STALENESS_MAP.get(change_source, [])
    if not affected_kinds:
        return

    count = CRAGeneratedDocument.objects.filter(
        assessment__in=assessments,
        document_kind__in=affected_kinds,
        is_stale=False,
    ).update(is_stale=True)

    if count:
        logger.debug("Marked %d docs stale (source: %s)", count, change_source)


@receiver(post_save, sender="core.Product")
@receiver(post_save, sender="sboms.Product")
def on_product_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When a product's details change, mark related CRA documents stale."""
    if created:
        return
    try:
        assessments = CRAAssessment.objects.filter(product_id=instance.pk)
        _mark_stale_for_assessments(assessments, "product")
    except Exception:
        logger.exception("Error in on_product_save signal for product %s", getattr(instance, "pk", "?"))


@receiver(post_save, sender="sboms.SBOM")
def on_sbom_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When a new SBOM is uploaded, mark risk assessment stale."""
    if not created:
        return
    try:
        assessments = CRAAssessment.objects.filter(
            product__projects__components__id=instance.component_id,
        ).distinct()
        _mark_stale_for_assessments(assessments, "sbom")
    except Exception:
        logger.exception("Error in on_sbom_save signal for SBOM %s", getattr(instance, "pk", "?"))


@receiver(post_save, sender="teams.ContactEntity")
def on_contact_entity_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When manufacturer contact info changes, mark affected documents stale."""
    try:
        if not instance.is_manufacturer:
            return
        team = instance.profile.team
        assessments = CRAAssessment.objects.filter(team=team)
        _mark_stale_for_assessments(assessments, "manufacturer_contact")
    except Exception:
        logger.exception("Error in on_contact_entity_save signal for entity %s", getattr(instance, "pk", "?"))


@receiver(post_save, sender="teams.ContactProfileContact")
def on_contact_profile_contact_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When security contact changes, mark affected documents stale."""
    try:
        if not instance.is_security_contact:
            return
        team = instance.entity.profile.team
        assessments = CRAAssessment.objects.filter(team=team)
        _mark_stale_for_assessments(assessments, "security_contact")
    except Exception:
        logger.exception("Error in on_contact_profile_contact_save signal for contact %s", getattr(instance, "pk", "?"))


_FIELD_SOURCE_MAP: dict[str, str] = {
    # Step 1 fields — affect declaration, risk assessment, user instructions, etc.
    "intended_use": "product",
    "target_eu_markets": "product",
    "support_period_end": "product",
    "product_category": "product",
    "is_open_source_steward": "product",
    "conformity_assessment_procedure": "product",
    # Step 3 fields
    "vdp_url": "vuln_handling",
    "acknowledgment_timeline_days": "vuln_handling",
    "security_contact_url": "vuln_handling",
    "csirt_country": "article_14",
    "csirt_contact_email": "article_14",
    "enisa_srp_registered": "article_14",
    # Step 4 fields
    "update_frequency": "user_info",
    "update_method": "user_info",
    "update_channel_url": "user_info",
    "support_email": "user_info",
    "support_url": "user_info",
    "support_phone": "user_info",
    "support_hours": "user_info",
    "data_deletion_instructions": "user_info",
}


@receiver(post_save, sender="compliance.CRAAssessment")
def on_assessment_save(sender: type, instance: CRAAssessment, created: bool, **kwargs: Any) -> None:
    """When CRA assessment fields change, mark affected documents stale.

    We use update_fields to determine what changed. Only fields present in
    _FIELD_SOURCE_MAP trigger staleness; wizard-state-only saves (status,
    current_step, completed_steps, updated_at) are ignored.
    If update_fields is None (full save), we conservatively mark all sources.
    """
    if created:
        return

    try:
        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            sources = {_FIELD_SOURCE_MAP[f] for f in update_fields if f in _FIELD_SOURCE_MAP}
        else:
            # Full save (no update_fields) — conservatively mark all sources stale.
            sources = set(_FIELD_SOURCE_MAP.values())

        if not sources:
            return

        from sbomify.apps.compliance.services.staleness_service import mark_stale_documents

        for source in sources:
            mark_stale_documents(instance, source)
    except Exception:
        logger.exception("Error in on_assessment_save signal for assessment %s", getattr(instance, "pk", "?"))
