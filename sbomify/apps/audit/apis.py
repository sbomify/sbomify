"""Audit log API: list events, export them, and set how long they are kept."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from django.http import HttpRequest, StreamingHttpResponse
from ninja import Query, Router, Schema
from ninja.security import django_auth
from pydantic import Field

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.core.utils import token_to_number

from . import services
from .models import RETENTION_MAX_DAYS, RETENTION_MIN_DAYS

router = Router(tags=["Audit Log"], auth=(PersonalAccessTokenAuth(), django_auth))


class AuditEventFilters(Schema):
    action: str = Field("", description="An action, e.g. product.deleted, or a prefix such as product.")
    actor: str = Field("", description="A user id, or part of the actor's email address.")
    target_type: str = ""
    target_id: str = ""
    outcome: Literal["", "success", "failure", "denied"] = ""
    since: datetime | None = Field(None, description="Events at or after this time.")
    until: datetime | None = Field(None, description="Events before this time.")
    search: str = ""

    def to_filters(self) -> services.AuditFilters:
        return services.AuditFilters(**self.model_dump())


class AuditActor(Schema):
    type: str
    user_id: int | None
    label: str
    role: str


class AuditCredential(Schema):
    kind: str
    id: str


class AuditTarget(Schema):
    type: str
    id: str
    label: str


class AuditRequest(Schema):
    id: str
    ip_address: str | None
    user_agent: str
    method: str
    path: str
    status_code: int | None


class AuditChain(Schema):
    seq: int | None
    prev_hash: str
    entry_hash: str


class AuditEventSchema(Schema):
    event_id: str
    occurred_at: datetime
    action: str
    outcome: str
    actor: AuditActor
    channel: str
    credential: AuditCredential
    target: AuditTarget
    request: AuditRequest
    metadata: dict[str, Any]
    chain: AuditChain


class AuditEventPage(Schema):
    items: list[AuditEventSchema]
    next_cursor: int | None = Field(None, description="Pass as cursor to fetch the next, older, page.")


class AuditRetention(Schema):
    retention_days: int = Field(..., ge=RETENTION_MIN_DAYS, le=RETENTION_MAX_DAYS)


def _workspace(request: HttpRequest, workspace_key: str) -> tuple[int, Any]:
    from sbomify.apps.teams.models import Workspace

    try:
        workspace = Workspace.objects.get(pk=token_to_number(workspace_key))
    except (ValueError, Workspace.DoesNotExist):
        return 404, {"detail": "Workspace not found"}
    return 200, workspace


def _authorized(request: HttpRequest, workspace_key: str, action: str = "audit_log:read") -> tuple[int, Any]:
    status, workspace = _workspace(request, workspace_key)
    if status != 200:
        return status, workspace
    allowed = services.authorize(request, workspace, action)
    if not allowed.ok:
        return allowed.status_code or 403, {"detail": allowed.error}
    return 200, workspace


@router.get(
    "/{workspace_key}/events",
    response={200: AuditEventPage, 402: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def list_audit_events(
    request: HttpRequest,
    workspace_key: str,
    filters: Query[AuditEventFilters],
    cursor: int | None = None,
    limit: int = services.PAGE_SIZE,
) -> tuple[int, Any]:
    """List a workspace's audit events, newest first. Owners and admins, Enterprise plan."""
    status, workspace = _authorized(request, workspace_key)
    if status != 200:
        return status, workspace
    page = services.list_events(workspace.pk, filters.to_filters(), cursor=cursor, limit=limit)
    return 200, {"items": [services.serialize(e) for e in page.events], "next_cursor": page.next_cursor}


@router.get(
    "/{workspace_key}/events/export",
    response={200: None, 402: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def export_audit_events(
    request: HttpRequest,
    workspace_key: str,
    filters: Query[AuditEventFilters],
    export_format: Literal["csv", "jsonl"] = Query("csv", alias="format"),  # type: ignore[type-arg]
) -> Any:
    """Download matching events as CSV or JSON Lines, newest first, at most 100,000 per file."""
    status, workspace = _authorized(request, workspace_key)
    if status != 200:
        return status, workspace
    return export_response(workspace, filters.to_filters(), export_format)


def export_response(workspace: Any, filters: services.AuditFilters, export_format: str) -> StreamingHttpResponse:
    services.record_export(workspace, filters, export_format)
    if export_format == "jsonl":
        body, content_type = services.export_jsonl(workspace.pk, filters), "application/x-ndjson"
    else:
        body, content_type = services.export_csv(workspace.pk, filters), "text/csv; charset=utf-8"
    response = StreamingHttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="audit-log-{workspace.key}.{export_format}"'
    response["Cache-Control"] = "private, no-store"
    return response


@router.get(
    "/{workspace_key}/retention",
    response={200: AuditRetention, 402: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def get_audit_retention(request: HttpRequest, workspace_key: str) -> tuple[int, Any]:
    """How many days the workspace keeps audit events."""
    status, workspace = _authorized(request, workspace_key)
    if status != 200:
        return status, workspace
    return 200, {"retention_days": workspace.audit_log_retention_days}


@router.put(
    "/{workspace_key}/retention",
    response={200: AuditRetention, 400: ErrorResponse, 402: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def set_audit_retention(request: HttpRequest, workspace_key: str, payload: AuditRetention) -> tuple[int, Any]:
    """Set how many days audit events are kept, between 30 and 3650."""
    status, workspace = _workspace(request, workspace_key)
    if status != 200:
        return status, workspace
    result = services.update_retention(request, workspace, payload.retention_days)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error}
    return 200, {"retention_days": result.value}
