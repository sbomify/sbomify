"""API endpoints for the CRA Compliance Wizard."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from django.http import HttpRequest, HttpResponse
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
    SignatureResponseSchema,
    SignatureSchema,
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


def _get_assessment_or_error(
    request: HttpRequest,
    assessment_id: str,
    *,
    require_mutable: bool = False,
) -> CRAAssessment | _Response:
    """Fetch assessment with access checks (billing gate + team role).

    Thin HTTP-adapter around ``permissions.require_assessment_access``
    — keeps role, billing, and cross-team-404 logic in one place so a
    future rule change (new role, billing plan, enumeration-resistance
    policy) doesn't drift between the view and API surfaces.

    ``require_mutable`` — when ``True``, additionally refuse 409 on
    ``WizardStatus.STALE`` assessments (issue #921). Read endpoints
    keep the default ``False`` so operators can still see the stale
    banner and reconcile via the scope-screening path; mutation
    endpoints pass ``True`` so the 409 short-circuits before any
    persistence write happens.
    """
    from sbomify.apps.compliance.permissions import AccessCheckFailure, require_assessment_access

    result = require_assessment_access(request, assessment_id)
    if isinstance(result, AccessCheckFailure):
        # Route by ``error_code``, not ``status_code``: two distinct
        # 403 cases live behind the same status (role denial vs billing
        # gate) and must surface with different ``error_code`` values
        # so API clients can react programmatically without parsing
        # human-readable messages.
        if result.error_code == "not_found":
            return 404, ErrorResponse(error="Assessment not found", error_code="not_found")
        if result.error_code == "billing_gate":
            return 403, ErrorResponse(
                error="CRA Compliance requires Business plan or higher",
                error_code="billing_gate",
            )
        if result.error_code == "permission_denied":
            return 403, ErrorResponse(error="Forbidden", error_code="permission_denied")
        return result.status_code, ErrorResponse(error=result.message, error_code=result.error_code)

    if require_mutable and result.status == CRAAssessment.WizardStatus.STALE:
        return 409, ErrorResponse(
            error=(
                "Assessment is stale — the product's CRA scope screening now says CRA "
                "does not apply. Re-run the scope screening (flipping CRA back on unstales the "
                "assessment automatically) or delete the assessment before continuing."
            ),
            error_code="assessment_stale",
        )
    return result


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
        justification=f.justification,
        is_mandatory=f.control.is_mandatory,
        annex_part=f.control.annex_part,
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
    response={
        200: CRAAssessmentSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def save_step_data(request: HttpRequest, assessment_id: str, step: int, payload: StepDataSchema) -> _Response:
    """Save data for a wizard step."""
    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
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
    response={
        200: FindingSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def update_finding(
    request: HttpRequest, assessment_id: str, finding_id: str, payload: FindingUpdateSchema
) -> _Response:
    """Update a single finding's status, notes, and justification.

    ``justification`` is required when a Part I control is marked
    ``not-applicable`` (CRA Art 13(4)).
    """
    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
    if not isinstance(result, CRAAssessment):
        return result

    try:
        # Eager-load ``assessment_result__cra_assessment`` so the audit
        # log inside ``update_finding`` doesn't take two extra queries
        # per PUT (one for ``assessment_result``, one for the reverse
        # ``cra_assessment``). Step 3 interactions are latency-sensitive
        # — each finding click hits this endpoint.
        finding = OSCALFinding.objects.select_related(
            "control",
            "assessment_result__catalog",
            "assessment_result__cra_assessment",
        ).get(
            pk=finding_id,
            assessment_result=result.oscal_assessment_result,
        )
    except OSCALFinding.DoesNotExist:
        return 404, ErrorResponse(error="Finding not found", error_code="not_found")

    from .services.oscal_service import update_finding as _update_finding

    try:
        updated = _update_finding(
            finding,
            payload.status,
            payload.notes,
            payload.justification,
            actor=request.user,
        )
    except ValueError as e:
        return 400, ErrorResponse(error=str(e))

    return 200, _finding_to_schema(updated)


@router.post(
    "/cra/{assessment_id}/findings/{finding_id}/observations",
    response={
        201: ObservationSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def create_observation(
    request: HttpRequest, assessment_id: str, finding_id: str, payload: ObservationCreateSchema
) -> _Response:
    """Add an observation (evidence) to a finding."""
    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
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
    response={
        200: DocumentSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
        502: ErrorResponse,
    },
)
def generate_document(request: HttpRequest, assessment_id: str, kind: str) -> _Response:
    """Generate a compliance document."""
    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
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


# Filename slugs per document kind. Used as the ``Content-Disposition``
# attachment name so the file lands in Downloads with a recognisable
# title rather than ``declaration_of_conformity.pdf`` (the raw
# DocumentKind enum value, with underscores). Kept in sync with the
# bundle layout in ``services/export_service._DOC_PATH_MAP``.
_DOC_PDF_FILENAME: dict[str, str] = {
    "vdp": "vulnerability-disclosure-policy.pdf",
    "risk_assessment": "risk-assessment.pdf",
    "user_instructions": "user-instructions.pdf",
    "decommissioning_guide": "secure-decommissioning.pdf",
    "early_warning": "early-warning-template.pdf",
    "full_notification": "vulnerability-notification-template.pdf",
    "final_report": "final-report-template.pdf",
    "declaration_of_conformity": "declaration-of-conformity.pdf",
}


@router.get("/cra/{assessment_id}/documents/{kind}/download")
def download_document_pdf(request: HttpRequest, assessment_id: str, kind: str) -> HttpResponse:
    """Render the named CRA document on-demand and return it as a PDF.

    Reuses the same markdown source the bundle export ships, runs it
    through ``markdown_to_pdf``, and streams the result with a
    ``Content-Disposition: attachment`` header so the browser triggers
    a download rather than rendering inline. We render fresh on every
    request (rather than fetching a cached PDF from S3) so a signature
    update or staleness flip is reflected immediately — the operator
    doesn't have to re-export the whole bundle to grab one document.

    Falls back to a 503 ``ErrorResponse`` when WeasyPrint is unavailable
    (distroless prod without Pango); the client can still hit the
    ``/preview`` endpoint and copy markdown manually in that case.
    """
    from django.http import JsonResponse

    from .services.document_generation_service import get_document_preview
    from .services.pdf_service import markdown_to_pdf

    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        # ``_Response`` returns ``(status, ErrorResponse)`` — wrap into
        # JsonResponse so this view's signature stays HttpResponse.
        status, body = result
        return JsonResponse({"error": getattr(body, "error", "Unknown error")}, status=status)

    preview = get_document_preview(result, kind)
    if not preview.ok:
        return JsonResponse(
            {"error": preview.error or "Unknown error"},
            status=preview.status_code or 400,
        )

    pdf_bytes = markdown_to_pdf(preview.value or "", title=_DOC_PDF_FILENAME.get(kind, kind))
    if pdf_bytes is None:
        return JsonResponse(
            {
                "error": "PDF rendering is unavailable on this server. Use the markdown preview instead.",
                "error_code": "pdf_renderer_unavailable",
            },
            status=503,
        )

    filename = _DOC_PDF_FILENAME.get(kind, f"{kind}.pdf")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


_SIGNATURE_FIELD_MAX = 255
_SIGNATURE_IMAGE_MAX_BYTES = 64 * 1024  # ~64 KB ceiling for the canvas PNG payload.
_SIGNATURE_DATA_URL_PREFIX = "data:image/png;base64,"
# PNG signature — every valid PNG starts with these 8 bytes (ISO/IEC 15948).
# Used to reject payloads that pass the data-URL prefix check but carry
# something other than an actual PNG (a transposed JPEG, a hand-crafted
# blob with the right header, base64-encoded HTML, etc.).
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@router.get(
    "/cra/{assessment_id}/signature",
    response={200: SignatureResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_doc_signature(request: HttpRequest, assessment_id: str) -> _Response:
    """Read the manufacturer signature block stored on the assessment."""
    result = _get_assessment_or_error(request, assessment_id)
    if not isinstance(result, CRAAssessment):
        return result
    return 200, SignatureResponseSchema(
        place=result.signature_place,
        name=result.signature_name,
        function=result.signature_function,
        image=result.signature_image,
        signed_at=result.signed_at.isoformat() if result.signed_at else None,
        is_signed=result.is_signed,
    )


@router.put(
    "/cra/{assessment_id}/signature",
    response={200: SignatureResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def save_doc_signature(request: HttpRequest, assessment_id: str, payload: SignatureSchema) -> _Response:
    """Save the manufacturer signature block.

    The signature image must be a base64-encoded PNG data URL produced
    by the wizard's ``signature_pad`` canvas. We validate the prefix
    and an upper byte cap server-side because:

    * the canvas can in principle return arbitrarily large payloads
      if a future UI change resizes the drawing surface, and
    * the field is rendered into the DoC template as ``data:image/png;
      base64,...`` — anything other than a real PNG would either render
      as a broken image (best case) or get scheme-blocked by the
      ``mark_safe`` rendering path (worst case).

    Saving the signature bumps any existing DoC ``CRAGeneratedDocument``
    to ``is_stale=True`` so the wizard's "Refresh Stale Documents"
    button picks it up — the operator must regenerate before the
    public reader will surface the updated declaration. We do not
    auto-regenerate here because a signature change is a deliberate
    legal act and we want the operator to confirm by clicking
    Generate.
    """
    from datetime import datetime, timezone

    from django.db import transaction

    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
    if not isinstance(result, CRAAssessment):
        return result

    # Length caps on the text fields. Trim trailing whitespace before
    # validating so users pasting from a doc do not trip the cap on a
    # stray newline.
    place = payload.place.strip()
    name = payload.name.strip()
    function = payload.function.strip()
    if not (place and name and function):
        return 400, ErrorResponse(
            error="Place, name, and function are all required.",
            error_code="signature_incomplete",
        )
    for field_name, value in (("place", place), ("name", name), ("function", function)):
        if len(value) > _SIGNATURE_FIELD_MAX:
            return 400, ErrorResponse(
                error=f"{field_name} must be {_SIGNATURE_FIELD_MAX} characters or fewer.",
                error_code="signature_field_too_long",
            )

    # Image validation runs in four stages so a payload that survives
    # the prefix check can't slip past as malformed bytes:
    #   1. data-URL prefix gate
    #   2. strict base64 decode (rejects whitespace / invalid alphabet)
    #   3. PNG magic-byte check on the decoded payload
    #   4. decoded-byte size cap (the previous version capped the
    #      base64 string length, which over-counted by ~33%)
    # We don't decode the IDAT or count non-blank pixels — the front
    # end already enforces ``pad.isEmpty()``, and a bytes-level PNG
    # check is sufficient to keep the DoC renderer / WeasyPrint from
    # blowing up on garbage server-side.
    image = payload.image
    if not image.startswith(_SIGNATURE_DATA_URL_PREFIX):
        return 400, ErrorResponse(
            error="Signature image must be a base64-encoded PNG data URL.",
            error_code="signature_invalid_image",
        )

    encoded = image[len(_SIGNATURE_DATA_URL_PREFIX) :]
    if not encoded:
        return 400, ErrorResponse(
            error="Signature image must contain a base64-encoded PNG payload.",
            error_code="signature_invalid_image",
        )
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return 400, ErrorResponse(
            error="Signature image must be valid base64.",
            error_code="signature_invalid_image",
        )
    if not decoded.startswith(_PNG_MAGIC):
        return 400, ErrorResponse(
            error="Signature image must be a valid PNG.",
            error_code="signature_invalid_image",
        )
    if len(decoded) > _SIGNATURE_IMAGE_MAX_BYTES:
        return 400, ErrorResponse(
            error="Signature image is too large.",
            error_code="signature_image_too_large",
        )

    user = request.user if request.user.is_authenticated else None
    with transaction.atomic():
        result.signature_place = place
        result.signature_name = name
        result.signature_function = function
        result.signature_image = image
        result.signed_at = datetime.now(tz=timezone.utc)
        result.signed_by = user
        result.save(
            update_fields=[
                "signature_place",
                "signature_name",
                "signature_function",
                "signature_image",
                "signed_at",
                "signed_by",
                "updated_at",
            ]
        )
        # Force a stale flag on the existing DoC so the operator
        # regenerates before publishing the new signature.
        from .models import CRAGeneratedDocument

        CRAGeneratedDocument.objects.filter(
            assessment=result,
            document_kind=CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY,
        ).update(is_stale=True)

    return 200, SignatureResponseSchema(
        place=result.signature_place,
        name=result.signature_name,
        function=result.signature_function,
        image=result.signature_image,
        signed_at=result.signed_at.isoformat() if result.signed_at else None,
        is_signed=result.is_signed,
    )


@router.post(
    "/cra/{assessment_id}/export",
    response={
        201: ExportPackageSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
        502: ErrorResponse,
    },
)
def create_export(request: HttpRequest, assessment_id: str) -> _Response:
    """Build a ZIP export package."""
    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
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
def download_export(request: HttpRequest, response: HttpResponse, assessment_id: str, package_id: str) -> _Response:
    """Get a short-lived presigned download URL for an export package.

    Response shape (200):

    - ``download_url``: presigned URL for the ZIP.

    The response carries ``Cache-Control: no-store`` and
    ``Pragma: no-cache`` so intermediate caches (Caddy, corporate
    proxies, browser) don't retain the presigned URL past its server
    lifetime. The URL itself is already short-lived (see
    ``_PRESIGNED_URL_EXPIRY_SECONDS`` in export_service) but the
    cache-control header stops it from being replayed from a stale
    cache entry after expiry. The headers apply to error responses too
    — a 404 or 403 can leak the existence of a package id / assessment
    scope via a shared cache otherwise.
    """
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"

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
    response={
        200: dict,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
        502: ErrorResponse,
    },
)
def refresh_stale(request: HttpRequest, assessment_id: str) -> _Response:
    """Regenerate stale documents."""
    result = _get_assessment_or_error(request, assessment_id, require_mutable=True)
    if not isinstance(result, CRAAssessment):
        return result

    from .services.document_generation_service import regenerate_stale

    refreshed = regenerate_stale(result)
    if not refreshed.ok:
        return refreshed.status_code or 400, ErrorResponse(error=refreshed.error or "Unknown error")

    return 200, {"refreshed_count": refreshed.value}
