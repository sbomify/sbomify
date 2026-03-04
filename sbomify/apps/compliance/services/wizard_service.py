"""CRA Compliance Wizard orchestration service.

Manages the 5-step wizard workflow:
  Step 1 — Product Profile & Classification
  Step 2 — SBOM Compliance (BSI TR-03183-2)
  Step 3 — Security Assessment (controls + vuln handling + Article 14)
  Step 4 — User Information & Document Generation
  Step 5 — Summary & Export
"""

from __future__ import annotations

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

# Category -> default conformity procedure mapping per CRA Annex VIII
_CATEGORY_PROCEDURE_MAP: dict[str, str] = {
    CRAAssessment.ProductCategory.DEFAULT: CRAAssessment.ConformityProcedure.MODULE_A,
    CRAAssessment.ProductCategory.CLASS_I: CRAAssessment.ConformityProcedure.MODULE_A,
    CRAAssessment.ProductCategory.CLASS_II: CRAAssessment.ConformityProcedure.MODULE_B_C,
    CRAAssessment.ProductCategory.CRITICAL: CRAAssessment.ConformityProcedure.EUCC,
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

    # Return existing assessment if one exists
    try:
        existing = CRAAssessment.objects.get(product=product)
        return ServiceResult.success(existing)
    except CRAAssessment.DoesNotExist:
        pass

    # Create new assessment
    catalog = ensure_cra_catalog()
    ar = create_assessment_result(catalog, team, product, user)

    assessment = CRAAssessment(
        team=team,
        product=product,
        oscal_assessment_result=ar,
        created_by=user,
    )

    _auto_fill_from_contacts(assessment)
    _auto_fill_from_product(assessment)
    assessment.save()

    return ServiceResult.success(assessment)


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
            "product_category": assessment.product_category,
            "is_open_source_steward": assessment.is_open_source_steward,
            "conformity_assessment_procedure": assessment.conformity_assessment_procedure,
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

    for finding in findings:
        gid = finding.control.group_id
        if gid not in groups:
            groups[gid] = {
                "group_id": gid,
                "group_title": finding.control.group_title,
                "controls": [],
            }

        # Get annex reference from the OSCAL catalog control props
        annex_ref = ""
        catalog_json = assessment.oscal_assessment_result.catalog.catalog_json
        for group in catalog_json.get("groups", []):
            if group.get("id") == gid:
                for ctrl in group.get("controls", []):
                    if ctrl.get("id") == finding.control.control_id:
                        for prop in ctrl.get("props", []):
                            if prop.get("name") == "annex-ref":
                                annex_ref = prop.get("value", "")
                                break
                        break
                break

        groups[gid]["controls"].append(
            {
                "finding_id": finding.id,
                "control_id": finding.control.control_id,
                "title": finding.control.title,
                "description": finding.control.description,
                "status": finding.status,
                "notes": finding.notes,
                "annex_reference": annex_ref,
            }
        )
        status_counts[finding.status] += 1

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

    return ServiceResult.success(
        {
            "user_info": {
                "update_frequency": assessment.update_frequency,
                "update_method": assessment.update_method,
                "update_channel_url": assessment.update_channel_url,
                "support_email": assessment.support_email,
                "support_url": assessment.support_url,
                "support_phone": assessment.support_phone,
                "support_hours": assessment.support_hours,
                "data_deletion_instructions": assessment.data_deletion_instructions,
            },
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
        status_counts[f.status] += 1

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
        "export_available": overall_ready and docs_stale == 0,
        "last_export": export_data,
    }


# ---- Step 1 fields that can be saved ----
_STEP_1_TEXT_FIELDS = ("intended_use",)
_STEP_1_CHAR_FIELDS = ("product_category", "csirt_country")
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
    import datetime

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
            setattr(assessment, field, bool(data[field]))

    for field in _STEP_1_JSON_FIELDS:
        if field in data:
            setattr(assessment, field, data[field])

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

    # Auto-set conformity procedure based on category
    assessment.conformity_assessment_procedure = _CATEGORY_PROCEDURE_MAP.get(
        assessment.product_category, CRAAssessment.ConformityProcedure.MODULE_A
    )

    _mark_step_complete(assessment, 1)
    assessment.save()
    return ServiceResult.success(assessment)


def _save_step_2(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 2: SBOM Compliance (read-only step, just mark complete)."""
    _mark_step_complete(assessment, 2)
    assessment.save()
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
    # Update findings
    findings_data = data.get("findings", [])
    for fd in findings_data:
        finding_id = fd.get("finding_id")
        if not finding_id:
            continue
        try:
            finding = OSCALFinding.objects.get(
                pk=finding_id,
                assessment_result=assessment.oscal_assessment_result,
            )
        except OSCALFinding.DoesNotExist:
            return ServiceResult.failure(f"Finding {finding_id} not found", status_code=404)

        try:
            update_finding(finding, fd.get("status", finding.status), fd.get("notes", finding.notes))
        except ValueError as e:
            return ServiceResult.failure(str(e), status_code=400)

    # Update vulnerability handling fields
    vh = data.get("vulnerability_handling", {})
    for field in _STEP_3_VH_FIELDS:
        if field in vh:
            setattr(assessment, field, vh[field])

    # Update Article 14 fields
    art14 = data.get("article_14", {})
    for field in _STEP_3_ART14_FIELDS:
        if field in art14:
            setattr(assessment, field, art14[field])

    _mark_step_complete(assessment, 3)
    assessment.save()
    return ServiceResult.success(assessment)


def _save_step_4(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 4: User Information."""
    for field in _STEP_4_FIELDS:
        if field in data:
            setattr(assessment, field, data[field])

    _mark_step_complete(assessment, 4)
    assessment.save()
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

    _mark_step_complete(assessment, 5)
    assessment.status = CRAAssessment.WizardStatus.COMPLETE
    assessment.completed_at = timezone.now()
    assessment.oscal_assessment_result.status = "complete"
    assessment.oscal_assessment_result.completed_at = timezone.now()
    assessment.oscal_assessment_result.save(update_fields=["status", "completed_at"])
    assessment.save()
    return ServiceResult.success(assessment)


def _mark_step_complete(assessment: CRAAssessment, step: int) -> None:
    """Add step to completed_steps if not already present and advance current_step."""
    if step not in assessment.completed_steps:
        assessment.completed_steps = [*assessment.completed_steps, step]
    if assessment.status == CRAAssessment.WizardStatus.DRAFT:
        assessment.status = CRAAssessment.WizardStatus.IN_PROGRESS
    assessment.current_step = max(assessment.current_step, step)


def get_compliance_summary(
    assessment: CRAAssessment,
) -> ServiceResult[dict[str, Any]]:
    """Get the full compliance summary for Step 5 dashboard."""
    return ServiceResult.success(_compute_compliance_summary(assessment))
