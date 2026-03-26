from __future__ import annotations

import re
from typing import Any, cast

from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.controls.models import Control, ControlCatalog, ControlEvidence, ControlStatus
from sbomify.apps.controls.schemas import (
    ActivateCatalogSchema,
    AutomationMappingSchema,
    AutomationSyncResultSchema,
    BulkMappingSchema,
    BulkResultSchema,
    BulkStatusUpdateSchema,
    CatalogDetailSchema,
    CatalogPatchSchema,
    CatalogSchema,
    ControlEvidenceSchema,
    ControlMappingSchema,
    ControlStatusSchema,
    ControlWithStatusSchema,
    CreateEvidenceSchema,
    CreateMappingSchema,
    PublicControlsSummarySchema,
    StatusUpdateSchema,
)
from sbomify.apps.controls.services.automation_service import (
    get_automation_mappings,
    sync_from_latest_assessments,
)
from sbomify.apps.controls.services.catalog_service import (
    activate_builtin_catalog,
    delete_catalog,
    get_active_catalogs,
    get_all_catalogs,
)
from sbomify.apps.controls.services.export_service import (
    export_controls_csv,
    export_controls_summary_csv,
)
from sbomify.apps.controls.services.mapping_service import (
    create_mapping,
    get_mappings_for_control,
    import_mappings_bulk,
)
from sbomify.apps.controls.services.public_service import (
    get_public_controls,
    get_public_product_controls,
)
from sbomify.apps.controls.services.status_service import (
    bulk_update_statuses,
    get_controls_detail,
    upsert_status,
)
from sbomify.apps.core.models import Product, User
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.models import Member, Team
from sbomify.logging import getLogger

logger = getLogger(__name__)

router = Router(tags=["Controls"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_user_team(request: HttpRequest) -> tuple[Team | None, tuple[int, ErrorResponse] | None]:
    """Resolve team from session or token, return (team, error_tuple)."""
    from sbomify.apps.core.apis import _get_user_team_id

    team_id = _get_user_team_id(request)
    if not team_id:
        return None, (403, ErrorResponse(detail="No current workspace"))

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return None, (404, ErrorResponse(detail="Workspace not found"))

    return team, None


def _check_admin_role(request: HttpRequest, team: Team) -> tuple[int, ErrorResponse] | None:
    """Return an error tuple if the user is not owner or admin."""
    user = cast(User, request.user)
    member = Member.objects.filter(user=user, team=team).only("role").first()
    if not member or member.role not in ("owner", "admin"):
        return 403, ErrorResponse(detail="Only workspace owners and admins can perform this action")
    return None


# ---------------------------------------------------------------------------
# Authenticated endpoints — Catalogs
# ---------------------------------------------------------------------------


@router.get(
    "/catalogs/",
    response={200: list[CatalogSchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="List catalogs for the current workspace",
)
def list_catalogs(request: HttpRequest, include_inactive: bool = False) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    result = get_all_catalogs(team) if include_inactive else get_active_catalogs(team)
    if not result.ok:
        return 400, ErrorResponse(detail=result.error or "Unknown error")

    catalogs = result.value or []
    return 200, [
        CatalogSchema(
            id=c.id,
            name=c.name,
            version=c.version,
            source=c.source,
            is_active=c.is_active,
            created_at=c.created_at,
        )
        for c in catalogs
    ]


@router.post(
    "/catalogs/activate/",
    response={201: CatalogSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Activate a built-in catalog",
)
def activate_catalog(request: HttpRequest, payload: ActivateCatalogSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    result = activate_builtin_catalog(team, payload.catalog_name)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    catalog = result.value
    assert catalog is not None
    return 201, CatalogSchema(
        id=catalog.id,
        name=catalog.name,
        version=catalog.version,
        source=catalog.source,
        is_active=catalog.is_active,
        created_at=catalog.created_at,
    )


@router.post(
    "/catalogs/import-oscal/",
    response={201: CatalogSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Import an OSCAL catalog",
)
def import_oscal(request: HttpRequest) -> tuple[int, Any]:
    """Import an OSCAL catalog JSON. Accepts standard NIST OSCAL format."""
    import json

    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    # Parse JSON from request body
    try:
        oscal_json = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return 400, ErrorResponse(detail="Invalid JSON in request body")
    except Exception:
        return 400, ErrorResponse(detail="Request body too large. Maximum upload size is 20 MB.")

    if not isinstance(oscal_json, dict):
        return 400, ErrorResponse(detail="Request body must be a JSON object")

    # Reject catalogs with more than 2000 controls to prevent abuse
    def _count_oscal_controls(data: dict[str, Any]) -> int:
        total = 0
        for g in data.get("catalog", {}).get("groups", []):
            ctrls = g.get("controls", [])
            total += len(ctrls)
            for c in ctrls:
                total += len(c.get("controls", []))  # sub-controls
        return total

    if _count_oscal_controls(oscal_json) > 2000:
        return 400, ErrorResponse(detail="Catalog exceeds maximum of 2000 controls")

    from sbomify.apps.controls.services.catalog_service import import_oscal_catalog

    result = import_oscal_catalog(team, oscal_json)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    catalog = result.value
    assert catalog is not None
    return 201, CatalogSchema(
        id=catalog.id,
        name=catalog.name,
        version=catalog.version,
        source=catalog.source,
        is_active=catalog.is_active,
        created_at=catalog.created_at,
    )


@router.get(
    "/catalogs/{catalog_id}/",
    response={200: CatalogDetailSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Get catalog detail",
)
def get_catalog(request: HttpRequest, catalog_id: str) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return 404, ErrorResponse(detail="Catalog not found")

    return 200, CatalogDetailSchema(
        id=catalog.id,
        name=catalog.name,
        version=catalog.version,
        source=catalog.source,
        is_active=catalog.is_active,
        created_at=catalog.created_at,
        controls_count=catalog.controls.count(),
    )


@router.patch(
    "/catalogs/{catalog_id}/",
    response={200: CatalogSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Update catalog (toggle is_active)",
)
def update_catalog(request: HttpRequest, catalog_id: str, payload: CatalogPatchSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return 404, ErrorResponse(detail="Catalog not found")

    catalog.is_active = payload.is_active
    catalog.save(update_fields=["is_active", "updated_at"])

    return 200, CatalogSchema(
        id=catalog.id,
        name=catalog.name,
        version=catalog.version,
        source=catalog.source,
        is_active=catalog.is_active,
        created_at=catalog.created_at,
    )


@router.delete(
    "/catalogs/{catalog_id}/",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Delete a catalog and all its controls/statuses",
)
def delete_catalog_endpoint(request: HttpRequest, catalog_id: str) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    result = delete_catalog(catalog_id, team)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    return 204, None


# ---------------------------------------------------------------------------
# Authenticated endpoints — CSV Export
# ---------------------------------------------------------------------------


@router.get(
    "/catalogs/{catalog_id}/export/csv",
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Export controls as CSV",
)
def export_csv(request: HttpRequest, catalog_id: str, product_id: str | None = None) -> HttpResponse | tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return 404, ErrorResponse(detail="Catalog not found")

    product = None
    if product_id:
        try:
            product = Product.objects.get(id=product_id, team=team)
        except Product.DoesNotExist:
            return 404, ErrorResponse(detail="Product not found")

    result = export_controls_csv(team, catalog, product)
    if not result.ok:
        return 400, ErrorResponse(detail=result.error or "Export failed")

    safe_name = re.sub(r"[^a-z0-9\-]", "-", catalog.name.lower()).strip("-")
    filename = f"{safe_name}-controls.csv"
    response = HttpResponse(result.value, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@router.get(
    "/catalogs/{catalog_id}/export/summary-csv",
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Export controls summary as CSV",
)
def export_summary_csv(request: HttpRequest, catalog_id: str) -> HttpResponse | tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return 404, ErrorResponse(detail="Catalog not found")

    result = export_controls_summary_csv(team, catalog=catalog)
    if not result.ok:
        return 400, ErrorResponse(detail=result.error or "Export failed")

    response = HttpResponse(result.value, content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="controls-summary.csv"'
    return response


# ---------------------------------------------------------------------------
# Authenticated endpoints — Controls & Statuses
# ---------------------------------------------------------------------------


@router.get(
    "/catalogs/{catalog_id}/controls/",
    response={200: list[ControlWithStatusSchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="List controls with statuses for a catalog",
)
def list_controls(request: HttpRequest, catalog_id: str, product_id: str | None = None) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return 404, ErrorResponse(detail="Catalog not found")

    product = None
    if product_id:
        try:
            product = Product.objects.get(id=product_id, team=team)
        except Product.DoesNotExist:
            return 404, ErrorResponse(detail="Product not found")

    result = get_controls_detail(catalog, product)
    if not result.ok:
        return 400, ErrorResponse(detail=result.error or "Unknown error")

    controls_list: list[ControlWithStatusSchema] = []
    for group in result.value or []:
        for ctrl in group.get("controls", []):
            controls_list.append(
                ControlWithStatusSchema(
                    id=ctrl["id"],
                    control_id=ctrl["control_id"],
                    group=ctrl["group"],
                    title=ctrl["title"],
                    description=ctrl.get("description", ""),
                    status=ctrl.get("status", "not_implemented"),
                    notes=ctrl.get("notes", ""),
                    updated_at=None,
                )
            )

    return 200, controls_list


@router.put(
    "/controls/{control_id}/status/",
    response={200: ControlStatusSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Upsert a control status",
)
def upsert_control_status(request: HttpRequest, control_id: str, payload: StatusUpdateSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    try:
        control = Control.objects.select_related("catalog").get(id=control_id, catalog__team=team)
    except Control.DoesNotExist:
        return 404, ErrorResponse(detail="Control not found")

    product = None
    if payload.product_id:
        try:
            product = Product.objects.get(id=payload.product_id, team=team)
        except Product.DoesNotExist:
            return 404, ErrorResponse(detail="Product not found")

    user = cast(User, request.user)
    result = upsert_status(control, product, payload.status, user, payload.notes)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    cs = result.value
    assert cs is not None
    return 200, ControlStatusSchema(
        id=cs.id,
        control_id=control.control_id,
        status=cs.status,
        notes=cs.notes,
        product_id=cs.product_id,
        updated_at=cs.updated_at,
    )


@router.post(
    "/status/bulk/",
    response={200: BulkResultSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Bulk update control statuses (atomic)",
)
def bulk_update(request: HttpRequest, payload: BulkStatusUpdateSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    user = cast(User, request.user)
    updates = [item.model_dump() for item in payload.items]
    result = bulk_update_statuses(updates, user, team=team)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    return 200, BulkResultSchema(updated=result.value or 0)


# ---------------------------------------------------------------------------
# Authenticated endpoints — Control Mappings
# ---------------------------------------------------------------------------


@router.get(
    "/controls/{control_id}/mappings/",
    response={200: list[ControlMappingSchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Get all mappings for a control (both directions)",
)
def list_control_mappings(request: HttpRequest, control_id: str) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    try:
        control = Control.objects.select_related("catalog").get(id=control_id, catalog__team=team)
    except Control.DoesNotExist:
        return 404, ErrorResponse(detail="Control not found")

    result = get_mappings_for_control(control)
    if not result.ok:
        return 400, ErrorResponse(detail=result.error or "Unknown error")

    return 200, [
        ControlMappingSchema(
            id=m.id,
            source_control_id=m.source_control_id,
            source_control_label=m.source_control.control_id,
            source_catalog_name=m.source_control.catalog.name,
            target_control_id=m.target_control_id,
            target_control_label=m.target_control.control_id,
            target_catalog_name=m.target_control.catalog.name,
            relation_type=m.relation_type,
            notes=m.notes,
            created_at=m.created_at,
        )
        for m in (result.value or [])
    ]


@router.post(
    "/mappings/",
    response={
        201: ControlMappingSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Create a control mapping (admin only)",
)
def create_control_mapping(request: HttpRequest, payload: CreateMappingSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    try:
        source = Control.objects.select_related("catalog").get(id=payload.source_control_id, catalog__team=team)
    except Control.DoesNotExist:
        return 404, ErrorResponse(detail="Source control not found")

    try:
        target = Control.objects.select_related("catalog").get(id=payload.target_control_id, catalog__team=team)
    except Control.DoesNotExist:
        return 404, ErrorResponse(detail="Target control not found")

    result = create_mapping(source, target, payload.relation_type, payload.notes)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    m = result.value
    assert m is not None
    return 201, ControlMappingSchema(
        id=m.id,
        source_control_id=m.source_control_id,
        source_control_label=source.control_id,
        source_catalog_name=source.catalog.name,
        target_control_id=m.target_control_id,
        target_control_label=target.control_id,
        target_catalog_name=target.catalog.name,
        relation_type=m.relation_type,
        notes=m.notes,
        created_at=m.created_at,
    )


@router.post(
    "/mappings/bulk/",
    response={200: BulkResultSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Bulk import control mappings (admin only)",
)
def bulk_import_mappings(request: HttpRequest, payload: BulkMappingSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    items = [item.model_dump() for item in payload.items]
    result = import_mappings_bulk(items, team)
    if not result.ok:
        status_code = result.status_code or 400
        return status_code, ErrorResponse(detail=result.error or "Unknown error")

    return 200, BulkResultSchema(updated=result.value or 0)


# ---------------------------------------------------------------------------
# Authenticated endpoints — Evidence
# ---------------------------------------------------------------------------

_VALID_EVIDENCE_TYPES = {choice[0] for choice in ControlEvidence.EvidenceType.choices}


def _resolve_control_status(
    control_id: str, team: Team
) -> tuple[ControlStatus | None, tuple[int, ErrorResponse] | None]:
    """Find the ControlStatus for a control scoped to a team.

    Looks up the global (product=None) status first. If none exists yet the
    control is valid, auto-creates a NOT_IMPLEMENTED status so evidence can
    still be attached.
    """
    try:
        control = Control.objects.select_related("catalog").get(id=control_id, catalog__team=team)
    except Control.DoesNotExist:
        return None, (404, ErrorResponse(detail="Control not found"))

    control_status = ControlStatus.objects.filter(control=control, product__isnull=True).first()
    if not control_status:
        control_status = ControlStatus.objects.create(
            control=control,
            product=None,
            status=ControlStatus.Status.NOT_IMPLEMENTED,
        )
    return control_status, None


@router.get(
    "/controls/{control_id}/evidence/",
    response={200: list[ControlEvidenceSchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="List evidence for a control",
)
def list_evidence(request: HttpRequest, control_id: str) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    control_status, cs_err = _resolve_control_status(control_id, team)
    if cs_err:
        return cs_err

    assert control_status is not None
    evidence_qs = ControlEvidence.objects.filter(control_status=control_status)
    return 200, [
        ControlEvidenceSchema(
            id=ev.id,
            evidence_type=ev.evidence_type,
            title=ev.title,
            url=ev.url,
            document_id=ev.document_id,
            description=ev.description,
            created_at=ev.created_at,
        )
        for ev in evidence_qs
    ]


@router.post(
    "/controls/{control_id}/evidence/",
    response={201: ControlEvidenceSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Add evidence to a control",
)
def add_evidence(request: HttpRequest, control_id: str, payload: CreateEvidenceSchema) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    if payload.evidence_type not in _VALID_EVIDENCE_TYPES:
        return 400, ErrorResponse(
            detail=f"Invalid evidence_type '{payload.evidence_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_EVIDENCE_TYPES))}"
        )

    control_status, cs_err = _resolve_control_status(control_id, team)
    if cs_err:
        return cs_err

    assert control_status is not None
    user = cast(User, request.user)
    ev = ControlEvidence.objects.create(
        control_status=control_status,
        evidence_type=payload.evidence_type,
        title=payload.title,
        url=payload.url,
        document_id=payload.document_id,
        description=payload.description,
        created_by=user,
    )
    return 201, ControlEvidenceSchema(
        id=ev.id,
        evidence_type=ev.evidence_type,
        title=ev.title,
        url=ev.url,
        document_id=ev.document_id,
        description=ev.description,
        created_at=ev.created_at,
    )


@router.delete(
    "/evidence/{evidence_id}/",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Delete evidence",
)
def delete_evidence(request: HttpRequest, evidence_id: str) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    try:
        ev = ControlEvidence.objects.select_related("control_status__control__catalog").get(
            id=evidence_id, control_status__control__catalog__team=team
        )
    except ControlEvidence.DoesNotExist:
        return 404, ErrorResponse(detail="Evidence not found")

    ev.delete()
    return 204, None


# ---------------------------------------------------------------------------
# Authenticated endpoints — Automation
# ---------------------------------------------------------------------------


@router.post(
    "/automation/sync/",
    response={200: AutomationSyncResultSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Sync control statuses from latest plugin assessments (admin only)",
)
def sync_automation(request: HttpRequest) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    assert team is not None
    admin_err = _check_admin_role(request, team)
    if admin_err:
        return admin_err

    result = sync_from_latest_assessments(team)
    if not result.ok:
        return 400, ErrorResponse(detail=result.error or "Sync failed")

    data = result.value
    assert data is not None
    return 200, AutomationSyncResultSchema(
        total_updated=data["total_updated"],
        by_plugin=data["by_plugin"],
    )


@router.get(
    "/automation/mappings/",
    response={200: AutomationMappingSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
    summary="Get plugin-to-control automation mappings",
)
def list_automation_mappings(request: HttpRequest) -> tuple[int, Any]:
    team, err = _get_user_team(request)
    if err:
        return err

    return 200, AutomationMappingSchema(mappings=get_automation_mappings())


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


@router.get(
    "/public/{workspace_key}/",
    response={200: PublicControlsSummarySchema, 404: ErrorResponse},
    auth=None,
    summary="Public controls compliance summary for a workspace",
)
def public_controls_summary(request: HttpRequest, workspace_key: str) -> HttpResponse | tuple[int, Any]:
    try:
        team_id = token_to_number(workspace_key)
    except ValueError:
        return 404, ErrorResponse(detail="Workspace not found")

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, ErrorResponse(detail="Workspace not found")

    if not team.is_public:
        return 404, ErrorResponse(detail="Workspace not found")

    result = get_public_controls(team)
    if not result.ok:
        status_code = result.status_code or 404
        return status_code, ErrorResponse(detail=result.error or "No active catalog")

    data = result.value
    assert data is not None
    response_schema = PublicControlsSummarySchema(
        catalog_name=data["catalog"]["name"],
        catalog_version=data["catalog"].get("version", ""),
        total=data["total"],
        addressed=data["addressed"],
        percentage=data["percentage"],
        by_status=data["by_status"],
        categories=data["categories"],
    )

    response = HttpResponse(
        response_schema.model_dump_json(),
        content_type="application/json",
        status=200,
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response


@router.get(
    "/public/{workspace_key}/{product_id}/",
    response={200: PublicControlsSummarySchema, 404: ErrorResponse},
    auth=None,
    summary="Public controls compliance summary for a product",
)
def public_product_controls_summary(
    request: HttpRequest, workspace_key: str, product_id: str
) -> HttpResponse | tuple[int, Any]:
    try:
        team_id = token_to_number(workspace_key)
    except ValueError:
        return 404, ErrorResponse(detail="Workspace not found")

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, ErrorResponse(detail="Workspace not found")

    if not team.is_public:
        return 404, ErrorResponse(detail="Workspace not found")

    try:
        product = Product.objects.get(id=product_id, team=team)
    except Product.DoesNotExist:
        return 404, ErrorResponse(detail="Product not found")

    if not product.is_public:
        return 404, ErrorResponse(detail="Product not found")

    result = get_public_product_controls(product)
    if not result.ok:
        status_code = result.status_code or 404
        return status_code, ErrorResponse(detail=result.error or "No active catalog")

    data = result.value
    assert data is not None
    response_schema = PublicControlsSummarySchema(
        catalog_name=data["catalog"]["name"],
        catalog_version=data["catalog"].get("version", ""),
        total=data["total"],
        addressed=data["addressed"],
        percentage=data["percentage"],
        by_status=data["by_status"],
        categories=data["categories"],
    )

    response = HttpResponse(
        response_schema.model_dump_json(),
        content_type="application/json",
        status=200,
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response
