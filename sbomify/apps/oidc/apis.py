"""OIDC token-exchange API.

Single endpoint: ``POST /api/v1/auth/oidc/github/exchange``.

A GitHub Actions runner presents its OIDC token in the
``Authorization: Bearer`` header; the body names the target Component.
The endpoint is a thin dispatch into
``services.exchange_github_oidc_token`` which owns every ORM call and
the verification logic.

Status code mapping (defense-in-depth — error bodies are intentionally
sparse so an attacker can't probe which check failed):

* 400 — missing body fields / malformed component_id
* 401 — invalid OIDC token (signature, issuer, audience, expiry,
  required claim missing). Same generic body for every sub-failure.
* 403 — token verified but ``(repository_owner_id, repository_id)``
  doesn't match any binding for the requested Component.
* 404 — Component doesn't exist.
* 503 — GitHub's JWKS endpoint is unreachable. Distinct from 401 so CI
  doesn't retry-loop a real config error.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited  # type: ignore[import-untyped]
from ninja import Router, Schema

from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.oidc.services import exchange_github_oidc_token
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
    component_id: str


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
    if is_ratelimited(
        request,
        group=_EXCHANGE_RATE_LIMIT_GROUP,
        key="ip",
        rate=_EXCHANGE_RATE_LIMIT,
        increment=True,
    ):
        logger.info("OIDC exchange: rate-limited request from %s", request.META.get("REMOTE_ADDR", "?"))
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
