"""The advisories API.

Every neighbouring domain has one and advisories did not, so the pages here
reached past the API into the services directly, the MCP server had no
advisory tools to offer, and a customer wanting a trust centre's advisories
programmatically had to read HTML.

The endpoints compose the same service functions the pages call, so there is
one implementation of what an advisory is and what publishing one means. What
this module adds is the wire contract: authorization through ``can()`` and a
response shape that carries the record rather than the presentation.

Two halves. The workspace half is authenticated and scoped to the caller's
current workspace. The public half is the trust center over JSON: no auth
required, a workspace named in the path, and every row filtered by the same
viewer scoping the trust-center pages use, so a gated advisory is exactly as
hidden here as it is there. Each public advisory is also served as a CSAF 2.0
document for scanners and aggregators.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from django.http import HttpRequest
from django.urls import reverse
from ninja import Router
from ninja.decorators import decorate_view
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth, optional_token_auth
from sbomify.apps.core.authz import can
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.core.url_utils import build_custom_domain_url, get_base_url
from sbomify.apps.core.views.workspace_public import fetch_public_team
from sbomify.apps.plugins.utils import get_sbomify_version
from sbomify.apps.security_advisories.csaf import render_csaf
from sbomify.apps.security_advisories.schemas import (
    AdvisoryDetailSchema,
    AdvisorySchema,
    AdvisoryUpdateSchema,
    CreateAdvisorySchema,
    PublicAdvisoryDetailSchema,
    PublicAdvisoryListSchema,
    PublishAdvisorySchema,
    UpdateAdvisorySchema,
    WithdrawAdvisorySchema,
)
from sbomify.apps.security_advisories.services import advisories as advisory_service
from sbomify.apps.security_advisories.services import trust_center
from sbomify.apps.teams.models import Team

router = Router(tags=["Security Advisories"])

AUTH = (PersonalAccessTokenAuth(), django_auth)

# The placeholder _version_expressions prints for "no versions recorded".
_NO_VERSIONS = "—"


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


def _tracking_id(projection: dict[str, Any]) -> str:
    """The allocated identifier, or nothing.

    The projection's ``id`` is ``display_id()``, which falls back to the
    primary key so a draft is addressable on screen. The contract says
    ``tracking_id`` is allocated at publication, so a draft reports none.
    """
    return "" if projection["id"] == projection["pk"] else str(projection["id"])


def _api_shape(projection: dict[str, Any]) -> dict[str, Any]:
    """The service projection, reduced to the contract.

    The projection is built for the pages and names the fix's progress
    ``status``; the model calls that ``remediation_status`` and keeps
    ``status`` for publication. The wire follows the model, because a client
    reading ``status`` should get the same field the database calls that.
    """
    shape: dict[str, Any] = {
        "id": projection["pk"],
        "tracking_id": _tracking_id(projection),
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
        "withdrawn_at": projection.get("withdrawn_at"),
        "withdrawal_reason": projection.get("withdrawal_reason", ""),
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
    code = {404: ErrorCode.NOT_FOUND, 409: ErrorCode.CONFLICT}.get(status, ErrorCode.BAD_REQUEST)
    return status, ErrorResponse(detail=result.error or "Request failed", error_code=code)


def _fetched(team: Team, advisory_id: str) -> tuple[int, Any]:
    result = advisory_service.get_advisory(team, advisory_id)
    if not result.ok:
        return _failed(result)
    return 200, _api_shape(result.value or {})


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
    from sbomify.apps.core.models import Product, Release

    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:manage", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    # Scoped to the workspace: an id from elsewhere names no product here
    # rather than attaching one the caller cannot see. Releases are scoped the
    # same way; the service then holds them to the products actually named.
    products = list(Product.objects.filter(id__in=payload.product_ids, team=team)) if payload.product_ids else []
    releases = (
        list(Release.objects.filter(id__in=payload.affected_release_ids, product__team=team))
        if payload.affected_release_ids
        else []
    )

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
        affected_releases=releases,
    )
    if not created.ok:
        return _failed(created)

    status, body = _fetched(team, created.value or "")
    return (201, body) if status == 200 else (status, body)


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

    return _fetched(team, advisory_id)


@router.patch(
    "/{advisory_id}",
    response={200: AdvisoryDetailSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="Update an advisory's own fields",
    description="Fields left out of the body keep their stored value. Send cvss_score as null to clear the CVSS entry.",
)
def update_advisory(request: HttpRequest, advisory_id: str, payload: UpdateAdvisorySchema) -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:manage", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    current = advisory_service.get_advisory(team, advisory_id)
    if not current.ok:
        return _failed(current)
    stored = current.value or {}

    # The service treats a missing severity or CVSS as "leave it alone" and a
    # missing description as blank, which is right for a form and wrong for
    # a PATCH. Only what the body carried is written; the rest is re-sent as
    # it stands.
    sent = payload.model_dump(exclude_unset=True)
    cvss_score = None
    cvss_vector = None
    if "cvss_score" in sent or "cvss_vector" in sent:
        score = sent.get("cvss_score", stored.get("cvss_score"))
        cvss_score = "" if score is None else str(score)
        if "cvss_vector" in sent:
            # Sent vectors always reach the service, so a vector with no
            # score to attach to is refused there rather than dropped here.
            cvss_vector = sent["cvss_vector"] or ""
        else:
            # Clearing the score clears the stored vector with it; changing
            # the score alone keeps it.
            cvss_vector = (stored.get("cvss_vector") or "") if score is not None else ""

    updated = advisory_service.update_advisory(
        team,
        request.user,
        advisory_id,
        title=sent.get("title") or stored["title"],
        severity=(sent["severity"] or "") if "severity" in sent else None,
        description=sent["description"] or "" if "description" in sent else stored.get("description", ""),
        cvss_score=cvss_score,
        cvss_vector=cvss_vector,
    )
    if not updated.ok:
        return _failed(updated)

    return _fetched(team, advisory_id)


@router.post(
    "/{advisory_id}/updates",
    response={200: AdvisoryDetailSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=AUTH,
    summary="Post a timeline update or move the remediation status",
    description="kind is 'update' for a note, or a remediation status to move to, with the note as commentary.",
)
def post_advisory_update(request: HttpRequest, advisory_id: str, payload: AdvisoryUpdateSchema) -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:manage", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    posted = advisory_service.post_update(team, request.user, advisory_id, kind=payload.kind, note=payload.note)
    if not posted.ok:
        return _failed(posted)

    return _fetched(team, advisory_id)


@router.post(
    "/{advisory_id}/publish",
    response={
        200: AdvisoryDetailSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
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

    return _fetched(team, advisory_id)


@router.post(
    "/{advisory_id}/withdraw",
    response={
        200: AdvisoryDetailSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
    auth=AUTH,
    summary="Withdraw a published advisory",
    description="The advisory stays listed on the trust center, marked withdrawn and carrying the reason.",
)
def withdraw_advisory(request: HttpRequest, advisory_id: str, payload: WithdrawAdvisorySchema) -> tuple[int, Any]:
    team, error = _workspace(request)
    if error:
        return error
    assert team is not None
    if not can(request, "advisory:publish", team):
        return 403, ErrorResponse(detail="Forbidden", error_code=ErrorCode.FORBIDDEN)

    withdrawn = advisory_service.withdraw_advisory(team, request.user, advisory_id, reason=payload.reason)
    if not withdrawn.ok:
        return _failed(withdrawn)

    return _fetched(team, advisory_id)


# --- the trust center over JSON ---------------------------------------------


def _public_workspace(request: HttpRequest, workspace_key: str) -> Team | None:
    """The workspace a trust-center reader named, or None when there is nothing to show.

    Reuses the page resolver, so a private workspace, a bad key and an
    unknown key are all the same 404 here as they are in the browser.
    """
    status, team = fetch_public_team(request, workspace_key)
    return team if status == 200 and isinstance(team, Team) else None


def _not_found(detail: str) -> tuple[int, ErrorResponse]:
    return 404, ErrorResponse(detail=detail, error_code=ErrorCode.NOT_FOUND)


def _versions(value: str) -> str:
    return "" if value == _NO_VERSIONS else value


def _public_shape(projection: dict[str, Any]) -> dict[str, Any]:
    """A trust-center projection reduced to the public contract.

    The projection is what the pages render, badge variants and relative
    dates included. The contract keeps the record and the two things a reader
    of a gated trust center is entitled to know: that products were withheld,
    and how many.
    """
    shape: dict[str, Any] = {
        "id": projection["pk"],
        "tracking_id": _tracking_id(projection),
        "title": projection["title"],
        "summary": projection.get("summary", ""),
        "severity": projection.get("severity", ""),
        "cvss_score": projection.get("cvss_score"),
        "status": projection["publication_status"],
        "remediation_status": projection["status"],
        "is_open": projection["is_open"],
        "visibility": projection["visibility"],
        "is_withdrawn": projection.get("is_withdrawn", False),
        "withdrawal_reason": projection.get("withdrawal_reason", ""),
        "products": [{"id": p.get("id"), "name": p.get("name", "")} for p in projection.get("products", [])],
        "withheld_product_count": projection.get("withheld_product_count", 0),
        "vulnerability_count": projection.get("vulnerability_count", 0),
        "cve_ids": projection.get("cve_ids", []),
        "published_at": projection.get("published_at"),
        "updated_at": projection.get("updated_at"),
    }
    if "statuses" in projection:
        shape["description"] = projection.get("description", "")
        shape["vulnerabilities"] = projection.get("vulnerabilities", [])
        shape["references"] = projection.get("references", [])
        shape["acknowledgments"] = projection.get("acknowledgments", [])
        shape["statuses"] = [
            {
                "id": row["id"],
                "vulnerability": row["vulnerability"],
                "product": row["product"],
                "product_id": row.get("product_id"),
                "status": row["status"],
                "justification": row.get("justification_value", ""),
                "impact_statement": row.get("impact_statement", ""),
                "action_statement": row.get("action_statement", ""),
                "response": row.get("response", ""),
                "recommended_version": row.get("recommended_version", ""),
                "affected": _versions(row.get("affected", "")),
                "unaffected": _versions(row.get("unaffected", "")),
                "version_ranges": row.get("version_ranges", []),
            }
            for row in projection["statuses"]
        ]
        shape["timeline"] = [
            {"id": e["id"], "kind": e["kind"], "note": e.get("note", ""), "created_at": e["created_at"]}
            for e in projection.get("timeline", [])
        ]
    return shape


@router.get(
    "/public/{workspace_key}",
    response={200: PublicAdvisoryListSchema, 404: ErrorResponse},
    auth=None,
    summary="List a workspace's public advisories",
    description=(
        "What the trust center shows this reader, as JSON. Takes the trust center's own filters: "
        "search, severity (repeatable), product (repeatable), from and to (YYYY-MM-DD), sort and page. "
        "A bearer token or session identifies the reader, which is what decides whether gated advisories appear."
    ),
)
@decorate_view(optional_token_auth)
def list_public_advisories(request: HttpRequest, workspace_key: str) -> tuple[int, Any]:
    team = _public_workspace(request, workspace_key)
    if team is None:
        return _not_found("Workspace not found")

    query = trust_center.parse_advisory_query(request.GET)
    payload = trust_center.browse_public_advisories(request, team, query).value or {}
    return 200, {
        "items": [_public_shape(row) for row in payload.get("advisories", [])],
        "pagination": {
            "total": payload.get("total", 0),
            "page": payload.get("page", 1),
            "page_size": payload.get("per_page", query.per_page),
            "total_pages": payload.get("page_count", 1),
            "has_previous": payload.get("has_prev", False),
            "has_next": payload.get("has_next", False),
        },
        "hidden_count": payload.get("hidden_count", 0),
        "viewer_is_authenticated": payload.get("viewer_is_authenticated", False),
        "viewer_has_gated_grant": payload.get("viewer_has_gated_grant", False),
    }


@router.get(
    "/public/{workspace_key}/{advisory_id}",
    response={200: PublicAdvisoryDetailSchema, 404: ErrorResponse},
    auth=None,
    summary="Get one public advisory",
    description="By tracking id or record id. An advisory this reader may not see is a 404, not a 403.",
)
@decorate_view(optional_token_auth)
def get_public_advisory(request: HttpRequest, workspace_key: str, advisory_id: str) -> tuple[int, Any]:
    team = _public_workspace(request, workspace_key)
    if team is None:
        return _not_found("Workspace not found")

    result = trust_center.get_public_advisory(request, team, advisory_id)
    if not result.ok or result.value is None:
        return _not_found("Advisory not found")
    return 200, _public_shape(result.value)


def _advisory_url(request: HttpRequest, team: Team, advisory_id: str) -> str:
    """Where a reader would find this advisory in a browser: the workspace's own domain when it has one."""
    path = f"/advisories/{quote(advisory_id, safe='')}/"
    return build_custom_domain_url(team, path, request.is_secure()) or (
        get_base_url()
        + reverse("core:advisory_details_public", kwargs={"workspace_key": team.key, "advisory_id": advisory_id})
    )


@router.get(
    "/public/{workspace_key}/{advisory_id}/csaf",
    response={200: dict[str, Any], 404: ErrorResponse},
    auth=None,
    summary="Get one public advisory as a CSAF 2.0 document",
    description="The same advisory, filtered for the same reader, in the format CSAF-aware tooling expects.",
)
@decorate_view(optional_token_auth)
def get_public_advisory_csaf(request: HttpRequest, workspace_key: str, advisory_id: str) -> tuple[int, Any]:
    team = _public_workspace(request, workspace_key)
    if team is None:
        return _not_found("Workspace not found")

    result = trust_center.get_public_advisory(request, team, advisory_id)
    if not result.ok or result.value is None:
        return _not_found("Advisory not found")

    projection = result.value
    return 200, render_csaf(
        projection,
        publisher_name=team.display_name,
        publisher_namespace=build_custom_domain_url(team, "/", request.is_secure())
        or get_base_url()
        or "https://sbomify.com",
        self_url=_advisory_url(request, team, str(projection["id"])),
        generator=get_sbomify_version(),
    )
