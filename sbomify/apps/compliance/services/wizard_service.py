"""CRA Compliance Wizard orchestration service.

Manages the 5-step wizard workflow:
  Step 1 — Product Profile & Classification
  Step 2 — SBOM Compliance (BSI TR-03183-2)
  Step 3 — Security Assessment (controls + vuln handling + Article 14)
  Step 4 — User Information & Document Generation
  Step 5 — Summary & Export
"""

from __future__ import annotations

import calendar
import datetime
from typing import TYPE_CHECKING, Any

from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAGeneratedDocument,
    OSCALFinding,
)
from sbomify.apps.compliance.services.oscal_service import (
    create_assessment_result,
    ensure_cra_catalog,
    update_finding,
)
from sbomify.apps.compliance.services.sbom_compliance_service import (
    get_bsi_assessment_status,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import ContactEntity, ContactProfileContact

if TYPE_CHECKING:
    from sbomify.apps.core.models import User
    from sbomify.apps.teams.models import Team

# Allowed conformity assessment procedures per product category.
# CRA Art 32(1): Default → Module A (self-assessment)
# CRA Art 32(2): Class I → Module A only if harmonised standard applied; otherwise B+C or H
# CRA Art 32(3): Class II → Module B+C or H (no self-assessment)
# CRA Art 32(3): Critical → Module B+C or H (EUCC not yet mandated per Art 8(1))
# CRA Art 32(5): FOSS with public tech docs may use Module A for Class I/II (not modelled separately)
_CATEGORY_PROCEDURE_OPTIONS: dict[str, list[str]] = {
    CRAAssessment.ProductCategory.DEFAULT: [CRAAssessment.ConformityProcedure.MODULE_A],
    CRAAssessment.ProductCategory.CLASS_I: [
        CRAAssessment.ConformityProcedure.MODULE_A,
        CRAAssessment.ConformityProcedure.MODULE_B_C,
        CRAAssessment.ConformityProcedure.MODULE_H,
    ],
    CRAAssessment.ProductCategory.CLASS_II: [
        CRAAssessment.ConformityProcedure.MODULE_B_C,
        CRAAssessment.ConformityProcedure.MODULE_H,
    ],
    CRAAssessment.ProductCategory.CRITICAL: [
        CRAAssessment.ConformityProcedure.MODULE_B_C,
        CRAAssessment.ConformityProcedure.MODULE_H,
    ],
}

# Default procedure per category (used when user hasn't explicitly selected)
_CATEGORY_DEFAULT_PROCEDURE: dict[str, str] = {
    CRAAssessment.ProductCategory.DEFAULT: CRAAssessment.ConformityProcedure.MODULE_A,
    CRAAssessment.ProductCategory.CLASS_I: CRAAssessment.ConformityProcedure.MODULE_A,
    CRAAssessment.ProductCategory.CLASS_II: CRAAssessment.ConformityProcedure.MODULE_B_C,
    CRAAssessment.ProductCategory.CRITICAL: CRAAssessment.ConformityProcedure.MODULE_B_C,
}

WIZARD_STEPS = (1, 2, 3, 4, 5)


def _auto_fill_from_contacts(assessment: CRAAssessment) -> None:
    """Populate security contact and CSIRT email from existing contact profiles."""
    team = assessment.team

    # Find the security contact across all team contact profiles
    security_contact = (
        ContactProfileContact.objects.filter(
            entity__profile__team=team,
            is_security_contact=True,
        )
        .select_related("entity")
        .first()
    )
    if security_contact:
        if not assessment.csirt_contact_email:
            assessment.csirt_contact_email = security_contact.email

    # Find manufacturer entity for VDP/support info
    manufacturer = ContactEntity.objects.filter(
        profile__team=team,
        is_manufacturer=True,
    ).first()
    if manufacturer:
        if not assessment.support_email and manufacturer.email:
            assessment.support_email = manufacturer.email


def _auto_fill_from_product(assessment: CRAAssessment) -> None:
    """Populate support dates from Product lifecycle data."""
    product = assessment.product
    if not assessment.support_period_end and product.end_of_support:
        assessment.support_period_end = product.end_of_support


def get_or_create_assessment(
    product_id: str,
    user: User,
    team: Team,
) -> ServiceResult[CRAAssessment]:
    """Get existing or create new CRA assessment for a product.

    On create:
    1. Ensures the CRA OSCAL catalog is loaded
    2. Creates an OSCAL AssessmentResult with 21 unanswered findings
    3. Creates CRAAssessment linked to the AR
    4. Auto-fills contact and product data where available
    """
    from sbomify.apps.core.models import Product

    try:
        product = Product.objects.get(pk=product_id, team=team)
    except Product.DoesNotExist:
        return ServiceResult.failure("Product not found", status_code=404)

    from django.db import IntegrityError, transaction

    # Return existing assessment if one exists
    try:
        existing = CRAAssessment.objects.get(product=product)
        return ServiceResult.success(existing)
    except CRAAssessment.DoesNotExist:
        pass

    # Create new assessment — wrap in atomic so the AR + findings are
    # rolled back if CRAAssessment.save() hits an IntegrityError.
    try:
        with transaction.atomic():
            catalog = ensure_cra_catalog()
            ar = create_assessment_result(catalog, team, product, user)

            assessment = CRAAssessment(
                team=team,
                product=product,
                oscal_assessment_result=ar,
                created_by=user,
            )

            try:
                _auto_fill_from_contacts(assessment)
            except (AttributeError, TypeError, ValueError):
                import logging

                logging.getLogger(__name__).warning("Auto-fill from contacts failed for product %s", product_id)

            try:
                _auto_fill_from_product(assessment)
            except (AttributeError, TypeError, ValueError):
                import logging

                logging.getLogger(__name__).warning("Auto-fill from product failed for product %s", product_id)

            assessment.save()
    except IntegrityError:
        # Concurrent creation — AR + findings were rolled back by the atomic block
        existing = CRAAssessment.objects.get(product=product)
        return ServiceResult.success(existing)

    return ServiceResult.success(assessment)


def get_assessment_by_id(assessment_id: str) -> ServiceResult[CRAAssessment]:
    """Fetch a CRA assessment by ID with related data."""
    try:
        assessment = CRAAssessment.objects.select_related("team", "product", "oscal_assessment_result__catalog").get(
            pk=assessment_id
        )
        return ServiceResult.success(assessment)
    except CRAAssessment.DoesNotExist:
        return ServiceResult.failure("Assessment not found", status_code=404)


def get_step_context(
    assessment: CRAAssessment,
    step: int,
) -> ServiceResult[dict[str, Any]]:
    """Build context data for a wizard step."""
    if step not in WIZARD_STEPS:
        return ServiceResult.failure(f"Invalid step {step}. Must be 1-5.", status_code=400)

    builders = {
        1: _build_step_1_context,
        2: _build_step_2_context,
        3: _build_step_3_context,
        4: _build_step_4_context,
        5: _build_step_5_context,
    }
    return builders[step](assessment)


def _build_step_1_context(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Step 1: Product Profile & Classification."""
    product = assessment.product

    manufacturer = ContactEntity.objects.filter(
        profile__team=assessment.team,
        is_manufacturer=True,
    ).first()
    manufacturer_data = None
    if manufacturer:
        manufacturer_data = {
            "name": manufacturer.name,
            "address": manufacturer.address,
            "email": manufacturer.email,
            "website_urls": manufacturer.website_urls,
        }

    return ServiceResult.success(
        {
            "product": {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "release_date": product.release_date.isoformat() if product.release_date else None,
                "end_of_support": product.end_of_support.isoformat() if product.end_of_support else None,
                "end_of_life": product.end_of_life.isoformat() if product.end_of_life else None,
            },
            "manufacturer": manufacturer_data,
            "intended_use": assessment.intended_use,
            "target_eu_markets": assessment.target_eu_markets,
            "support_period_end": assessment.support_period_end.isoformat() if assessment.support_period_end else None,
            "support_period_short_justification": assessment.support_period_short_justification,
            "product_category": assessment.product_category,
            "is_open_source_steward": assessment.is_open_source_steward,
            "harmonised_standard_applied": assessment.harmonised_standard_applied,
            "conformity_assessment_procedure": assessment.conformity_assessment_procedure,
            "conformity_procedure_options": _CATEGORY_PROCEDURE_OPTIONS,
        }
    )


def _build_step_2_context(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Step 2: SBOM Compliance (BSI TR-03183-2)."""
    result = get_bsi_assessment_status(assessment.product)
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to get BSI status")
    return ServiceResult.success(result.value)


def _build_step_3_context(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Step 3: Security Assessment (controls, vuln handling, Article 14)."""
    findings = (
        OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
        .select_related("control")
        .order_by("control__sort_order")
    )

    # Group findings by control group
    groups: dict[str, dict[str, Any]] = {}
    status_counts = {"satisfied": 0, "not-satisfied": 0, "not-applicable": 0, "unanswered": 0}

    catalog_json = assessment.oscal_assessment_result.catalog.catalog_json

    from sbomify.apps.compliance.services.oscal_service import get_annex_reference, get_annex_url

    for finding in findings:
        gid = finding.control.group_id
        if gid not in groups:
            groups[gid] = {
                "group_id": gid,
                "group_title": finding.control.group_title,
                "controls": [],
            }

        # Get annex reference from the OSCAL catalog control props
        annex_ref = get_annex_reference(catalog_json, finding.control.control_id)

        groups[gid]["controls"].append(
            {
                "finding_id": finding.id,
                "control_id": finding.control.control_id,
                "title": finding.control.title,
                "description": finding.control.description,
                "status": finding.status,
                "notes": finding.notes,
                "justification": finding.justification,
                "is_mandatory": finding.control.is_mandatory,
                "annex_part": finding.control.annex_part,
                "annex_reference": annex_ref,
                "annex_url": get_annex_url(annex_ref),
            }
        )
        status_counts[finding.status] = status_counts.get(finding.status, 0) + 1

    # Check workspace-level security.txt configuration
    team = assessment.product.team
    security_txt_config = getattr(team, "security_txt_config", None) or {}
    security_txt_enabled = bool(security_txt_config.get("enabled", False))

    return ServiceResult.success(
        {
            "control_groups": list(groups.values()),
            "summary": {
                "total": sum(status_counts.values()),
                **status_counts,
            },
            "vulnerability_handling": {
                "vdp_url": assessment.vdp_url,
                "acknowledgment_timeline_days": assessment.acknowledgment_timeline_days,
                "csirt_contact_email": assessment.csirt_contact_email,
                "security_contact_url": assessment.security_contact_url,
            },
            "article_14": {
                "csirt_country": assessment.csirt_country,
                "enisa_srp_registered": assessment.enisa_srp_registered,
                "incident_response_plan_url": assessment.incident_response_plan_url,
                "incident_response_notes": assessment.incident_response_notes,
            },
            "security_txt_enabled": security_txt_enabled,
        }
    )


def _build_step_4_context(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Step 4: User Information & Documents."""
    docs = CRAGeneratedDocument.objects.filter(assessment=assessment)
    doc_status: dict[str, dict[str, Any]] = {}
    for doc in docs:
        doc_status[doc.document_kind] = {
            "exists": True,
            "version": doc.version,
            "is_stale": doc.is_stale,
            "generated_at": doc.generated_at.isoformat(),
        }

    # Fetch contact profiles for the support contact dropdown
    from sbomify.apps.teams.models import ContactProfileContact

    team = assessment.product.team
    contacts = list(
        ContactProfileContact.objects.filter(
            entity__profile__team=team,
            entity__profile__is_component_private=False,
        )
        .select_related("entity__profile")
        .values("id", "name", "email", "phone", "entity__profile__name")
    )

    return ServiceResult.success(
        {
            "user_info": {
                "update_frequency": assessment.update_frequency,
                "update_method": assessment.update_method,
                "update_channel_url": assessment.update_channel_url,
                "support_contact_id": assessment.support_contact_id,
                "support_email": assessment.support_email,
                "support_url": assessment.support_url,
                "support_phone": assessment.support_phone,
                "support_hours": assessment.support_hours,
                "data_deletion_instructions": assessment.data_deletion_instructions,
            },
            "contacts": contacts,
            "documents": doc_status,
        }
    )


def _build_step_5_context(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Step 5: Summary & Export."""
    summary = _compute_compliance_summary(assessment)
    return ServiceResult.success(summary)


def _compute_compliance_summary(assessment: CRAAssessment) -> dict[str, Any]:
    """Compute the full compliance summary for the assessment."""
    # Control assessment counts
    findings = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
    status_counts = {"satisfied": 0, "not-satisfied": 0, "not-applicable": 0, "unanswered": 0}
    for f in findings:
        status_counts[f.status] = status_counts.get(f.status, 0) + 1

    # Document status
    docs = CRAGeneratedDocument.objects.filter(assessment=assessment)
    docs_generated = docs.count()
    docs_stale = docs.filter(is_stale=True).count()

    # Export status
    last_export = assessment.export_packages.order_by("-created_at").first()
    export_data = None
    if last_export:
        export_data = {
            "id": last_export.id,
            "content_hash": last_export.content_hash,
            "created_at": last_export.created_at.isoformat(),
        }

    steps = {
        1: {"complete": 1 in assessment.completed_steps},
        2: {"complete": 2 in assessment.completed_steps},
        3: {
            "complete": 3 in assessment.completed_steps,
            "controls": {
                "total": sum(status_counts.values()),
                **status_counts,
            },
        },
        4: {
            "complete": 4 in assessment.completed_steps,
            "documents_generated": docs_generated,
            "documents_stale": docs_stale,
        },
        5: {"complete": 5 in assessment.completed_steps},
    }

    # Overall ready: steps 1-4 complete, no unanswered controls
    required_steps_done = all(s in assessment.completed_steps for s in [1, 2, 3, 4])
    overall_ready = required_steps_done and status_counts["unanswered"] == 0

    return {
        "product": {
            "name": assessment.product.name,
            "category": assessment.product_category,
            "conformity_procedure": assessment.conformity_assessment_procedure,
        },
        "is_open_source_steward": assessment.is_open_source_steward,
        "steps": steps,
        "overall_ready": overall_ready,
        "export_available": (
            overall_ready and docs_generated == len(CRAGeneratedDocument.DocumentKind.choices) and docs_stale == 0
        ),
        "last_export": export_data,
    }


# ---- Step 1 fields that can be saved ----
_STEP_1_TEXT_FIELDS = ("intended_use",)
_STEP_1_CHAR_FIELDS = ("product_category",)
_STEP_1_BOOL_FIELDS = ("is_open_source_steward",)
_STEP_1_DATE_FIELDS = ("support_period_end",)
_STEP_1_JSON_FIELDS = ("target_eu_markets",)

# ---- Step 3b/3c fields ----
_STEP_3_VH_FIELDS = ("vdp_url", "acknowledgment_timeline_days", "csirt_contact_email", "security_contact_url")
_STEP_3_ART14_FIELDS = (
    "csirt_country",
    "enisa_srp_registered",
    "incident_response_plan_url",
    "incident_response_notes",
)

# ---- Step 4 fields ----
_STEP_4_FIELDS = (
    "update_frequency",
    "update_method",
    "update_channel_url",
    "support_contact_id",
    "support_email",
    "support_url",
    "support_phone",
    "support_hours",
    "data_deletion_instructions",
)


def save_step_data(
    assessment: CRAAssessment,
    step: int,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Validate and persist step data."""
    if step not in WIZARD_STEPS:
        return ServiceResult.failure(f"Invalid step {step}. Must be 1-5.", status_code=400)

    savers = {
        1: _save_step_1,
        2: _save_step_2,
        3: _save_step_3,
        4: _save_step_4,
        5: _save_step_5,
    }
    return savers[step](assessment, data, user)


def _save_step_1(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 1: Product Profile & Classification."""
    # Validate product_category if provided
    if "product_category" in data:
        valid_categories = {c[0] for c in CRAAssessment.ProductCategory.choices}
        if data["product_category"] not in valid_categories:
            return ServiceResult.failure(
                f"Invalid product_category. Must be one of: {sorted(valid_categories)}", status_code=400
            )

    # Apply simple text/char fields
    for field in (*_STEP_1_TEXT_FIELDS, *_STEP_1_CHAR_FIELDS):
        if field in data:
            setattr(assessment, field, data[field])

    for field in _STEP_1_BOOL_FIELDS:
        if field in data:
            val = data[field]
            if isinstance(val, bool):
                setattr(assessment, field, val)
            elif isinstance(val, str):
                setattr(assessment, field, val.lower() in ("true", "1", "yes"))
            elif isinstance(val, int):
                setattr(assessment, field, bool(val))

    if "target_eu_markets" in data:
        markets = data["target_eu_markets"]
        if markets is not None:
            if not isinstance(markets, list) or not all(isinstance(m, str) and len(m) == 2 for m in markets):
                return ServiceResult.failure(
                    "target_eu_markets must be a list of 2-letter country codes", status_code=400
                )
        assessment.target_eu_markets = markets or []

    if "support_period_end" in data:
        val = data["support_period_end"]
        if val is None:
            assessment.support_period_end = None
        elif isinstance(val, str):
            try:
                assessment.support_period_end = datetime.date.fromisoformat(val)
            except ValueError:
                return ServiceResult.failure("Invalid date format for support_period_end", status_code=400)
        elif isinstance(val, datetime.date):
            assessment.support_period_end = val
        else:
            return ServiceResult.failure("Invalid type for support_period_end", status_code=400)

    # Handle harmonised_standard_applied (CRA Art 32(2))
    if "harmonised_standard_applied" in data:
        val = data["harmonised_standard_applied"]
        if isinstance(val, bool):
            assessment.harmonised_standard_applied = val
        elif isinstance(val, str):
            assessment.harmonised_standard_applied = val.lower() in ("true", "1", "yes")
        elif isinstance(val, int):
            assessment.harmonised_standard_applied = bool(val)

    # Handle conformity procedure selection (CRA Art 32(1-5))
    allowed = _CATEGORY_PROCEDURE_OPTIONS.get(assessment.product_category, [])
    if "conformity_assessment_procedure" in data:
        chosen = data["conformity_assessment_procedure"]
        if chosen not in allowed:
            return ServiceResult.failure(
                f"Procedure '{chosen}' is not allowed for category '{assessment.product_category}'. "
                f"Allowed: {allowed} (CRA Art 32)",
                status_code=400,
            )
    else:
        chosen = _CATEGORY_DEFAULT_PROCEDURE.get(
            assessment.product_category, CRAAssessment.ConformityProcedure.MODULE_A
        )

    # Class I + Module A requires harmonised standard (CRA Art 32(2))
    if (
        assessment.product_category == CRAAssessment.ProductCategory.CLASS_I
        and chosen == CRAAssessment.ConformityProcedure.MODULE_A
        and not assessment.harmonised_standard_applied
    ):
        return ServiceResult.failure(
            "Class I products may only use Module A when a harmonised standard has been applied "
            "(CRA Art 32(2)). Either select a different procedure or confirm harmonised standard.",
            status_code=400,
        )
    assessment.conformity_assessment_procedure = chosen

    # Validate support period minimum of 5 years (CRA Art 13(8), FAQ 4.5.2)
    if assessment.support_period_end:
        reference_date = assessment.product.release_date or datetime.date.today()
        new_year = reference_date.year + 5
        try:
            min_end = reference_date.replace(year=new_year)
        except ValueError:
            # Handle leap-day reference dates (e.g., Feb 29) for non-leap target years
            last_day = calendar.monthrange(new_year, reference_date.month)[1]
            min_end = datetime.date(new_year, reference_date.month, last_day)
        if assessment.support_period_end < min_end:
            justification = data.get("support_period_short_justification")
            if justification is not None and isinstance(justification, str):
                assessment.support_period_short_justification = justification
            if not assessment.support_period_short_justification.strip():
                return ServiceResult.failure(
                    "Support period is less than 5 years. CRA Art 13(8) requires at least 5 years "
                    "unless the product's expected use time is shorter. Please provide a justification.",
                    status_code=400,
                )
    if "support_period_short_justification" in data:
        val = data["support_period_short_justification"]
        if isinstance(val, str):
            assessment.support_period_short_justification = val

    _mark_step_complete(assessment, 1)
    assessment.save(
        update_fields=[
            "product_category",
            "is_open_source_steward",
            "harmonised_standard_applied",
            "conformity_assessment_procedure",
            "intended_use",
            "target_eu_markets",
            "support_period_end",
            "support_period_short_justification",
            "status",
            "current_step",
            "completed_steps",
            "updated_at",
        ]
    )
    return ServiceResult.success(assessment)


def _save_step_2(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 2: SBOM Compliance (read-only step, just mark complete)."""
    _mark_step_complete(assessment, 2)
    assessment.save(update_fields=["status", "current_step", "completed_steps", "updated_at"])
    return ServiceResult.success(assessment)


def _save_step_3(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 3: Security Assessment.

    Expects:
    - findings: list of {finding_id, status, notes}
    - vulnerability_handling: {vdp_url, ...}
    - article_14: {csirt_country, ...}
    """
    from django.db import transaction

    # Validate findings_data
    findings_data = data.get("findings", [])
    if not isinstance(findings_data, list):
        return ServiceResult.failure("findings must be a list", status_code=400)

    # Update findings atomically — pre-validate all IDs before modifying anything
    valid_finding_ids = set(
        OSCALFinding.objects.filter(
            assessment_result=assessment.oscal_assessment_result,
        ).values_list("pk", flat=True)
    )

    valid_statuses = {choice[0] for choice in OSCALFinding.FindingStatus.choices}

    for fd in findings_data:
        if not isinstance(fd, dict):
            return ServiceResult.failure("Each finding must be a dict", status_code=400)
        finding_id = fd.get("finding_id")
        if not finding_id:
            continue
        if finding_id not in valid_finding_ids:
            return ServiceResult.failure(f"Finding {finding_id} not found", status_code=404)
        status = fd.get("status")
        if status and status not in valid_statuses:
            return ServiceResult.failure(
                f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}", status_code=400
            )

    with transaction.atomic():
        for fd in findings_data:
            finding_id = fd.get("finding_id")
            if not finding_id:
                continue
            finding = OSCALFinding.objects.select_related("control").get(
                pk=finding_id,
                assessment_result=assessment.oscal_assessment_result,
            )
            try:
                update_finding(
                    finding,
                    fd.get("status", finding.status),
                    fd.get("notes", finding.notes),
                    fd.get("justification", finding.justification),
                )
            except ValueError as e:
                return ServiceResult.failure(str(e), status_code=400)

        # Update vulnerability handling fields
        vh = data.get("vulnerability_handling", {})
        for field in _STEP_3_VH_FIELDS:
            if field in vh:
                val = vh[field]
                if field == "acknowledgment_timeline_days":
                    if val is not None and not isinstance(val, int):
                        continue
                elif not isinstance(val, str):
                    continue
                setattr(assessment, field, val)

        # Update Article 14 fields
        art14 = data.get("article_14", {})
        for field in _STEP_3_ART14_FIELDS:
            if field in art14:
                val = art14[field]
                if field == "enisa_srp_registered":
                    setattr(assessment, field, bool(val))
                elif not isinstance(val, str):
                    continue
                else:
                    setattr(assessment, field, val)

        # Only mark step 3 complete when all findings are answered
        unanswered = OSCALFinding.objects.filter(
            assessment_result=assessment.oscal_assessment_result,
            status="unanswered",
        ).count()
        if unanswered == 0:
            _mark_step_complete(assessment, 3)

        assessment.save(
            update_fields=[
                "vdp_url",
                "acknowledgment_timeline_days",
                "csirt_contact_email",
                "security_contact_url",
                "csirt_country",
                "enisa_srp_registered",
                "incident_response_plan_url",
                "incident_response_notes",
                "status",
                "current_step",
                "completed_steps",
                "updated_at",
            ]
        )

    return ServiceResult.success(assessment)


def _save_step_4(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 4: User Information."""
    # Validate support_contact_id belongs to the assessment's team
    contact_id = data.get("support_contact_id", "")
    if contact_id:
        from sbomify.apps.teams.models import ContactProfileContact

        if not ContactProfileContact.objects.filter(
            id=contact_id, entity__profile__team=assessment.product.team
        ).exists():
            return ServiceResult.failure("Invalid support contact", status_code=400)

    for field in _STEP_4_FIELDS:
        if field in data:
            val = data[field]
            if not isinstance(val, str):
                continue
            setattr(assessment, field, val)

    _mark_step_complete(assessment, 4)
    assessment.save(
        update_fields=[
            "update_frequency",
            "update_method",
            "update_channel_url",
            "support_contact_id",
            "support_email",
            "support_url",
            "support_phone",
            "support_hours",
            "data_deletion_instructions",
            "status",
            "current_step",
            "completed_steps",
            "updated_at",
        ]
    )
    return ServiceResult.success(assessment)


def _save_step_5(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 5: Mark wizard complete if all steps are done."""
    from django.utils import timezone

    required_complete = all(s in assessment.completed_steps for s in [1, 2, 3, 4])
    if not required_complete:
        return ServiceResult.failure("Steps 1-4 must be completed before finishing.", status_code=400)

    unanswered = OSCALFinding.objects.filter(
        assessment_result=assessment.oscal_assessment_result,
        status="unanswered",
    ).count()
    if unanswered > 0:
        return ServiceResult.failure(
            f"{unanswered} control(s) still unanswered. Answer all controls before finishing.",
            status_code=400,
        )

    _mark_step_complete(assessment, 5)
    assessment.status = CRAAssessment.WizardStatus.COMPLETE
    assessment.completed_at = timezone.now()
    assessment.oscal_assessment_result.status = "complete"
    assessment.oscal_assessment_result.completed_at = timezone.now()
    assessment.oscal_assessment_result.save(update_fields=["status", "completed_at"])
    assessment.save(update_fields=["status", "current_step", "completed_steps", "completed_at", "updated_at"])
    return ServiceResult.success(assessment)


def _mark_step_complete(assessment: CRAAssessment, step: int) -> None:
    """Add step to completed_steps if not already present and advance current_step.

    current_step is set to step + 1 (capped at 5) so the wizard shell
    redirects to the *next* incomplete step, not the one just finished.
    """
    if step not in assessment.completed_steps:
        assessment.completed_steps = [*assessment.completed_steps, step]
    if assessment.status == CRAAssessment.WizardStatus.DRAFT:
        assessment.status = CRAAssessment.WizardStatus.IN_PROGRESS
    next_step = min(step + 1, 5)
    assessment.current_step = max(assessment.current_step, next_step)


def get_compliance_summary(
    assessment: CRAAssessment,
) -> ServiceResult[dict[str, Any]]:
    """Get the full compliance summary for Step 5 dashboard."""
    return ServiceResult.success(_compute_compliance_summary(assessment))


def get_assessment_list_for_team(team_id: int | str) -> ServiceResult[list[dict[str, Any]]]:
    """Get CRA assessments for a team, formatted for the product list view."""
    assessments = CRAAssessment.objects.filter(team_id=team_id).select_related("product").order_by("-updated_at")
    return ServiceResult.success(
        [
            {
                "id": a.id,
                "product_name": a.product.name,
                "product_id": a.product_id,
                "status": a.get_status_display(),
                "status_value": a.status,
                "current_step": a.current_step,
                "completed_steps": a.completed_steps,
                "updated_at": a.updated_at,
            }
            for a in assessments
        ]
    )
