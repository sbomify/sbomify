"""OAuth for the MCP endpoint: Keycloak issues the token, ``/mcp`` checks it.

Keycloak already owns identity here, and it implements everything an MCP
client needs from an authorization server: discovery, dynamic client
registration and the authorization-code flow with PKCE. So sbomify is only the
resource server. It publishes RFC 9728 metadata naming the realm, answers a
request without a usable token with a 401 that points at that metadata, and
verifies the access token the client comes back with.

A token is accepted when the realm signed it, it has not expired, and its
``aud`` names this server's ``/mcp`` URL. The audience comes from the realm's
``mcp`` client scope, so a token issued to any other client of the realm,
such as the one the web app signs in with, is refused. Keycloak does not
support the RFC 8707 ``resource`` parameter yet, and the audience mapper is
its documented way to bind a token to one resource meanwhile.

The token's ``sub`` is the Keycloak user id, which django-allauth stores as the
``SocialAccount`` uid when that person signs in to sbomify, so a token resolves
to the same user the browser does. Someone who has never signed in to sbomify
has no user to resolve to and is refused.

An OAuth session acts with the read-only preset. It can read everything the
person's role lets them read and write nothing. Writes still need a personal
access token, whose scopes the person chose when making it.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import jwt
from django.conf import settings

from sbomify.logging import getLogger

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

logger = getLogger(__name__)

#: The Keycloak client scope an MCP client asks for. It carries the audience mapper.
SCOPE = "mcp"

#: Where RFC 9728 metadata for ``/mcp`` lives: the well-known prefix, then the resource's path.
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"

#: How long a fetched signing key set is reused before Keycloak is asked again.
_JWKS_LIFESPAN_SECONDS = 300
_JWKS_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class OAuthCredential:
    """What ``request.access_token_record`` carries for an OAuth caller.

    The contract the auth module documents: ``scopes`` for ``can()`` and
    ``pk`` for the rate-limit window. There is no row, so nothing else.
    """

    pk: str
    scopes: list[str]


def issuer() -> str:
    """The realm's issuer, as Keycloak writes it into the tokens it signs."""
    return f"{settings.KEYCLOAK_PUBLIC_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}"


def resource() -> str:
    """This server's MCP URL, which a token's ``aud`` must name."""
    return f"{settings.APP_BASE_URL.rstrip('/')}/mcp"


def metadata_url() -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}{METADATA_PATH}"


def protected_resource_metadata() -> dict[str, Any]:
    """The RFC 9728 document a client reads to find out where to sign in."""
    return {
        "resource": resource(),
        "authorization_servers": [issuer()],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "sbomify",
    }


def www_authenticate(*, invalid: bool) -> str:
    """The challenge on a 401, pointing the client at the metadata."""
    challenge = f'Bearer resource_metadata="{metadata_url()}", scope="{SCOPE}"'
    return f'{challenge}, error="invalid_token"' if invalid else challenge


def is_keycloak_token(token: str) -> bool:
    """Whether ``token`` claims to come from the realm, before anything about it is trusted.

    Only routes the token: a personal access token is a JWT too, signed by
    sbomify, and naming another issuer sends it down the PAT path.
    ``verify`` checks the claim properly.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    return claims.get("iss") == issuer()


@functools.cache
def _jwks_client() -> jwt.PyJWKClient:
    url = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
    return jwt.PyJWKClient(url, lifespan=_JWKS_LIFESPAN_SECONDS, timeout=_JWKS_TIMEOUT_SECONDS)


def verify(token: str) -> dict[str, Any] | None:
    """The token's claims when the realm signed it for this server, else ``None``."""
    try:
        key = _jwks_client().get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=resource(),
            issuer=issuer(),
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWKClientError:
        logger.warning("[MCP] Could not read Keycloak's signing keys", exc_info=True)
        return None
    except jwt.PyJWTError as exc:
        logger.info("[MCP] Refused an OAuth token: %s", exc)
        return None
    return claims


def resolve(token: str) -> tuple[AbstractBaseUser, OAuthCredential] | tuple[None, None]:
    """The sbomify user an OAuth token speaks for, and the credential to record, or ``(None, None)``."""
    from allauth.socialaccount.models import SocialAccount

    from sbomify.apps.core.authz import SCOPE_PRESETS

    claims = verify(token)
    if claims is None:
        return None, None
    account = SocialAccount.objects.filter(provider="keycloak", uid=claims["sub"]).select_related("user").first()
    if account is None or not account.user.is_active:
        return None, None
    return account.user, OAuthCredential(pk=f"oauth:{claims['sub']}", scopes=list(SCOPE_PRESETS["read_only"] or []))
