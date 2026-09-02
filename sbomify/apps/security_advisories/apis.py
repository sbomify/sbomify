"""The advisories API.

Every neighbouring domain has one and advisories did not, so the pages here
reached past the API into the services directly, the MCP server had no
advisory tools to offer, and a customer wanting a trust centre's advisories
programmatically had to read HTML.

The endpoints compose the same service functions the pages call, so there is
one implementation of what an advisory is and what publishing one means. What
this module adds is the wire contract: authorization through ``can()`` and a
response shape that carries the record rather than the presentation.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.authz import can
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.security_advisories.schemas import (
    AdvisoryDetailSchema,
    AdvisorySchema,
    CreateAdvisorySchema,
    PublishAdvisorySchema,
    UpdateAdvisorySchema,
)
from sbomify.apps.security_advisories.services import advisories as advisory_service
from sbomify.apps.teams.models import Team

router = Router(tags=["Security Advisories"])

AUTH = (PersonalAccessTokenAuth(), django_auth)


def _workspace(request: HttpRequest) -> tuple[Team | None, tuple[int, ErrorResponse] | None]:
    """The caller's current workspace, from the session or the token."""
    from sbomify.apps.core.apis import _get_user_team_id

    team_id = _get_user_team_id(request)
    if not team_id:
        return None, (
            403,
            ErrorResponse(detail="No current workspace selected", error_code=ErrorCode.NO_CURRENT_TEAM),
        )
    team = Team.objects.filter(pk=team_id).first()
    if team is None:
        return None, (404, ErrorResponse(detail="Workspace not found", error_code=ErrorCode.TEAM_NOT_FOUND))
    return team, None


def _api_shape(projection: dict[str, Any]) -> dict[str, Any]:
    """The service projection, reduced to the contract.

    The projection is built for the pages and names the fix's progress
    ``status``; the model calls that ``remediation_status`` and keeps
    ``status`` for publication. The wire follows the model, because a client
    reading ``status`` should get the same field the database calls that.
    """
    shape: dict[str, Any] = {
        "id": projection["pk"],
        "tracking_id": projection["id"],
        "title": projection["title"],
        "summary": projection.get("summary", ""),
        "description": projection.get("description", ""),
        "advisory_type": projection["advisory_type"],
        "severity": projection.get("severity", ""),
        "cvss_score": projection.get("cvss_score"),
        "cvss_vector": projection.get("cvss_vector", ""),
        "status": projection["publication_status"],
        "remediation_status": projection["status"],
        "is_open": projection["is_open"],
        "visibility": projection["visibility"],
        "vulnerability_count": projection.get("vulnerability_count", 0),
        "vulnerability_id": projection.get("vulnerability_id", ""),
        "products": [
            {"id": p.get("id"), "name": p.get("name", ""), "affected_ranges": p.get("affected_ranges", [])}
            for p in projection.get("products", [])
        ],
        "created_at": projection["created_at"],
        "updated_at": projection["updated_at"],
        "published_at": projection.get("published_at"),
    }
    if "vulnerabilities" in projection:
        shape["vulnerabilities"] = projection["vulnerabilities"]
        shape["references"] = projection.get("references", [])
        shape["timeline"] = [
            {
                "id": event["id"],
                "kind": event["kind"],
                "body": event.get("body", ""),
                "actor": event.get("actor", ""),
                "from_status": event.get("from_status"),
                "to_status": event.get("to_status"),
                "created_at": event["created_at"],
            }
            for event in projection.get("timeline", [])
        ]
    return shape


def _failed(result: Any) -> tuple[int, ErrorResponse]:
    """A service failure, at the status the service chose."""
    status = result.status_code or 400
    code = ErrorCode.NOT_FOUND if status == 404 else ErrorCode.BAD_REQUEST
    return status, ErrorResponse(detail=result.error or "Request failed", error_code=code)


@router.get(
    "/",
    response={200: list[AdvisorySchema], 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="List advisories in the current workspace",
)
def list_advisories(request: HttpRequest, search: str = "") -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:read", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    result = advisory_service.list_advisories(team, search)
    if not result.ok:
        return _failed(result)
    return 200, [_api_shape(item) for item in result.value or []]


@router.post(
    "/",
    response={201: AdvisoryDetailSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="Create an advisory",
)
def create_advisory(request: HttpRequest, payload: CreateAdvisorySchema) -> tuple[int, Any]:
    from sbomify.apps.core.models import Product

    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:manage", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    # Scoped to the workspace: an id from elsewhere names no product here
    # rather than attaching one the caller cannot see.
    products = list(Product.objects.filter(id__in=payload.product_ids, team=team)) if payload.product_ids else []

    created = advisory_service.create_advisory(
        team,
        request.user,
        title=payload.title,
        severity=payload.severity,
        description=payload.description,
        identifier=payload.identifier,
        remediation_status=payload.remediation_status,
        cvss_score=payload.cvss_score,
        cvss_vector=payload.cvss_vector,
        products=products,
    )
    if not created.ok:
        return _failed(created)

    fetched = advisory_service.get_advisory(team, created.value or "")
    if not fetched.ok:
        return _failed(fetched)
    return 201, _api_shape(fetched.value or {})


@router.get(
    "/{advisory_id}",
    response={200: AdvisoryDetailSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="Get one advisory",
)
def get_advisory(request: HttpRequest, advisory_id: str) -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:read", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    result = advisory_service.get_advisory(team, advisory_id)
    if not result.ok:
        return _failed(result)
    return 200, _api_shape(result.value or {})


@router.patch(
    "/{advisory_id}",
    response={200: AdvisoryDetailSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="Update an advisory's own fields",
)
def update_advisory(request: HttpRequest, advisory_id: str, payload: UpdateAdvisorySchema) -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:manage", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    updated = advisory_service.update_advisory(
        team,
        request.user,
        advisory_id,
        title=payload.title,
        severity=payload.severity,
        description=payload.description,
        cvss_score=None if payload.cvss_score is None else str(payload.cvss_score),
        cvss_vector=payload.cvss_vector,
    )
    if not updated.ok:
        return _failed(updated)

    result = advisory_service.get_advisory(team, advisory_id)
    if not result.ok:
        return _failed(result)
    return 200, _api_shape(result.value or {})


@router.post(
    "/{advisory_id}/publish",
    response={200: AdvisoryDetailSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="Publish an advisory at a visibility",
)
def publish_advisory(request: HttpRequest, advisory_id: str, payload: PublishAdvisorySchema) -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:publish", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    published = advisory_service.publish_advisory(team, request.user, advisory_id, visibility=payload.visibility)
    if not published.ok:
        return _failed(published)

    result = advisory_service.get_advisory(team, advisory_id)
    if not result.ok:
        return _failed(result)
    return 200, _api_shape(result.value or {})
