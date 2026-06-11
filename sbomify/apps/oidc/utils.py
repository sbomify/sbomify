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

# Namespaced cache key so the JWKS dict can't collide with anything else
# that touches the shared Django cache. Defense against cache-poisoning:
# an attacker who can write to ``cache.set(user_input, ...)`` elsewhere
# in the codebase still can't overwrite this slot without knowing the
# full namespaced key.
_JWKS_CACHE_KEY = "sbomify:trusted:oidc:github:jwks"
_JWKS_REFRESH_MARKER_KEY = "sbomify:trusted:oidc:github:jwks:last_refresh"
_JWKS_FETCH_TIMEOUT_SECONDS = 5

# Minimum gap between forced JWKS refreshes triggered by a ``kid`` miss.
# Without this, an unauthenticated attacker spamming the exchange
# endpoint with novel ``kid`` headers could DoS-amplify into GitHub's
# JWKS endpoint (and indirectly into our own legitimate traffic when
# GitHub starts rate-limiting us). 30 s is enough that legitimate
# rotations resolve within one minute while attack amplification is
# capped at 2 fetches/min across the entire deployment — the marker
# lives in Django's cache (typically Redis), so it's shared across
# every process and replica that hit the same cache namespace, not
# per-process.
_JWKS_FORCED_REFRESH_MIN_GAP_SECONDS = 30

# Defensive structural validation of cached JWKS entries. The JWKS dict
# is loaded from cache and handed to PyJWK without integrity checks
# otherwise — if an attacker poisons the cache (lateral move into
# Redis, future cache.set() bug elsewhere), they could plant a forged
# RSA public key whose private half they hold and mint signatures we
# accept. Validating before trust closes that gap.
_JWKS_REQUIRED_FIELDS = {"kty", "kid", "n", "e"}
_JWKS_MIN_MODULUS_BITS = 2048  # RFC 7518 + GitHub's own minimum


def _is_valid_signing_jwk(jwk: dict[str, Any]) -> bool:
    """Return True iff ``jwk`` looks like a usable RSA signing key."""
    if not isinstance(jwk, dict):
        return False
    if not _JWKS_REQUIRED_FIELDS.issubset(jwk):
        return False
    if jwk.get("kty") != "RSA":
        return False
    # ``use`` and ``alg`` are optional in the spec but GitHub always sets
    # them; reject anything that's set to a non-signing value.
    if jwk.get("use") not in (None, "sig"):
        return False
    if jwk.get("alg") not in (None, "RS256"):
        return False
    # Modulus ``n`` is base64url-encoded; rough length-to-bits check.
    n = jwk.get("n", "")
    if not isinstance(n, str):
        return False
    # base64url with no padding: 4 chars → 3 bytes → 24 bits.
    approx_bits = (len(n) * 24) // 4
    if approx_bits < _JWKS_MIN_MODULUS_BITS:
        return False
    return True


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


_ALLOWED_JWKS_HOSTS = frozenset({"token.actions.githubusercontent.com"})


def _is_safe_jwks_url(url: str) -> bool:
    """Reject any JWKS URL that's not HTTPS to a known GitHub host.

    SSRF defense: if ``OIDC_GITHUB_JWKS_URL`` env var is ever
    compromised, an attacker could point it at an internal metadata
    service. Allow-list pinning blocks that. Combined with
    ``allow_redirects=False`` in the fetch itself, the host can't be
    swapped at runtime either.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    return parsed.hostname in _ALLOWED_JWKS_HOSTS


def _fetch_github_jwks() -> dict[str, Any]:
    """Fetch GitHub's JWKS document, with a short-TTL Django cache.

    JWKS rotation is infrequent (key rotation is a planned event) and
    every workflow run does an exchange, so a 1h cache is a good
    balance between freshness and pressure on GitHub.

    Defensive validation: cached entries are re-validated on read AND
    on write (every ``keys[]`` member must look like a valid RSA
    signing JWK). A poisoned cache slot fails validation and we
    refetch — closes the gap an attacker could otherwise use to plant
    a forged key.

    SSRF guard: the URL must be HTTPS to a known GitHub host
    (``_ALLOWED_JWKS_HOSTS``). Combined with ``allow_redirects=False``
    on the actual request, this prevents a compromised settings file
    or env from pivoting the fetch at an internal address.
    """
    cached = cache.get(_JWKS_CACHE_KEY)
    if cached is not None and _jwks_passes_validation(cached):
        return cast(dict[str, Any], cached)
    if cached is not None:
        # Reached only if a poisoned / malformed entry was returned.
        logger.warning("Discarding invalid cached JWKS entry; refetching")
        cache.delete(_JWKS_CACHE_KEY)

    url = settings.OIDC_GITHUB_JWKS_URL
    if not _is_safe_jwks_url(url):
        logger.error("Refusing to fetch JWKS from unsafe URL: %s", url)
        raise OIDCJWKSUnavailable("JWKS URL not allow-listed")

    try:
        response = requests.get(url, timeout=_JWKS_FETCH_TIMEOUT_SECONDS, allow_redirects=False)
        response.raise_for_status()
        jwks: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        logger.warning("GitHub JWKS fetch failed (%s): %s", url, exc)
        raise OIDCJWKSUnavailable(str(exc)) from exc
    except ValueError as exc:
        # ``response.json()`` raises ``ValueError`` (the parent of
        # ``json.JSONDecodeError``) on malformed upstream bodies. Without
        # this branch the exception bubbles up as an unhandled 500; with it
        # the exchange endpoint maps cleanly to 503 like every other JWKS
        # unavailability mode.
        logger.warning("GitHub JWKS response was not valid JSON (%s): %s", url, exc)
        raise OIDCJWKSUnavailable(f"upstream JWKS not parseable: {exc}") from exc

    if not _jwks_passes_validation(jwks):
        # Upstream returned something we don't recognise; better to fail
        # the request than to cache a degraded document for an hour.
        logger.warning("GitHub JWKS response failed structural validation; not caching")
        raise OIDCJWKSUnavailable("upstream JWKS failed validation")

    cache.set(_JWKS_CACHE_KEY, jwks, timeout=settings.OIDC_JWKS_CACHE_SECONDS)
    return jwks


def _jwks_passes_validation(jwks: Any) -> bool:
    if not isinstance(jwks, dict):
        return False
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        return False
    return all(_is_valid_signing_jwk(k) for k in keys)


def _signing_key_for_kid(token: str) -> Any:
    """Locate the JWK signing key for the token's ``kid`` header.

    Walks our cached JWKS dict, finds the entry whose ``kid`` matches
    the token's header, and constructs the RSA key via ``jwt.PyJWK``.
    On a cache miss, we invalidate-and-refetch ONCE (rate-limited by
    ``_JWKS_REFRESH_MARKER_KEY``) — a second miss after refresh raises
    ``OIDCInvalidSignature("no JWK matches")``.

    We deliberately don't use ``PyJWKClient`` here: it owns its own
    HTTP fetch and would bypass our validation + rate-limit + SSRF
    guards. The manual match is simpler given those constraints.
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
        # cache was warmed. The refresh is rate-limited by a separate
        # marker key (in Django's cache, typically Redis — so the
        # ceiling is one forced fetch per
        # ``_JWKS_FORCED_REFRESH_MIN_GAP_SECONDS`` across the entire
        # deployment that shares the cache namespace, not per process)
        # so an attacker spamming novel ``kid`` headers can't amplify
        # into GitHub's JWKS endpoint or our own latency budget.
        last_refresh_marker = cache.get(_JWKS_REFRESH_MARKER_KEY)
        if last_refresh_marker is None:
            cache.set(_JWKS_REFRESH_MARKER_KEY, True, timeout=_JWKS_FORCED_REFRESH_MIN_GAP_SECONDS)
            cache.delete(_JWKS_CACHE_KEY)
            jwks = _fetch_github_jwks()
            matching = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not matching:
        raise OIDCInvalidSignature(f"no JWK matches token kid={kid!r}")

    return jwt.PyJWK(matching).key


def verify_github_oidc_token(token: str) -> dict[str, Any]:
    """Fully verify a GitHub Actions OIDC token and return its claims.

    Verifies (PyJWT does all atomically):
    * RS256 signature against GitHub's JWKS
    * ``iss`` == ``settings.OIDC_GITHUB_ISSUER``
    * ``aud`` == ``settings.OIDC_GITHUB_AUDIENCE``
    * ``exp`` is in the future, ``iat``/``nbf`` are not in the future
      (``verify_iat=True``) — each tolerant of up to
      ``settings.OIDC_GITHUB_LEEWAY_SECONDS`` of clock skew, applied
      symmetrically. GitHub's issuer clock often runs a few seconds ahead
      of ours, so a fresh token's ``iat``/``nbf`` is slightly in the future
      at verification time; with zero leeway PyJWT would reject it as "not
      yet valid" and every exchange would 401.
    * required claims present: ``iss``, ``aud``, ``exp``, ``iat``,
      ``sub``

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
            leeway=settings.OIDC_GITHUB_LEEWAY_SECONDS,
            options={
                # PyJWT's ``require`` ONLY enforces claim presence —
                # the corresponding ``verify_*`` options control
                # semantic validation. Both layers needed.
                "require": ["iss", "aud", "exp", "iat", "sub"],
                "verify_iat": True,
            },
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
