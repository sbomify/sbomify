"""OIDC token verification helpers.

Currently implements verification against GitHub Actions
(``token.actions.githubusercontent.com``). The shape is generic enough
that a future ``provider`` argument can swap issuer/JWKS URL/audience.

Verification strategy mirrors PyPI Trusted Publishers:

1. Decode the JWT header to extract ``kid``.
2. Fetch GitHub's JWKS (cached in Django cache for
   ``OIDC_JWKS_CACHE_SECONDS``) and pick the key whose ``kid`` matches.
3. Hand the token + key to PyJWT for full verification — signature,
   ``iss``, ``aud``, ``exp``, ``iat`` are all checked.
4. Return the verified claims dict.

Each failure mode raises a typed subclass of ``OIDCVerificationError``
so the API layer can map them to 401/403 cleanly without leaking
internal verification detail to the response.
"""

from __future__ import annotations

from typing import Any, cast

import jwt
import requests
from django.conf import settings
from django.core.cache import cache

from sbomify.logging import getLogger

logger = getLogger(__name__)

_JWKS_CACHE_KEY = "oidc:github:jwks"
_JWKS_FETCH_TIMEOUT_SECONDS = 5


class OIDCVerificationError(Exception):
    """Base class for OIDC verification failures."""


class OIDCInvalidSignature(OIDCVerificationError):
    """The token's signature could not be verified against the issuer's JWKS."""


class OIDCInvalidIssuer(OIDCVerificationError):
    """The token's ``iss`` claim does not match the expected issuer."""


class OIDCInvalidAudience(OIDCVerificationError):
    """The token's ``aud`` claim does not match the configured audience."""


class OIDCExpiredToken(OIDCVerificationError):
    """The token's ``exp`` claim is in the past."""


class OIDCJWKSUnavailable(OIDCVerificationError):
    """The issuer's JWKS endpoint could not be reached."""


def _fetch_github_jwks() -> dict[str, Any]:
    """Fetch GitHub's JWKS document, with a short-TTL Django cache.

    JWKS rotation is infrequent (key rotation is a planned event) and
    every workflow run does an exchange, so a 1h cache is a good
    balance between freshness and pressure on GitHub.
    """
    cached = cache.get(_JWKS_CACHE_KEY)
    if cached is not None:
        return cast(dict[str, Any], cached)

    url = settings.OIDC_GITHUB_JWKS_URL
    try:
        response = requests.get(url, timeout=_JWKS_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        jwks: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        logger.warning("GitHub JWKS fetch failed (%s): %s", url, exc)
        raise OIDCJWKSUnavailable(str(exc)) from exc

    cache.set(_JWKS_CACHE_KEY, jwks, timeout=settings.OIDC_JWKS_CACHE_SECONDS)
    return jwks


def _signing_key_for_kid(token: str) -> Any:
    """Locate the JWK signing key for the token's ``kid`` header.

    Uses ``PyJWKClient`` so we don't have to hand-build the RSA key
    from its JWK params — it knows the JWK → PyCryptodome conversion
    and caches keys per ``kid``. We seed it with our own cached JWKS
    dict to avoid PyJWKClient doing its own (uncached) HTTP fetch.
    """
    jwks = _fetch_github_jwks()
    # Build a one-off JWKClient seeded with the JWKS we just fetched.
    # PyJWKClient normally takes a URL; we override its internal data
    # path by injecting the key set directly via from_jwk for the
    # matching kid.
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise OIDCInvalidSignature("token header missing 'kid'")

    matching = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not matching:
        # Force a refresh — the signing key may have rotated since the
        # cache was warmed. One retry is enough; a second miss after
        # refresh means the token really is signed by a key we don't
        # know about (likely forged or from a different issuer).
        cache.delete(_JWKS_CACHE_KEY)
        jwks = _fetch_github_jwks()
        matching = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not matching:
        raise OIDCInvalidSignature(f"no JWK matches token kid={kid!r}")

    return jwt.PyJWK(matching).key


def verify_github_oidc_token(token: str) -> dict[str, Any]:
    """Fully verify a GitHub Actions OIDC token and return its claims.

    Verifies (PyJWT does all four atomically):
    * RS256 signature against GitHub's JWKS
    * ``iss`` == ``settings.OIDC_GITHUB_ISSUER``
    * ``aud`` == ``settings.OIDC_GITHUB_AUDIENCE``
    * ``exp`` is in the future (with PyJWT's default leeway)
    * ``iat`` is in the past

    Raises ``OIDCVerificationError`` (or a subclass) on any failure.
    The API layer should treat any subclass as 401.
    """
    try:
        key = _signing_key_for_kid(token)
    except OIDCVerificationError:
        raise
    except Exception as exc:
        # PyJWK parse / unverified-header decode can blow up on a
        # truly malformed token before we even reach signature
        # verification. Treat as invalid signature.
        raise OIDCInvalidSignature(f"token header could not be parsed: {exc}") from exc

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            issuer=settings.OIDC_GITHUB_ISSUER,
            audience=settings.OIDC_GITHUB_AUDIENCE,
            options={"require": ["iss", "aud", "exp", "iat", "sub"]},
        )
    except jwt.InvalidIssuerError as exc:
        raise OIDCInvalidIssuer(str(exc)) from exc
    except jwt.InvalidAudienceError as exc:
        raise OIDCInvalidAudience(str(exc)) from exc
    except jwt.ExpiredSignatureError as exc:
        raise OIDCExpiredToken(str(exc)) from exc
    except jwt.InvalidTokenError as exc:
        # Catch-all for signature mismatch, missing required claim,
        # bad algorithm, etc. Mapped to "invalid signature" externally
        # so we don't accidentally leak which check failed.
        raise OIDCInvalidSignature(str(exc)) from exc

    return claims
