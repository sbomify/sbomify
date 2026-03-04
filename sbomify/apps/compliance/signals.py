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
    """Mark stale documents for each assessment linked to the change."""
    from sbomify.apps.compliance.services.staleness_service import mark_stale_documents

    for assessment in assessments:
        count = mark_stale_documents(assessment, change_source)
        if count:
            logger.debug("Marked %d docs stale for assessment %s (source: %s)", count, assessment.id, change_source)


@receiver(post_save, sender="core.Product")
def on_product_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When a product's details change, mark related CRA documents stale."""
    if created:
        return
    assessments = CRAAssessment.objects.filter(product=instance)
    _mark_stale_for_assessments(assessments, "product")


@receiver(post_save, sender="sboms.SBOM")
def on_sbom_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When a new SBOM is uploaded, mark risk assessment stale."""
    if not created:
        return
    assessments = CRAAssessment.objects.filter(
        product__projects__components=instance.component,
    ).distinct()
    _mark_stale_for_assessments(assessments, "sbom")


@receiver(post_save, sender="teams.ContactEntity")
def on_contact_entity_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When manufacturer contact info changes, mark affected documents stale."""
    if not instance.is_manufacturer:
        return
    team = instance.profile.team
    assessments = CRAAssessment.objects.filter(team=team)
    _mark_stale_for_assessments(assessments, "manufacturer_contact")


@receiver(post_save, sender="teams.ContactProfileContact")
def on_contact_profile_contact_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """When security contact changes, mark affected documents stale."""
    if not instance.is_security_contact:
        return
    team = instance.entity.profile.team
    assessments = CRAAssessment.objects.filter(team=team)
    _mark_stale_for_assessments(assessments, "security_contact")


@receiver(post_save, sender="compliance.CRAAssessment")
def on_assessment_save(sender: type, instance: CRAAssessment, created: bool, **kwargs: Any) -> None:
    """When CRA assessment fields change, mark affected documents stale.

    We use update_fields to determine what changed. If update_fields is None
    (full save), we conservatively mark all document types.
    """
    if created:
        return

    update_fields = kwargs.get("update_fields")

    _FIELD_SOURCE_MAP: dict[str, str] = {
        "vdp_url": "vuln_handling",
        "acknowledgment_timeline_days": "vuln_handling",
        "security_contact_url": "vuln_handling",
        "csirt_country": "article_14",
        "csirt_contact_email": "article_14",
        "enisa_srp_registered": "article_14",
        "update_frequency": "user_info",
        "update_method": "user_info",
        "update_channel_url": "user_info",
        "support_email": "user_info",
        "support_url": "user_info",
        "support_phone": "user_info",
        "support_hours": "user_info",
        "data_deletion_instructions": "user_info",
    }

    if update_fields is not None:
        sources = {_FIELD_SOURCE_MAP[f] for f in update_fields if f in _FIELD_SOURCE_MAP}
    else:
        sources = set(_FIELD_SOURCE_MAP.values())

    from sbomify.apps.compliance.services.staleness_service import mark_stale_documents

    for source in sources:
        mark_stale_documents(instance, source)
