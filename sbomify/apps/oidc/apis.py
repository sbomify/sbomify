"""OIDC token-exchange API.

Single endpoint: ``POST /api/v1/auth/oidc/github/exchange``.

A GitHub Actions runner presents its OIDC token in the
``Authorization: Bearer`` header; the body names the target Component.
We verify the OIDC token's signature + claims (via
``utils.verify_github_oidc_token``), match the immutable
``repository_owner_id`` / ``repository_id`` claims against an
``OIDCBinding`` for that Component, mint a short-lived
``AccessToken`` row owned by the binding's bot user, and hand back
the token + TTL.

Status code mapping (defense-in-depth — error bodies are intentionally
sparse so an attacker can't probe which check failed):

* 400 — missing body fields / malformed component_id
* 401 — invalid OIDC token (signature, issuer, audience, expiry,
  required claim missing). PyJWT verifies signature BEFORE claims,
  so a forged token can't probe per-claim checks.
* 403 — token verified but ``(repository_owner_id, repository_id)``
  doesn't match any binding for the requested Component.
* 404 — Component doesn't exist.
* 503 — GitHub's JWKS endpoint is unreachable. Distinct from 401 so
  CI doesn't retry-loop a real config error and so we don't conflate
  "your token is bad" with "our infra is down".
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.utils import (
    OIDCExpiredToken,
    OIDCInvalidAudience,
    OIDCInvalidIssuer,
    OIDCInvalidSignature,
    OIDCJWKSUnavailable,
    OIDCVerificationError,
    verify_github_oidc_token,
)
from sbomify.apps.sboms.models import Component
from sbomify.logging import getLogger

logger = getLogger(__name__)


router = Router(tags=["OIDC Trusted Publishing"], auth=None)


class ExchangeRequest(Schema):
    component_id: str


class ExchangeResponse(Schema):
    access_token: str
    expires_in: int
    component_id: str


def _bearer_token(request: HttpRequest) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.removeprefix("Bearer ").strip()
    return token or None


@router.post(
    "/github/exchange",
    response={
        200: ExchangeResponse,
        400: ErrorResponse,
        401: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        503: ErrorResponse,
    },
    summary="Exchange a GitHub Actions OIDC token for a short-lived sbomify token.",
)
def github_token_exchange(request: HttpRequest, payload: ExchangeRequest) -> tuple[int, Any]:
    oidc_token = _bearer_token(request)
    if not oidc_token:
        return 400, {"detail": "missing 'Authorization: Bearer <github_oidc_jwt>' header"}

    component_id = (payload.component_id or "").strip()
    if not component_id:
        return 400, {"detail": "missing component_id"}

    # 1. Look up the Component first — gives the most user-friendly
    # 404 ("you typed a bad ID") before we burn a JWKS round-trip.
    # The binding lookup below re-selects via FK, so we don't need to
    # hold the instance here.
    if not Component.objects.filter(pk=component_id).exists():
        return 404, {"detail": "component not found"}

    # 2. Verify the OIDC token. Failures map to the appropriate
    # status — careful not to leak which sub-check failed (an attacker
    # could otherwise probe iss vs aud vs signature independently).
    try:
        claims = verify_github_oidc_token(oidc_token)
    except OIDCJWKSUnavailable as exc:
        logger.warning("OIDC exchange: GitHub JWKS unavailable: %s", exc)
        return 503, {"detail": "OIDC verification temporarily unavailable"}
    except (OIDCInvalidSignature, OIDCInvalidIssuer, OIDCInvalidAudience, OIDCExpiredToken) as exc:
        # Same 401 + sparse body for all token-validity failures.
        logger.info("OIDC exchange: token rejected (%s): %s", type(exc).__name__, exc)
        return 401, {"detail": "invalid OIDC token"}
    except OIDCVerificationError as exc:
        # Defensive — should never hit; covers future subclass additions.
        logger.warning("OIDC exchange: unexpected verification error: %s", exc)
        return 401, {"detail": "invalid OIDC token"}

    # 3. Match the claim against a binding. We MUST match on the
    # immutable IDs (repository_owner_id + repository_id) — never on
    # the mutable repository name — see OIDCBinding docstring for
    # the account-resurrection rationale.
    repository_owner_id = claims.get("repository_owner_id")
    repository_id = claims.get("repository_id")
    if not isinstance(repository_owner_id, int) or not isinstance(repository_id, int):
        return 401, {"detail": "invalid OIDC token"}

    try:
        binding = OIDCBinding.objects.select_related("bot_user", "component__team").get(
            component_id=component_id,
            provider=OIDCBinding.PROVIDER_GITHUB,
            repository_owner_id=repository_owner_id,
            repository_id=repository_id,
        )
    except OIDCBinding.DoesNotExist:
        # The token is valid but its repository is not bound to this
        # component. 403, not 401, so the caller knows the token
        # itself was fine — they need to fix the binding config.
        logger.info(
            "OIDC exchange: no binding for component=%s owner_id=%s repo_id=%s repository=%s",
            component_id,
            repository_owner_id,
            repository_id,
            claims.get("repository"),
        )
        return 403, {"detail": "repository not bound to this component"}

    # 4. Mint a short-lived AccessToken row owned by the binding's bot
    # user. The JWT itself is the same shape as a PAT (so it auths
    # through the existing PersonalAccessTokenAuth path) — what
    # makes it short-lived is the ``expires_at`` column the auth
    # path will check in OIDC-5.
    ttl_seconds = int(getattr(settings, "OIDC_TOKEN_TTL_SECONDS", 900))
    now = timezone.now()
    expires_at = now + timedelta(seconds=ttl_seconds)

    sbomify_jwt = create_personal_access_token(binding.bot_user)
    with transaction.atomic():
        AccessToken.objects.create(
            encoded_token=sbomify_jwt,
            description=f"oidc:github:{binding.id}",
            user=binding.bot_user,
            team=binding.component.team,
            expires_at=expires_at,
        )
        # Update last_used_at out-of-band of the create so a refused
        # token (caught earlier) doesn't bump the timestamp.
        OIDCBinding.objects.filter(pk=binding.pk).update(last_used_at=now)

    logger.info(
        "OIDC exchange: issued token for binding=%s component=%s repo=%s ttl=%ds",
        binding.id,
        component_id,
        claims.get("repository"),
        ttl_seconds,
    )
    return 200, {
        "access_token": sbomify_jwt,
        "expires_in": ttl_seconds,
        "component_id": component_id,
    }
