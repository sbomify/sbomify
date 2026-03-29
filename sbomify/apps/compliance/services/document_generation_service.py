"""CRA document generation service — render Django templates, store in S3."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.template import Context, Engine

from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAGeneratedDocument,
    OSCALFinding,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import ContactEntity, ContactProfileContact

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "document_templates"

_engine = Engine(dirs=[str(_TEMPLATE_DIR)], autoescape=False)

# Map document kinds to template filenames
_TEMPLATE_MAP: dict[str, str] = {
    CRAGeneratedDocument.DocumentKind.VDP: "vdp.md.dtl",
    CRAGeneratedDocument.DocumentKind.SECURITY_TXT: "security_txt.dtl",
    CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT: "risk_assessment.md.dtl",
    CRAGeneratedDocument.DocumentKind.EARLY_WARNING: "early_warning.md.dtl",
    CRAGeneratedDocument.DocumentKind.FULL_NOTIFICATION: "full_notification.md.dtl",
    CRAGeneratedDocument.DocumentKind.FINAL_REPORT: "final_report.md.dtl",
    CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS: "user_instructions.md.dtl",
    CRAGeneratedDocument.DocumentKind.DECOMMISSIONING_GUIDE: "decommissioning_guide.md.dtl",
    CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY: "declaration_of_conformity.md.dtl",
}

# Map EU country codes to language codes for security.txt Preferred-Languages
_COUNTRY_LANGUAGE_MAP: dict[str, str] = {
    "AT": "de",
    "BE": "nl,fr,de",
    "BG": "bg",
    "HR": "hr",
    "CY": "el",
    "CZ": "cs",
    "DK": "da",
    "EE": "et",
    "FI": "fi",
    "FR": "fr",
    "DE": "de",
    "GR": "el",
    "HU": "hu",
    "IE": "en",
    "IT": "it",
    "LV": "lv",
    "LT": "lt",
    "LU": "fr,de",
    "MT": "mt,en",
    "NL": "nl",
    "PL": "pl",
    "PT": "pt",
    "RO": "ro",
    "SK": "sk",
    "SI": "sl",
    "ES": "es",
    "SE": "sv",
}


def _sanitize(value: str, escape_pipe: bool = False) -> str:
    """Strip control characters and newlines from user input for safe template rendering.

    Prevents line-injection in generated plain-text artifacts (e.g., security.txt)
    and Markdown table corruption when escape_pipe=True.
    """
    import re

    # Replace newlines/tabs/carriage returns with spaces, strip other control chars
    sanitized = re.sub(r"[\r\n\t]", " ", value)
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)
    sanitized = re.sub(r" +", " ", sanitized).strip()
    if escape_pipe:
        sanitized = sanitized.replace("|", "\\|")
    return sanitized


def _build_common_context(assessment: CRAAssessment) -> dict[str, Any]:
    """Build context shared across all templates."""
    product = assessment.product

    manufacturer = ContactEntity.objects.filter(
        profile__team=assessment.team,
        is_manufacturer=True,
    ).first()

    security_contact = ContactProfileContact.objects.filter(
        entity__profile__team=assessment.team,
        is_security_contact=True,
    ).first()

    return {
        "product_name": _sanitize(product.name),
        "product_description": _sanitize(product.description or ""),
        "product_uuid": str(product.uuid),
        "intended_use": _sanitize(assessment.intended_use),
        "target_eu_markets": [_sanitize(m)[:2].upper() for m in (assessment.target_eu_markets or [])],
        "support_period_end": (assessment.support_period_end.isoformat() if assessment.support_period_end else None),
        "manufacturer_name": _sanitize(manufacturer.name) if manufacturer else "[Manufacturer Name]",
        "manufacturer_address": _sanitize(manufacturer.address) if manufacturer else "",
        "manufacturer_email": _sanitize(manufacturer.email) if manufacturer else "",
        "manufacturer_website": (
            _sanitize(str(manufacturer.website_urls[0])) if manufacturer and manufacturer.website_urls else ""
        ),
        "security_contact_email": _sanitize(security_contact.email) if security_contact else "",
        "security_contact_url": _sanitize(assessment.security_contact_url),
        "vdp_url": _sanitize(assessment.vdp_url),
        "csirt_contact_email": _sanitize(assessment.csirt_contact_email),
        "csirt_country": _sanitize(assessment.csirt_country)[:2].upper(),
        "acknowledgment_timeline_days": assessment.acknowledgment_timeline_days,
        "date": date.today().isoformat(),
        "version": "1.0",
        "assessment_id": assessment.id,
    }


def _build_risk_assessment_context(assessment: CRAAssessment, base: dict[str, Any]) -> dict[str, Any]:
    """Add findings grouped by control group for risk assessment."""
    findings = (
        OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
        .select_related("control")
        .order_by("control__sort_order")
    )

    groups: dict[str, list[dict[str, str]]] = {
        "cra-sd": [],
        "cra-dp": [],
        "cra-av": [],
        "cra-mn": [],
        "cra-vh": [],
    }
    counts = {"satisfied": 0, "not-satisfied": 0, "not-applicable": 0, "unanswered": 0}

    for f in findings:
        gid = f.control.group_id
        if gid in groups:
            groups[gid].append(
                {
                    "title": f.control.title,
                    "status": f.get_status_display(),
                    "notes": _sanitize(f.notes, escape_pipe=True) if f.notes else "",
                }
            )
        counts[f.status] = counts.get(f.status, 0) + 1

    base["sd_findings"] = groups["cra-sd"]
    base["dp_findings"] = groups["cra-dp"]
    base["av_findings"] = groups["cra-av"]
    base["mn_findings"] = groups["cra-mn"]
    base["vh_findings"] = groups["cra-vh"]
    # Use underscored keys so Django template {{ summary.not_satisfied }} resolves correctly
    base["summary"] = {
        "total": sum(counts.values()),
        "satisfied": counts["satisfied"],
        "not_satisfied": counts["not-satisfied"],
        "not_applicable": counts["not-applicable"],
        "unanswered": counts["unanswered"],
    }
    return base


def _build_security_txt_context(assessment: CRAAssessment, base: dict[str, Any]) -> dict[str, Any]:
    """Build context for security.txt template."""
    # Build Preferred-Languages from target markets
    languages: set[str] = set()
    for country in assessment.target_eu_markets:
        for lang in _COUNTRY_LANGUAGE_MAP.get(country.upper(), "").split(","):
            if lang:
                languages.add(lang)
    # Always include English
    languages.add("en")
    base["preferred_languages"] = ", ".join(sorted(languages))

    # Expires: support_period_end + 1 year, or empty
    if assessment.support_period_end:
        end = assessment.support_period_end
        try:
            expires_date = end.replace(year=end.year + 1)
        except ValueError:
            # Feb 29 → Feb 28 in non-leap year
            expires_date = end.replace(year=end.year + 1, day=28)
        base["expires"] = expires_date.strftime("%Y-%m-%dT00:00:00.000Z")
    else:
        base["expires"] = ""

    base["hiring_url"] = ""
    return base


def _build_declaration_context(assessment: CRAAssessment, base: dict[str, Any]) -> dict[str, Any]:
    """Build context for declaration of conformity."""
    base["product_category_display"] = assessment.get_product_category_display()
    base["conformity_procedure_display"] = assessment.get_conformity_assessment_procedure_display()
    base["applied_standards"] = []
    return base


def _build_document_context(assessment: CRAAssessment, kind: str) -> dict[str, Any]:
    """Build the full template context for a document kind."""
    base = _build_common_context(assessment)

    if kind == CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT:
        base["product_category_display"] = assessment.get_product_category_display()
        return _build_risk_assessment_context(assessment, base)

    if kind == CRAGeneratedDocument.DocumentKind.SECURITY_TXT:
        return _build_security_txt_context(assessment, base)

    if kind == CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY:
        return _build_declaration_context(assessment, base)

    if kind == CRAGeneratedDocument.DocumentKind.USER_INSTRUCTIONS:
        base["update_frequency"] = _sanitize(assessment.update_frequency or "")
        base["update_method"] = _sanitize(assessment.update_method or "")
        base["update_channel_url"] = _sanitize(assessment.update_channel_url or "")
        base["support_email"] = _sanitize(assessment.support_email or "")
        base["support_url"] = _sanitize(assessment.support_url or "")
        base["support_phone"] = _sanitize(assessment.support_phone or "")
        base["support_hours"] = _sanitize(assessment.support_hours or "")
        base["data_deletion_instructions"] = _sanitize(assessment.data_deletion_instructions or "")
        return base

    if kind == CRAGeneratedDocument.DocumentKind.DECOMMISSIONING_GUIDE:
        base["data_deletion_instructions"] = _sanitize(assessment.data_deletion_instructions or "")
        return base

    return base


def _render_template(kind: str, context: dict[str, Any]) -> str:
    """Render a Django template by document kind."""
    template_name = _TEMPLATE_MAP.get(kind)
    if not template_name:
        raise ValueError(f"Unknown document kind: {kind}")
    template = _engine.get_template(template_name)
    return template.render(Context(context))


def generate_document(
    assessment: CRAAssessment,
    kind: str,
) -> ServiceResult[CRAGeneratedDocument]:
    """Render a Django template, upload to S3, create/update CRAGeneratedDocument."""
    valid_kinds = {c[0] for c in CRAGeneratedDocument.DocumentKind.choices}
    if kind not in valid_kinds:
        return ServiceResult.failure(f"Unknown document kind: {kind}", status_code=400)

    context = _build_document_context(assessment, kind)
    rendered = _render_template(kind, context)
    content_bytes = rendered.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Storage key
    storage_key = f"compliance/{assessment.id}/{kind}"
    if kind == CRAGeneratedDocument.DocumentKind.SECURITY_TXT:
        storage_key += ".txt"
    else:
        storage_key += ".md"

    # Upload to S3
    try:
        from sbomify.apps.core.object_store import StorageClient

        s3 = StorageClient("DOCUMENTS")
        from django.conf import settings as django_settings

        s3.upload_data_as_file(django_settings.AWS_DOCUMENTS_STORAGE_BUCKET_NAME, storage_key, content_bytes)
    except Exception:
        logger.exception("Failed to upload document %s to S3", kind)
        return ServiceResult.failure("Failed to upload document to storage", status_code=502)

    # Create or update record
    doc, created = CRAGeneratedDocument.objects.get_or_create(
        assessment=assessment,
        document_kind=kind,
        defaults={
            "storage_key": storage_key,
            "content_hash": content_hash,
            "version": 1,
            "is_stale": False,
        },
    )

    if not created:
        doc.version += 1
        doc.storage_key = storage_key
        doc.content_hash = content_hash
        doc.is_stale = False
        doc.save()

    return ServiceResult.success(doc)


def regenerate_all(assessment: CRAAssessment) -> ServiceResult[int]:
    """Regenerate all document kinds. Returns count on full success, failure if any fail."""
    total = len(CRAGeneratedDocument.DocumentKind.choices)
    failed_kinds: list[str] = []
    count = 0
    for kind, _ in CRAGeneratedDocument.DocumentKind.choices:
        result = generate_document(assessment, kind)
        if result.ok:
            count += 1
        else:
            failed_kinds.append(kind)
    if failed_kinds:
        return ServiceResult.failure(
            f"Failed to generate {len(failed_kinds)}/{total} documents: {', '.join(failed_kinds)}",
            status_code=502,
        )
    return ServiceResult.success(count)


def regenerate_stale(assessment: CRAAssessment) -> ServiceResult[int]:
    """Regenerate only stale documents. Returns count."""
    stale_docs = CRAGeneratedDocument.objects.filter(assessment=assessment, is_stale=True)
    count = 0
    for doc in stale_docs:
        result = generate_document(assessment, doc.document_kind)
        if result.ok:
            count += 1
    return ServiceResult.success(count)


def get_document_preview(
    assessment: CRAAssessment,
    kind: str,
) -> ServiceResult[str]:
    """Render to string without persisting — for preview in wizard."""
    valid_kinds = {c[0] for c in CRAGeneratedDocument.DocumentKind.choices}
    if kind not in valid_kinds:
        return ServiceResult.failure(f"Unknown document kind: {kind}", status_code=400)

    context = _build_document_context(assessment, kind)
    rendered = _render_template(kind, context)
    return ServiceResult.success(rendered)
