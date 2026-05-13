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
from sbomify.apps.teams.services.contacts import (
    contact_belongs_to_team,
    get_manufacturer,
    get_security_contact,
    list_workspace_contacts,
)

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

# Cap on the waiver justification text (issue #907). The field lives
# in a JSONField which has no length constraint; an unbounded value
# would bloat the row and could DoS JSON serialisation. 2 KB is
# generous for a one-paragraph audit explanation.
_MAX_WAIVER_JUSTIFICATION_CHARS = 2_000

# Generic caps for Step 1 free-text fields (intended_use,
# support_period_short_justification). ``intended_use`` flows into the
# DoC; ``support_period_short_justification`` is stored-only today but
# is regulated audit evidence per CRA Art 13(8). Same rationale as the
# waiver cap above — the JSONField / TextField surfaces have no server
# cap and would otherwise accept arbitrarily large blobs that bloat
# the row and stall JSON serialisation.
_MAX_STEP_1_TEXT_CHARS = 4_000

# EU member states (ISO 3166-1 alpha-2). Mirrors
# ``sbomify/apps/compliance/js/eu-countries.ts`` — a market code that
# isn't in this set is rejected at save time (CRA Art 24: DoC enumerates
# the member states the product is placed on the market in, so an
# invalid code would land in a regulated artefact).
_EU_COUNTRIES: frozenset[str] = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)


def _auto_fill_from_contacts(assessment: CRAAssessment) -> None:
    """Populate security contact and CSIRT email from existing contact profiles."""
    team = assessment.team

    security_contact = get_security_contact(team)
    if security_contact:
        if not assessment.csirt_contact_email:
            assessment.csirt_contact_email = security_contact.email

    # Find manufacturer entity for VDP/support info
    manufacturer = get_manufacturer(team)
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
    from sbomify.apps.compliance.services._manufacturer_policy import is_placeholder_manufacturer

    product = assessment.product

    manufacturer = get_manufacturer(assessment.team)
    manufacturer_data = None
    if manufacturer:
        manufacturer_data = {
            "name": manufacturer.name,
            "address": manufacturer.address,
            "email": manufacturer.email,
            "website_urls": manufacturer.website_urls,
        }
    # Annex V item 2 — DoC requires the manufacturer's legal name.
    # Surface a boolean the wizard UI can use to render a prevention
    # banner BEFORE the operator discovers "[Manufacturer Name — not
    # configured]" on the generated DoC. This is the wizard-side guard
    # that complements the render-time safety net in
    # document_generation_service._build_common_context.
    manufacturer_name = manufacturer.name if manufacturer else ""
    manufacturer_is_placeholder = is_placeholder_manufacturer(manufacturer_name)

    # Compute the 5-year minimum support-end date server-side so the
    # Alpine "is support period short?" check doesn't drift across time
    # zones. ``new Date()`` is the client-local wall clock; ``today()``
    # is the server-local date — at midnight the two can differ by a
    # day and the UI would require (or skip) a justification the
    # backend disagrees with. Shipping the canonical value removes the
    # whole class of drift.
    reference_date = product.release_date or datetime.date.today()
    new_year = reference_date.year + 5
    try:
        support_period_min_end = reference_date.replace(year=new_year)
    except ValueError:
        last_day = calendar.monthrange(new_year, reference_date.month)[1]
        support_period_min_end = datetime.date(new_year, reference_date.month, last_day)

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
            "manufacturer_is_placeholder": manufacturer_is_placeholder,
            "intended_use": assessment.intended_use,
            "target_eu_markets": assessment.target_eu_markets,
            "support_period_end": assessment.support_period_end.isoformat() if assessment.support_period_end else None,
            "support_period_min_end": support_period_min_end.isoformat(),
            "support_period_short_justification": assessment.support_period_short_justification,
            "product_category": assessment.product_category,
            "is_open_source_steward": assessment.is_open_source_steward,
            "harmonised_standard_applied": assessment.harmonised_standard_applied,
            "conformity_assessment_procedure": assessment.conformity_assessment_procedure,
            "conformity_procedure_options": _CATEGORY_PROCEDURE_OPTIONS,
            # EN 18031 applicability flags (issue #905). Orthogonal to
            # ``product_category``; surface separately so the wizard
            # renders both a CRA risk-tier selector and a RED-scope
            # checklist.
            "is_radio_equipment": assessment.is_radio_equipment,
            "processes_personal_data": assessment.processes_personal_data,
            "handles_financial_value": assessment.handles_financial_value,
        }
    )


def _build_step_2_context(assessment: CRAAssessment) -> ServiceResult[dict[str, Any]]:
    """Step 2: SBOM Compliance (BSI TR-03183-2).

    Overlays the BSI findings with any tooling-limitation waivers
    persisted on the assessment (issue #907). A waived finding is
    flagged on the payload (``waived: true`` plus ``justification``)
    so the template can render it as "accepted" instead of "failing".
    The overall gate also recomputes — a product whose only failing
    checks are all waived passes Step 2.
    """
    result = get_bsi_assessment_status(assessment.product)
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to get BSI status")

    payload: dict[str, Any] = dict(result.value or {})
    # Defensive: ``bsi_waivers`` is a JSONField with no schema guard,
    # so a corrupted row (admin edit, bad migration, hand-rolled
    # SQL) could store a list/string/null where a dict is expected.
    # Normalise to {} so ``.get`` / ``.items`` calls below don't
    # raise and break the whole Step 2 render. The save path
    # (``_save_step_2``) enforces dict shape on ingress; this guard
    # is the ingress's complement on the read side.
    raw_waivers = assessment.bsi_waivers
    waivers: dict[str, Any] = raw_waivers if isinstance(raw_waivers, dict) else {}

    components: list[dict[str, Any]] = payload.get("components") or []
    summary: dict[str, Any] = payload.get("summary") or {}
    any_passing_gate = False
    for component in components:
        bsi = component.get("bsi_assessment")
        if not bsi:
            continue
        failing = bsi.get("failing_checks", [])
        unwaived_fail_count = 0
        for check in failing:
            finding_id = check.get("id", "")
            waiver = waivers.get(finding_id)
            # Per-finding waiver entries should be dicts carrying
            # non-empty ``justification`` / ``waived_at`` values. A
            # malformed or incomplete row (non-dict, missing fields,
            # whitespace-only strings) degrades to "no waiver"
            # rather than crashing on ``.get`` or incorrectly
            # flipping the Annex I Part II(1) gate to green.
            justification = ""
            waived_at = ""
            if isinstance(waiver, dict):
                raw_j = waiver.get("justification", "")
                raw_w = waiver.get("waived_at", "")
                justification = raw_j.strip() if isinstance(raw_j, str) else ""
                waived_at = raw_w.strip() if isinstance(raw_w, str) else ""
            if check.get("remediation_type") == "tooling_limitation" and justification and waived_at:
                # Only tooling-limitation findings can be waived;
                # operator_action waivers are dropped to keep the
                # Annex I Part II(1) guard honest.
                check["waived"] = True
                check["justification"] = justification
                check["waived_at"] = waived_at
            else:
                check["waived"] = False
                unwaived_fail_count += 1
        # Cross-check the waiver-adjusted count against the run's
        # own ``fail_count`` summary. If the run reports failures
        # that didn't materialise as ``failing_checks`` entries
        # (e.g. a truncated payload where ``findings`` was dropped
        # but ``summary`` survived), trust the higher number so an
        # unwaivable failure can't silently bypass the Annex I
        # Part II(1) gate. The overlay adjustments below still
        # apply — any trusted unwaived failure keeps
        # ``effectively_passing`` false.
        summary_fail_count = bsi.get("fail_count")
        if isinstance(summary_fail_count, int) and summary_fail_count > unwaived_fail_count:
            unwaived_fail_count = summary_fail_count
        bsi["unwaived_fail_count"] = unwaived_fail_count
        # Component now "effectively passing" if every failing check
        # is waived AND the scan itself completed + the format is
        # compliant (those are separate gates upstream).
        if unwaived_fail_count == 0 and component.get("format_compliant") and bsi.get("status") == "completed":
            component["effectively_passing"] = True
            any_passing_gate = True
        else:
            component["effectively_passing"] = False

    # Recompute the gate with waivers applied. Match the existential
    # semantics of ``check_sbom_gate()`` / ``get_bsi_assessment_status``
    # — the product-level gate passes when at least one component
    # effectively passes. Requiring every component to be unwaived-
    # clean would be stricter than the underlying SBOM gate and
    # block wizard progression for products that have one good
    # component and one unresolved-but-unwaivable tail.
    summary["overall_gate"] = any_passing_gate
    summary["has_waivers"] = bool(waivers)
    payload["summary"] = summary
    return ServiceResult.success(payload)


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

    contacts = list_workspace_contacts(assessment.product.team)

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

    # Export status — includes the full manifest of the last exported
    # bundle so the Step 5 UI can show what was actually packaged
    # (files, CRA references, per-file hashes) without re-downloading
    # the ZIP. The ``integrity`` block surfaces the hash algorithm and
    # the verification-doc paths so the operator can cross-check the
    # bundle without reading our code.
    last_export = assessment.export_packages.order_by("-created_at").first()
    export_data = None
    if last_export:
        manifest = last_export.manifest or {}
        export_data = {
            "id": last_export.id,
            "content_hash": last_export.content_hash,
            "created_at": last_export.created_at.isoformat(),
            "format_version": manifest.get("format_version"),
            "manufacturer_is_placeholder": bool((manifest.get("manufacturer") or {}).get("is_placeholder", False)),
            "integrity": manifest.get("integrity"),
            "files": [
                {
                    "path": f.get("path", "").split("/", 1)[-1] if "/" in f.get("path", "") else f.get("path", ""),
                    "sha256": f.get("sha256", ""),
                    "cra_reference": f.get("cra_reference", ""),
                }
                for f in manifest.get("files", [])
            ],
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
_STEP_1_BOOL_FIELDS = (
    "is_open_source_steward",
    "is_radio_equipment",
    "processes_personal_data",
    "handles_financial_value",
)
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


_AUDITED_STEP_FIELDS: dict[int, tuple[str, ...]] = {
    1: (
        "product_category",
        "conformity_assessment_procedure",
        "harmonised_standard_applied",
        "support_period_end",
        "support_period_short_justification",
        "target_eu_markets",
        "is_radio_equipment",
        "is_open_source_steward",
        "intended_use",
    ),
    2: ("bsi_waivers",),
    3: ("vdp_url", "security_contact_url", "csirt_contact_email"),
    4: ("update_frequency", "update_method", "support_email"),
    5: (),
}


def _audit_snapshot(assessment: CRAAssessment, step: int) -> dict[str, Any]:
    """Capture the audited fields for a step as a dict for diffing."""
    return {field: getattr(assessment, field, None) for field in _AUDITED_STEP_FIELDS.get(step, ())}


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

    before = _audit_snapshot(assessment, step)
    result = savers[step](assessment, data, user)
    if result.ok and result.value is not None:
        from sbomify.apps.compliance.audit import log_step_save

        log_step_save(
            user=user,
            assessment_id=str(result.value.pk),
            team_id=result.value.team_id,
            step=step,
            before=before,
            after=_audit_snapshot(result.value, step),
        )
    return result


def _save_step_1(
    assessment: CRAAssessment,
    data: dict[str, Any],
    user: User,
) -> ServiceResult[CRAAssessment]:
    """Save Step 1: Product Profile & Classification."""
    # Validate product_category if provided. Require a string — a
    # non-hashable type (``list`` / ``dict``) would otherwise crash the
    # ``x not in set`` check with ``TypeError: unhashable type`` and
    # surface as a 500 instead of a controlled 400.
    if "product_category" in data:
        category_raw = data["product_category"]
        if not isinstance(category_raw, str):
            return ServiceResult.failure("product_category must be a string", status_code=400)
        valid_categories = {c[0] for c in CRAAssessment.ProductCategory.choices}
        if category_raw not in valid_categories:
            return ServiceResult.failure(
                f"Invalid product_category. Must be one of: {sorted(valid_categories)}", status_code=400
            )

    # Apply simple text/char fields. Reject non-string inputs with a 400
    # before the cap is evaluated — ``setattr`` + ``assessment.save()``
    # would later coerce a ``list`` / ``dict`` to its ``repr`` (which
    # bypasses the length cap's ``isinstance`` branch and can still
    # bloat the row / stall JSON serialisation on later reads) or
    # raise a DB-adapter error that surfaces as a 500.
    for field in (*_STEP_1_TEXT_FIELDS, *_STEP_1_CHAR_FIELDS):
        if field in data:
            raw = data[field]
            if raw is None:
                setattr(assessment, field, "")
                continue
            if not isinstance(raw, str):
                return ServiceResult.failure(f"{field} must be a string", status_code=400)
            if len(raw) > _MAX_STEP_1_TEXT_CHARS:
                return ServiceResult.failure(
                    f"{field} exceeds the {_MAX_STEP_1_TEXT_CHARS}-character cap",
                    status_code=400,
                )
            setattr(assessment, field, raw)

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
            if not isinstance(markets, list) or not all(isinstance(m, str) for m in markets):
                return ServiceResult.failure("target_eu_markets must be a list of strings", status_code=400)
            invalid = [m for m in markets if m not in _EU_COUNTRIES]
            if invalid:
                return ServiceResult.failure(
                    f"Invalid EU country code(s): {invalid}. Must be an EU member-state ISO 3166-1 alpha-2 code.",
                    status_code=400,
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

    # Harmonised-standard flag (CRA Art 32(2)). Treat an absent key as
    # "unchanged" — the normal PATCH semantic — so a partial save that
    # edits ``intended_use`` doesn't silently clear an earlier operator
    # affirmation. The Art 32(2) gate below reads the post-payload
    # state; a re-tick is only required when the operator explicitly
    # sends ``False`` or transitions category/procedure into the
    # gated combination (Class I + Module A) without the stored flag
    # being ``True``.
    if "harmonised_standard_applied" in data:
        val = data["harmonised_standard_applied"]
        if isinstance(val, bool):
            assessment.harmonised_standard_applied = val
        elif isinstance(val, str):
            assessment.harmonised_standard_applied = val.lower() in ("true", "1", "yes")
        elif isinstance(val, int):
            assessment.harmonised_standard_applied = bool(val)
        else:
            return ServiceResult.failure(
                "harmonised_standard_applied must be a boolean, string, or integer",
                status_code=400,
            )

    # Apply support_period_short_justification from payload BEFORE the
    # 5-year gate reads it (CRA Art 13(8)). Previously the gate read the
    # stored value, then the assignment happened after — a payload
    # sending ``""`` would clear the justification while still passing
    # the gate via the stored non-empty value.
    #
    # Type validation matches the other Step 1 free-text fields
    # (``_STEP_1_TEXT_FIELDS`` above): ``None`` clears the value; any
    # other non-string payload returns 400 so clients see a schema
    # error rather than silently losing their typed justification.
    if "support_period_short_justification" in data:
        raw = data["support_period_short_justification"]
        if raw is None:
            assessment.support_period_short_justification = ""
        elif not isinstance(raw, str):
            return ServiceResult.failure(
                "support_period_short_justification must be a string",
                status_code=400,
            )
        elif len(raw) > _MAX_STEP_1_TEXT_CHARS:
            return ServiceResult.failure(
                f"support_period_short_justification exceeds the {_MAX_STEP_1_TEXT_CHARS}-character cap",
                status_code=400,
            )
        else:
            assessment.support_period_short_justification = raw

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
        if assessment.support_period_end < min_end and not assessment.support_period_short_justification.strip():
            return ServiceResult.failure(
                "Support period is less than 5 years. CRA Art 13(8) requires at least 5 years "
                "unless the product's expected use time is shorter. Please provide a justification.",
                status_code=400,
            )

    # EN 18031-2 and -3 are RED harmonised standards — they are not
    # standalone privacy / fraud standards. A product that doesn't fall
    # under the RED can't claim presumption of conformity against them,
    # so ``processes_personal_data`` and ``handles_financial_value``
    # are meaningless when ``is_radio_equipment=False``. The client
    # disables those checkboxes in that state; mirror the constraint
    # on the server so a non-browser client (SDK / curl) can't persist
    # a nonsensical "privacy scope without RED scope" combination that
    # would show up on the Step 1 page but produce no DoC effect.
    if not assessment.is_radio_equipment:
        assessment.processes_personal_data = False
        assessment.handles_financial_value = False

    # Server-side mirror of the wizard's canContinue gate. The client
    # already refuses to call this endpoint when the manufacturer is a
    # placeholder, but the SDK / curl / a misbehaving client could hit
    # it directly. Reject with 400 + Annex V item 2 message so the
    # same guard applies from both surfaces (issue #908 follow-up).
    from sbomify.apps.compliance.services._manufacturer_policy import is_placeholder_manufacturer

    manufacturer = get_manufacturer(assessment.team)
    manufacturer_name = manufacturer.name if manufacturer else ""
    if is_placeholder_manufacturer(manufacturer_name):
        return ServiceResult.failure(
            "Annex V item 2 requires a legal manufacturer name. "
            "Configure a real manufacturer entity in team settings before advancing Step 1.",
            status_code=400,
        )

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
            "is_radio_equipment",
            "processes_personal_data",
            "handles_financial_value",
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
    """Save Step 2: SBOM Compliance.

    Accepts an optional ``waivers`` payload: a dict mapping BSI
    finding id to ``{"justification": str}``. Every entry is stamped
    with ``waived_at`` (ISO-8601) and ``waived_by`` (user id) before
    persisting — the wizard / DoC renderers show these as
    attribution. Empty justification rejects the waiver; an
    auditable waiver needs a reason text so Annex VII technical
    documentation can show why a tooling gap was accepted.

    Only known BSI finding ids (``bsi-tr03183:*``) are accepted to
    stop typos from silently poisoning the ``bsi_waivers`` map.
    Submitted finding ids that fail the whitelist return 400 —
    waiver management is belt-and-braces, not best-effort.
    """
    import datetime

    from sbomify.apps.compliance.services.sbom_compliance_service import (
        is_known_bsi_finding,
        is_waivable_bsi_finding,
    )

    update_fields = ["status", "current_step", "completed_steps", "updated_at"]

    if "waivers" in data:
        # Don't collapse every falsy value into ``{}``. ``[]`` / ``0``
        # / ``""`` / ``False`` would otherwise silently clear every
        # existing waiver instead of reporting a 400. Only the two
        # cases below are "no waivers provided": the key is absent
        # (handled by the outer ``if "waivers" in data``) or the
        # value is explicitly None. Every other non-dict type must
        # return 400 so the API contract stays strict.
        raw = data.get("waivers")
        if raw is None:
            raw = {}
        elif not isinstance(raw, dict):
            return ServiceResult.failure("waivers must be an object", status_code=400)

        waivers: dict[str, dict[str, Any]] = {}
        now_iso = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        for finding_id, entry in raw.items():
            if not is_known_bsi_finding(finding_id):
                return ServiceResult.failure(f"Unknown BSI finding id: {finding_id!r}", status_code=400)
            if not is_waivable_bsi_finding(finding_id):
                return ServiceResult.failure(
                    f"{finding_id!r} is an operator-action finding and cannot be waived",
                    status_code=400,
                )
            justification = ""
            if isinstance(entry, dict):
                # Require justification to be a string literal. Nested
                # dicts / lists coerce via str() to their repr, which
                # is truthy and would paper over malformed payloads.
                raw_justification = entry.get("justification")
                if isinstance(raw_justification, str):
                    justification = raw_justification.strip()
            if not justification:
                return ServiceResult.failure(
                    f"Waiver for {finding_id!r} requires a justification",
                    status_code=400,
                )
            # Defense-in-depth: the JSONField has no size cap, so an
            # unbounded justification would bloat the row and could
            # DoS the JSON round-trip. 2 KB is plenty for an audit
            # sentence; anything larger is almost certainly a bug or
            # attack. Enforce the limit here so oversized payloads
            # are rejected consistently — waiver authoring currently
            # happens via the API (Django admin or scripted setup),
            # so the server must not rely on a client-side cap.
            if len(justification) > _MAX_WAIVER_JUSTIFICATION_CHARS:
                return ServiceResult.failure(
                    f"Waiver justification for {finding_id!r} exceeds {_MAX_WAIVER_JUSTIFICATION_CHARS}-char limit",
                    status_code=400,
                )
            waivers[finding_id] = {
                "justification": justification,
                "waived_at": now_iso,
                "waived_by": user.id if user else None,
            }
        assessment.bsi_waivers = waivers
        update_fields.append("bsi_waivers")

    _mark_step_complete(assessment, 2)
    assessment.save(update_fields=update_fields)
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
            # Eager-load ``assessment_result__cra_assessment`` because
            # ``update_finding`` now reads the CRAAssessment PK for the
            # audit log — without this join a Step 3 payload with N
            # finding updates would fire 2×N extra queries.
            finding = OSCALFinding.objects.select_related(
                "control",
                "assessment_result__cra_assessment",
            ).get(
                pk=finding_id,
                assessment_result=assessment.oscal_assessment_result,
            )
            try:
                update_finding(
                    finding,
                    fd.get("status", finding.status),
                    fd.get("notes", finding.notes),
                    fd.get("justification", finding.justification),
                    actor=user,
                )
            except ValueError as e:
                return ServiceResult.failure(str(e), status_code=400)

        # Update vulnerability handling fields. Reject wrong-type
        # inputs with a controlled 400 — Step 1 already behaves this
        # way, and a silent ``continue`` here lets an SDK client lose
        # writes without any signal.
        vh = data.get("vulnerability_handling", {})
        if not isinstance(vh, dict):
            return ServiceResult.failure("vulnerability_handling must be an object", status_code=400)
        for field in _STEP_3_VH_FIELDS:
            if field in vh:
                val = vh[field]
                if field == "acknowledgment_timeline_days":
                    if val is not None and not isinstance(val, int):
                        return ServiceResult.failure(f"{field} must be an integer or null", status_code=400)
                elif val is None:
                    val = ""
                elif not isinstance(val, str):
                    return ServiceResult.failure(f"{field} must be a string", status_code=400)
                setattr(assessment, field, val)

        # Update Article 14 fields
        art14 = data.get("article_14", {})
        if not isinstance(art14, dict):
            return ServiceResult.failure("article_14 must be an object", status_code=400)
        for field in _STEP_3_ART14_FIELDS:
            if field in art14:
                val = art14[field]
                if field == "enisa_srp_registered":
                    setattr(assessment, field, bool(val))
                elif val is None:
                    setattr(assessment, field, "")
                elif not isinstance(val, str):
                    return ServiceResult.failure(f"{field} must be a string", status_code=400)
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
    if contact_id and not contact_belongs_to_team(contact_id, assessment.product.team):
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


_SCOPE_TEXT_CAP = 4_000
_SCOPE_NAME_CAP = 255


def _parse_scope_bool(val: object, default: bool = False) -> bool:
    """Normalise scope-screening boolean payloads into Python ``bool``.

    Accepts the shapes clients actually send: a JSON ``bool``; a
    string spelled ``"true"``/``"1"``/``"yes"`` (case-insensitive)
    for the truthy side, anything else for the falsy side; an
    integer treated as truthy/falsy via ``bool(val)``. Anything else
    falls back to ``default`` so a malformed-but-non-destructive
    payload does not silently flip a persisted flag.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    if isinstance(val, int):
        return bool(val)
    return default


def _cra_applies(
    has_data_connection: bool,
    is_own_use_only: bool,
    is_covered_by_other_legislation: bool,
) -> bool:
    """Delegate to ``CRAScopeScreening.cra_applies`` to keep one authoritative impl.

    The wizard flow needs to evaluate applicability over the **before**
    snapshot (a dict pulled from the DB row before mutation), where there
    is no model instance available. Construct an unsaved
    ``CRAScopeScreening`` with the three triggering fields and let the
    model's own property answer — that way the semantics never drift if
    the property is later refined (e.g., for testing-version edge cases).
    """
    from sbomify.apps.compliance.models import CRAScopeScreening

    probe = CRAScopeScreening(
        has_data_connection=has_data_connection,
        is_own_use_only=is_own_use_only,
        is_covered_by_other_legislation=is_covered_by_other_legislation,
    )
    return probe.cra_applies


def _status_from_completed_steps(completed_steps: list[int]) -> str:
    """Derive the would-be wizard status from the step-completion list.

    Used by ``save_scope_screening`` to pick the "back to last good
    state" status when a stale assessment becomes valid again because
    the operator flipped CRA scope applicability back on. ``STALE``
    itself overwrites the previous status so the only way to restore
    it without adding another column is to look at what the operator
    has actually finished.
    """
    from sbomify.apps.compliance.models import CRAAssessment

    if not completed_steps:
        return CRAAssessment.WizardStatus.DRAFT
    if set(completed_steps) >= {1, 2, 3, 4, 5}:
        return CRAAssessment.WizardStatus.COMPLETE
    return CRAAssessment.WizardStatus.IN_PROGRESS


def save_scope_screening(
    product: Any,
    user: User,
    data: dict[str, Any],
) -> ServiceResult[Any]:
    """Persist a ``CRAScopeScreening`` from validated JSON data.

    Central service-layer gate for the scope-determination write path.
    Returns ``ServiceResult`` so the view and any future Ninja/SDK
    endpoint share the same length caps, coercion rules, and audit
    emission — without those rules duplicated and drifting across
    surfaces.

    Scope-flip → assessment stale (issue #921). When this write changes
    ``CRAScopeScreening.cra_applies`` from ``True`` to ``False`` and a
    live ``CRAAssessment`` exists for the product, the assessment is
    flipped to ``WizardStatus.STALE``. The assessment row survives
    (ADR-004 — we never destroy evidence) but every mutation endpoint
    refuses edits with 409 until the operator either re-scopes CRA
    back on (which auto-unstales) or explicitly deletes the assessment
    via a separate delete path.
    """
    from django.db import IntegrityError, transaction

    from sbomify.apps.compliance.audit import log_assessment_stale_transition, log_scope_screening_change
    from sbomify.apps.compliance.models import CRAAssessment, CRAScopeScreening

    # Length caps (CWE-400). Check the ``str(...)`` coerced form so a
    # caller passing ``list``/``dict`` can't bypass the string-only
    # ``isinstance`` branch and still bloat the row.
    notes_coerced = str(data.get("screening_notes") or "")
    if len(notes_coerced) > _SCOPE_TEXT_CAP:
        return ServiceResult.failure("screening_notes exceeds 4000-char cap", status_code=400)
    name_coerced = str(data.get("exempted_legislation_name") or "")
    if len(name_coerced) > _SCOPE_NAME_CAP:
        return ServiceResult.failure("exempted_legislation_name exceeds 255-char cap", status_code=400)

    # Capture before-state so the audit log diff reflects only actual
    # deltas. ``screening_exists`` drives the create vs update log.
    try:
        existing = CRAScopeScreening.objects.get(product=product)
        before = {
            "has_data_connection": existing.has_data_connection,
            "is_own_use_only": existing.is_own_use_only,
            "is_testing_version": existing.is_testing_version,
            "is_covered_by_other_legislation": existing.is_covered_by_other_legislation,
            "exempted_legislation_name": existing.exempted_legislation_name,
            "is_dual_use": existing.is_dual_use,
            "screening_notes": existing.screening_notes,
        }
    except CRAScopeScreening.DoesNotExist:
        before = {}

    applies_before = bool(before) and _cra_applies(
        bool(before.get("has_data_connection", True)),
        bool(before.get("is_own_use_only", False)),
        bool(before.get("is_covered_by_other_legislation", False)),
    )

    def _apply_field_writes(target: CRAScopeScreening) -> None:
        target.has_data_connection = _parse_scope_bool(data.get("has_data_connection"), default=True)
        target.is_own_use_only = _parse_scope_bool(data.get("is_own_use_only"))
        target.is_testing_version = _parse_scope_bool(data.get("is_testing_version"))
        target.is_covered_by_other_legislation = _parse_scope_bool(data.get("is_covered_by_other_legislation"))
        target.exempted_legislation_name = str(data.get("exempted_legislation_name") or "").strip()
        target.is_dual_use = _parse_scope_bool(data.get("is_dual_use"))
        target.screening_notes = str(data.get("screening_notes") or "").strip()

    def _apply_stale_transition() -> tuple[CRAAssessment, str, str, str] | None:
        """Lock the assessment row and apply the stale flip if needed.

        Must be called inside the same ``transaction.atomic()`` block as
        the screening write so the screening edit and the stale-flip
        either both commit or both roll back. ``select_for_update``
        serialises against concurrent step writes that read ``status``
        before mutating, preventing TOCTOU windows where a concurrent
        step save could complete against an "about to be stale" row.
        """
        try:
            assessment = CRAAssessment.objects.select_for_update().get(product=product)
        except CRAAssessment.DoesNotExist:
            return None
        applies_after = bool(screening.cra_applies)
        if applies_before and not applies_after and assessment.status != CRAAssessment.WizardStatus.STALE:
            prior_status = assessment.status
            assessment.status = CRAAssessment.WizardStatus.STALE
            assessment.save(update_fields=["status", "updated_at"])
            return (assessment, prior_status, CRAAssessment.WizardStatus.STALE, "scope_flipped_out")
        if (not applies_before) and applies_after and assessment.status == CRAAssessment.WizardStatus.STALE:
            restored = _status_from_completed_steps(assessment.completed_steps or [])
            assessment.status = restored
            assessment.save(update_fields=["status", "updated_at"])
            return (assessment, CRAAssessment.WizardStatus.STALE, restored, "scope_flipped_in")
        return None

    # ``OneToOneField`` uniqueness race — wrap the get_or_create AND
    # the field writes AND the assessment stale-flip in the same atomic
    # block. The screening edit and the linked-assessment status change
    # are a single regulated transition (ADR-004): either both commit
    # or both roll back. Without this, an exception during the
    # assessment update could leave a contradictory regulated state
    # (screening out-of-scope while assessment still mutable).
    transition: tuple[CRAAssessment, str, str, str] | None = None
    try:
        with transaction.atomic():
            screening, _created = CRAScopeScreening.objects.select_for_update().get_or_create(
                product=product,
                defaults={"team": product.team, "created_by": user},
            )
            _apply_field_writes(screening)
            screening.save()
            transition = _apply_stale_transition()
    except IntegrityError:
        # The OneToOne raced under us — reload under lock and retry the
        # write inside a fresh atomic so the assessment flip is still
        # atomic with the screening write on the retry path. This loses
        # the ``created_by`` marker on the second winner but keeps the
        # data consistent with the losing caller's payload.
        with transaction.atomic():
            screening = CRAScopeScreening.objects.select_for_update().get(product=product)
            _apply_field_writes(screening)
            screening.save()
            transition = _apply_stale_transition()

    after = {
        "has_data_connection": screening.has_data_connection,
        "is_own_use_only": screening.is_own_use_only,
        "is_testing_version": screening.is_testing_version,
        "is_covered_by_other_legislation": screening.is_covered_by_other_legislation,
        "exempted_legislation_name": screening.exempted_legislation_name,
        "is_dual_use": screening.is_dual_use,
        "screening_notes": screening.screening_notes,
    }
    # Audit emissions live outside the atomic so a logging-pipeline hiccup
    # cannot roll back the regulated state — the writes are already durable.
    log_scope_screening_change(
        user=user,
        product_id=str(product.id),
        team_id=product.team_id,
        before=before,
        after=after,
    )
    if transition is not None:
        flipped_assessment, prior_status, after_status, reason = transition
        log_assessment_stale_transition(
            user=user,
            assessment_id=str(flipped_assessment.pk),
            team_id=flipped_assessment.team_id,
            before_status=prior_status,
            after_status=after_status,
            reason=reason,
        )

    return ServiceResult.success(screening)
