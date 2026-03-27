"""API endpoints for the CRA Compliance Wizard."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import verify_item_access

from .models import CRAAssessment, CRAExportPackage, OSCALFinding, OSCALObservation
from .permissions import check_cra_access
from .schemas import (
    CRAAssessmentSchema,
    DocumentSchema,
    ErrorResponse,
    ExportPackageSchema,
    FindingSchema,
    FindingUpdateSchema,
    ObservationCreateSchema,
    ObservationSchema,
    SBOMStatusSchema,
    StalenessSchema,
    StepContextSchema,
    StepDataSchema,
)

# NOTE: CSRF is disabled app-wide on the NinjaAPI (sbomify/apis.py). Session-auth
# endpoints rely on SameSite cookies + CORS headers for CSRF protection. This matches
# the pattern used by all other routers (core, sboms, teams, plugins, etc.).
router = Router(tags=["Compliance"], auth=(PersonalAccessTokenAuth(), django_auth))

# Django Ninja view return type
_Response = tuple[int, Any]


def _get_assessment_or_error(request: HttpRequest, assessment_id: str) -> CRAAssessment | _Response:
    """Fetch assessment with access checks (billing gate + team role)."""
    try:
        assessment = CRAAssessment.objects.select_related("team", "product", "oscal_assessment_result__catalog").get(
            pk=assessment_id
        )
    except CRAAssessment.DoesNotExist:
        return 404, ErrorResponse(error="Assessment not found", error_code="not_found")

    if not verify_item_access(request, assessment, ["owner", "admin"]):
        return 403, ErrorResponse(error="Forbidden", error_code="permission_denied")

    if not check_cra_access(assessment.team):
        return 403, ErrorResponse(error="CRA Compliance requires Business plan or higher", error_code="billing_gate")

    return assessment


def _assessment_to_schema(a: CRAAssessment) -> CRAAssessmentSchema:
    return CRAAssessmentSchema(
        id=a.id,
        product_id=a.product_id,
        product_name=a.product.name,
        status=a.status,  # type: ignore[arg-type]
        current_step=a.current_step,
        completed_steps=a.completed_steps,
        product_category=a.product_category,
        is_open_source_steward=a.is_open_source_steward,
        conformity_assessment_procedure=a.conformity_assessment_procedure,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _finding_to_schema(f: OSCALFinding) -> FindingSchema:
    from .services.oscal_service import get_annex_reference, get_annex_url

    annex_ref = get_annex_reference(f.assessment_result.catalog.catalog_json, f.control.control_id)

    return FindingSchema(
        id=f.id,
        control_id=f.control.control_id,
        control_title=f.control.title,
        group_id=f.control.group_id,
        group_title=f.control.group_title,
        status=f.status,  # type: ignore[arg-type]
        notes=f.notes,
        annex_reference=annex_ref,
        annex_url=get_annex_url(annex_ref),
        updated_at=f.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/cra/product/{product_id}",
    response={
        200: CRAAssessmentSchema,
        201: CRAAssessmentSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        500: ErrorResponse,
    },
)
def create_or_get_assessment(request: HttpRequest, product_id: str) -> _Response:
    """Create or get a CRA assessment for a product."""
    from sbomify.apps.core.models import Product

    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, ErrorResponse(error="Product not found", error_code="not_found")

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, ErrorResponse(error="Forbidden", error_code="permission_denied")

    if not check_cra_access(product.team):
        return 403, ErrorResponse(error="CRA Compliance requires Business plan or higher", error_code="billing_gate")

    from .services.wizard_service import get_or_create_assessment

    user: User = request.user  # type: ignore[assignment]

    # Check existence before calling the service to determine correct HTTP status
    already_exists = CRAAssessment.objects.filter(product=product).exists()

    result = get_or_create_assessment(product_id, user, product.team)
    if not result.ok:
        return result.status_code or 400, ErrorResponse(error=result.error or "Unknown error")

    assert result.value is not None
    return (200 if already_exists else 201), _assessment_to_schema(result.value)


@router.get(
    "/cra/{assessment_id}",
    response={200: CRAAssessmentSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_assessment(request: HttpRequest, assessment_id: str) -> _Response:
    """Get assessment status."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result
    return 200, _assessment_to_schema(result)


@router.get(
    "/cra/{assessment_id}/step/{step}",
    response={200: StepContextSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def get_step_context(request: HttpRequest, assessment_id: str, step: int) -> _Response:
    """Get context data for a wizard step."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.wizard_service import get_step_context as _get_step_context

    ctx = _get_step_context(result, step)
    if not ctx.ok:
        return ctx.status_code or 400, ErrorResponse(error=ctx.error or "Unknown error")

    assert ctx.value is not None
    is_complete = step in result.completed_steps
    return 200, StepContextSchema(step=step, data=ctx.value, is_complete=is_complete)


@router.patch(
    "/cra/{assessment_id}/step/{step}",
    response={200: CRAAssessmentSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def save_step_data(request: HttpRequest, assessment_id: str, step: int, payload: StepDataSchema) -> _Response:
    """Save data for a wizard step."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.wizard_service import save_step_data as _save_step_data

    user: User = request.user  # type: ignore[assignment]
    save_result = _save_step_data(result, step, payload.data, user)
    if not save_result.ok:
        return save_result.status_code or 400, ErrorResponse(error=save_result.error or "Unknown error")

    assert save_result.value is not None
    return 200, _assessment_to_schema(save_result.value)


@router.get(
    "/cra/{assessment_id}/sbom-status",
    response={200: SBOMStatusSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def get_sbom_status(request: HttpRequest, assessment_id: str) -> _Response:
    """Get SBOM compliance status for all product components."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.sbom_compliance_service import get_bsi_assessment_status

    bsi = get_bsi_assessment_status(result.product)
    if not bsi.ok:
        return 400, ErrorResponse(error=bsi.error or "Unknown error")

    assert bsi.value is not None
    data: dict[str, Any] = bsi.value
    return 200, SBOMStatusSchema(**data)


@router.put(
    "/cra/{assessment_id}/findings/{finding_id}",
    response={200: FindingSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_finding(
    request: HttpRequest, assessment_id: str, finding_id: str, payload: FindingUpdateSchema
) -> _Response:
    """Update a single finding's status and notes."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    try:
        finding = OSCALFinding.objects.select_related("control", "assessment_result__catalog").get(
            pk=finding_id,
            assessment_result=result.oscal_assessment_result,
        )
    except OSCALFinding.DoesNotExist:
        return 404, ErrorResponse(error="Finding not found", error_code="not_found")

    from .services.oscal_service import update_finding as _update_finding

    try:
        updated = _update_finding(finding, payload.status, payload.notes)
    except ValueError as e:
        return 400, ErrorResponse(error=str(e))

    return 200, _finding_to_schema(updated)


@router.post(
    "/cra/{assessment_id}/findings/{finding_id}/observations",
    response={201: ObservationSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_observation(
    request: HttpRequest, assessment_id: str, finding_id: str, payload: ObservationCreateSchema
) -> _Response:
    """Add an observation (evidence) to a finding."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    try:
        finding = OSCALFinding.objects.get(
            pk=finding_id,
            assessment_result=result.oscal_assessment_result,
        )
    except OSCALFinding.DoesNotExist:
        return 404, ErrorResponse(error="Finding not found", error_code="not_found")

    valid_methods = {c[0] for c in OSCALObservation.ObservationMethod.choices}
    if payload.method not in valid_methods:
        return 400, ErrorResponse(error=f"Invalid method. Must be one of: {sorted(valid_methods)}")

    evidence_doc = None
    if payload.evidence_document_id:
        from sbomify.apps.documents.models import Document

        try:
            evidence_doc = Document.objects.get(pk=payload.evidence_document_id, component__team=result.team)
        except Document.DoesNotExist:
            return 404, ErrorResponse(error="Evidence document not found", error_code="not_found")

    obs = OSCALObservation.objects.create(
        finding=finding,
        description=payload.description,
        method=payload.method,
        evidence_document=evidence_doc,
    )

    return 201, ObservationSchema(
        id=obs.id,
        description=obs.description,
        method=obs.method,
        evidence_document_id=evidence_doc.id if evidence_doc else None,
        collected_at=obs.collected_at,
    )


@router.post(
    "/cra/{assessment_id}/generate/{kind}",
    response={200: DocumentSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 502: ErrorResponse},
)
def generate_document(request: HttpRequest, assessment_id: str, kind: str) -> _Response:
    """Generate a compliance document."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.document_generation_service import generate_document as _generate

    gen = _generate(result, kind)
    if not gen.ok:
        return gen.status_code or 400, ErrorResponse(error=gen.error or "Unknown error")

    assert gen.value is not None
    doc = gen.value
    return 200, DocumentSchema(
        id=doc.id,
        document_kind=doc.document_kind,
        version=doc.version,
        is_stale=doc.is_stale,
        content_hash=doc.content_hash,
        generated_at=doc.generated_at,
    )


@router.get(
    "/cra/{assessment_id}/documents/{kind}/preview",
    response={200: dict, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def preview_document(request: HttpRequest, assessment_id: str, kind: str) -> _Response:
    """Preview a document without persisting."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.document_generation_service import get_document_preview

    preview = get_document_preview(result, kind)
    if not preview.ok:
        return preview.status_code or 400, ErrorResponse(error=preview.error or "Unknown error")

    return 200, {"content": preview.value}


@router.post(
    "/cra/{assessment_id}/export",
    response={201: ExportPackageSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 502: ErrorResponse},
)
def create_export(request: HttpRequest, assessment_id: str) -> _Response:
    """Build a ZIP export package."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    # Enforce readiness: all steps 1-4 complete + no unanswered controls
    required_steps_done = all(s in result.completed_steps for s in [1, 2, 3, 4])
    if not required_steps_done:
        return 400, ErrorResponse(error="All wizard steps must be completed before exporting", error_code="not_ready")

    unanswered = OSCALFinding.objects.filter(
        assessment_result=result.oscal_assessment_result,
        status="unanswered",
    ).count()
    if unanswered > 0:
        return 400, ErrorResponse(error=f"{unanswered} control(s) still unanswered", error_code="controls_unanswered")

    # Auto-regenerate missing/stale documents before building the export
    from .services.document_generation_service import regenerate_all

    regen = regenerate_all(result)
    if not regen.ok:
        return regen.status_code or 502, ErrorResponse(error=regen.error or "Document generation failed")

    from .services.export_service import build_export_package

    user: User = request.user  # type: ignore[assignment]
    export = build_export_package(result, user)
    if not export.ok:
        return export.status_code or 400, ErrorResponse(error=export.error or "Unknown error")

    assert export.value is not None
    pkg = export.value
    return 201, ExportPackageSchema(
        id=pkg.id,
        content_hash=pkg.content_hash,
        manifest=pkg.manifest,
        created_at=pkg.created_at,
    )


@router.get(
    "/cra/{assessment_id}/export/{package_id}/download",
    response={200: dict, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
)
def download_export(request: HttpRequest, assessment_id: str, package_id: str) -> _Response:
    """Get a presigned download URL for an export package."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    try:
        package = CRAExportPackage.objects.get(pk=package_id, assessment=result)
    except CRAExportPackage.DoesNotExist:
        return 404, ErrorResponse(error="Export package not found", error_code="not_found")

    from .services.export_service import get_download_url

    url = get_download_url(package)
    if not url.ok:
        return url.status_code or 500, ErrorResponse(error=url.error or "Unknown error")

    return 200, {"download_url": url.value}


@router.get(
    "/cra/{assessment_id}/staleness",
    response={200: StalenessSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def check_staleness(request: HttpRequest, assessment_id: str) -> _Response:
    """Check which documents/steps are stale."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.staleness_service import check_staleness as _check

    stale = _check(result)
    if not stale.ok:
        return stale.status_code or 400, ErrorResponse(error=stale.error or "Unknown error")

    assert stale.value is not None
    return 200, StalenessSchema(**stale.value)


@router.get(
    "/cra/{assessment_id}/oscal-export",
    response={200: dict, 403: ErrorResponse, 404: ErrorResponse},
)
def export_oscal_json(request: HttpRequest, assessment_id: str) -> _Response:
    """Export OSCAL Assessment Results as JSON."""
    import json

    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.oscal_service import serialize_assessment_results

    json_str = serialize_assessment_results(result.oscal_assessment_result)
    return 200, json.loads(json_str)


@router.post(
    "/cra/{assessment_id}/refresh",
    response={200: dict, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 502: ErrorResponse},
)
def refresh_stale(request: HttpRequest, assessment_id: str) -> _Response:
    """Regenerate stale documents."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.document_generation_service import regenerate_stale

    refreshed = regenerate_stale(result)
    if not refreshed.ok:
        return refreshed.status_code or 400, ErrorResponse(error=refreshed.error or "Unknown error")

    return 200, {"refreshed_count": refreshed.value}
