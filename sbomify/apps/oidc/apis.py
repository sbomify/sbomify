"""OIDC trusted-publishing API.

Two concerns, two auth postures:

* ``POST /github/exchange`` — PUBLIC (``auth=None``). A GitHub Actions
  runner presents its OIDC token in the ``Authorization: Bearer``
  header; the body names the target Component. Thin dispatch into
  ``services.exchange_github_oidc_token``.

* ``GET/POST/DELETE /github/bindings`` — AUTHENTICATED (PAT or session)
  and owner/admin-gated. Lets workspace owners manage trusted-publisher
  bindings over the API (the same operations the UI exposes), so the
  GitHub Action / wizard can register a binding during setup instead of
  the user hand-creating one in the UI. Thin dispatch into
  ``services.create_binding`` / ``delete_binding`` /
  ``list_bindings_for_component``.

Exchange status mapping (defense-in-depth — error bodies are
intentionally sparse so an attacker can't probe which check failed):

* 400 — missing body fields / malformed component_id
* 401 — invalid OIDC token (signature, issuer, audience, expiry,
  required claim missing). Same generic body for every sub-failure.
* 403 — token verified but ``(repository_owner_id, repository_id)``
  doesn't match any binding for the requested Component.
* 404 — Component doesn't exist.
* 503 — GitHub's JWKS endpoint is unreachable. Distinct from 401 so CI
  doesn't retry-loop a real config error.

Binding-management status mapping:

* 201 — binding created.
* 204 — binding deleted.
* 400 — malformed repository slug / unknown provider.
* 401 — no / invalid credential.
* 404 — Component doesn't exist OR the caller isn't an owner/admin of
  its workspace. The two are deliberately conflated so a non-member
  can't enumerate workspace inventory by status code.
* 409 — that repository is already bound to the Component.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited  # type: ignore[import-untyped]
from ninja import Router, Schema
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.authz import can
from sbomify.apps.core.models import User
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.core.utils import get_client_ip
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import (
    create_binding,
    delete_binding,
    exchange_github_oidc_token,
    list_bindings_for_component,
)
from sbomify.logging import getLogger

# Rate limit for the public, unauthenticated token-exchange endpoint.
# 60/m per IP is comfortably above the legitimate use case (CI runs
# rarely exceed 1/min for a single repo, even across all jobs in a
# workflow) while capping:
#
#   * component-id enumeration attacks (404 vs 403 vs 200 differ and
#     leak workspace inventory cheaply)
#   * JWKS amplification (each request can trigger a forced refresh
#     past the cache-level rate limit)
#   * brute-force forged-signature attempts
#
# Security finding H-2.
_EXCHANGE_RATE_LIMIT = "60/m"
_EXCHANGE_RATE_LIMIT_GROUP = "oidc:github:exchange"

logger = getLogger(__name__)


router = Router(tags=["OIDC Trusted Publishing"], auth=None)


class ExchangeRequest(Schema):
    # Optional at the schema level so a missing / empty field maps to
    # the documented 400 ("missing component_id") via the explicit
    # check in the handler, instead of Ninja's auto-generated 422 from
    # Pydantic. Keeps the public error contract consistent across all
    # body-validation failures.
    component_id: str | None = None


class ExchangeResponse(Schema):
    access_token: str
    expires_in: int
    component_id: str
    token_type: str = "Bearer"


def _bearer_token(request: HttpRequest) -> str | None:
    """Extract the bearer token from the Authorization header.

    Per RFC 7235 §2.1 the auth scheme is case-insensitive — a client
    sending ``bearer`` or ``BEARER`` should be treated the same as
    ``Bearer``. Splitting on whitespace + case-folding the scheme is
    the standard pattern.
    """
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.casefold() != "bearer":
        return None
    token = token.strip()
    return token or None


@router.post(
    "/github/exchange",
    response={
        200: ExchangeResponse,
        400: ErrorResponse,
        401: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        429: ErrorResponse,
        503: ErrorResponse,
    },
    summary="Exchange a GitHub Actions OIDC token for a short-lived sbomify token.",
)
def github_token_exchange(request: HttpRequest, payload: ExchangeRequest) -> tuple[int, Any]:
    # Rate-limit BEFORE doing any verification work — keeps the cost
    # of an enumeration attempt at the django-ratelimit cache lookup,
    # not at the JWKS / DB / JWT-decode level. Sparse 429 body for the
    # same anti-probe reason as the 401 path.
    # django-ratelimit's built-in ``key="ip"`` reads ``REMOTE_ADDR`` —
    # which is the proxy's IP, not the client's, since this app sits
    # behind a trusted Caddy reverse proxy that sets ``X-Real-IP``.
    # Pass a callable that uses the codebase's ``get_client_ip``
    # helper so the limit hits real client IPs (and matches the log
    # line below — without this, every request would log + bucket
    # against the proxy IP, making the cap effectively global).
    client_ip = get_client_ip(request) or "unknown"
    if is_ratelimited(
        request,
        group=_EXCHANGE_RATE_LIMIT_GROUP,
        key=lambda group, req: client_ip,
        rate=_EXCHANGE_RATE_LIMIT,
        increment=True,
    ):
        logger.info("OIDC exchange: rate-limited request from %s", client_ip)
        return 429, {"detail": "too many requests"}

    oidc_token = _bearer_token(request)
    if not oidc_token:
        return 400, {"detail": "missing 'Authorization: Bearer <github_oidc_jwt>' header"}

    component_id = (payload.component_id or "").strip()
    if not component_id:
        return 400, {"detail": "missing component_id"}

    result = exchange_github_oidc_token(component_id=component_id, oidc_token=oidc_token)
    if not result.ok:
        return result.status_code or 500, {"detail": result.error or "unknown error"}

    exchange = result.value
    assert exchange is not None  # ServiceResult.ok ⇒ value is set
    return 200, {
        "access_token": exchange.access_token,
        "expires_in": exchange.expires_in_seconds,
        "component_id": exchange.component_id,
        "token_type": "Bearer",  # nosec B105 — OAuth2 token_type sentinel, not a credential
    }


# ============================================================================
# Binding management — authenticated, owner/admin-gated CRUD over the same
# services the UI uses. Dual auth (PAT for the action/CI, session for the web
# UI) overrides the router-level ``auth=None`` per-route.
# ============================================================================

_BINDING_AUTH = (PersonalAccessTokenAuth(), django_auth)
_VALID_PROVIDERS = {value for value, _label in OIDCBinding.PROVIDER_CHOICES}


class BindingCreateRequest(Schema):
    # Just the repo name — identical input for public and private repos. The
    # backend resolves the immutable IDs for public repos at create time, and
    # defers to the first OIDC publish for private ones (see create_binding).
    component_id: str
    repository: str
    provider: str = OIDCBinding.PROVIDER_GITHUB


class BindingResponse(Schema):
    id: str
    component_id: str
    provider: str
    repository: str
    # Null while the binding is unpinned (private repo, awaiting first publish).
    repository_id: int | None = None
    repository_owner_id: int | None = None
    created_at: datetime
    last_used_at: datetime | None = None


def _component_for_management(request: HttpRequest, component_id: str) -> Any | None:
    """Resolve a Component the caller may manage bindings for, else ``None``.

    Returns ``None`` for BOTH "no such component" and "caller isn't an
    owner/admin of its workspace" — the caller maps either to 404 so a
    non-member can't distinguish them (anti-enumeration). Mirrors the UI's
    ``_component_or_error`` permission gate. Component import is local to
    match the service layer's circular-import avoidance.
    """
    from sbomify.apps.sboms.models import Component

    component = Component.objects.filter(pk=component_id).select_related("team").first()
    if component is None or not can(request, "component:manage", component):
        return None
    return component


@router.get(
    "/github/bindings",
    auth=_BINDING_AUTH,
    response={200: list[BindingResponse], 401: ErrorResponse, 404: ErrorResponse},
    summary="List GitHub trusted-publisher bindings for a component.",
)
def list_github_bindings(request: HttpRequest, component_id: str) -> tuple[int, Any]:
    component = _component_for_management(request, component_id)
    if component is None:
        return 404, {"detail": "component not found or insufficient permissions"}
    return 200, list_bindings_for_component(component)


@router.post(
    "/github/bindings",
    auth=_BINDING_AUTH,
    response={
        201: BindingResponse,
        400: ErrorResponse,
        401: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
    summary="Create a GitHub trusted-publisher binding for a component.",
)
def create_github_binding(request: HttpRequest, payload: BindingCreateRequest) -> tuple[int, Any]:
    provider = payload.provider or OIDCBinding.PROVIDER_GITHUB
    if provider not in _VALID_PROVIDERS:
        return 400, {"detail": f"unsupported provider '{provider}'"}

    component = _component_for_management(request, payload.component_id)
    if component is None:
        return 404, {"detail": "component not found or insufficient permissions"}

    result = create_binding(
        component=component,
        provider=provider,
        repository_slug=payload.repository,
        requested_by=cast(User, request.user),
    )
    if not result.ok:
        return result.status_code or 500, {"detail": result.error or "failed to create binding"}
    return 201, result.value


@router.delete(
    "/github/bindings/{binding_id}",
    auth=_BINDING_AUTH,
    response={204: None, 401: ErrorResponse, 404: ErrorResponse},
    summary="Delete a GitHub trusted-publisher binding.",
)
def delete_github_binding(request: HttpRequest, binding_id: str, component_id: str) -> tuple[int, Any]:
    component = _component_for_management(request, component_id)
    if component is None:
        return 404, {"detail": "component not found or insufficient permissions"}

    result = delete_binding(component=component, binding_id=binding_id)
    if not result.ok:
        return result.status_code or 404, {"detail": result.error or "trusted publisher not found"}
    return 204, None
