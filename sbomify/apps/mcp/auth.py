"""Bearer personal-access-token authentication for the MCP server.

The MCP server is a Starlette ASGI app mounted alongside Django (see
``sbomify/asgi.py``), so it never passes through Django's middleware or ninja's
``PersonalAccessTokenAuth``. This module bridges the gap: it resolves the bearer
token with the same low-level helper ninja's auth uses
(``get_user_and_token_record``) and then builds a stub ``HttpRequest`` carrying
``user``, ``access_token_record`` and ``token_team``.

That stub is the whole point. ``can()`` reads ``access_token_record`` to enforce
the token's action scopes *before* the role check
(``sbomify/apps/core/authz.py``), and ``verify_item_access`` reads ``user`` and
``token_team`` for workspace scoping. Handing it a faithful stub means MCP tools
get byte-identical authorization to the REST API without a second permission
model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from mcp.server.fastmcp.exceptions import ToolError

from sbomify.apps.access_tokens.throttling import AccessTokenHeavyRateThrottle, AccessTokenRateThrottle
from sbomify.apps.access_tokens.utils import get_user_and_token_record
from sbomify.apps.core.utils import get_client_ip

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from starlette.requests import Request

    from sbomify.apps.access_tokens.models import AccessToken


class MCPAuthError(ToolError):
    """Raised when the caller presents no token, or a bad/expired one.

    Subclasses ``ToolError`` so FastMCP surfaces it to the agent as a tool error
    with our message intact, rather than an opaque 500.
    """


# Reused across requests. ``SimpleRateThrottle`` keys its sliding window on the
# token pk via ``get_cache_key``, so a shared instance is safe; the same pattern
# is used for the NinjaAPI-level throttle in ``sbomify/apis.py``.
_throttle = AccessTokenRateThrottle()
_write_throttle = AccessTokenHeavyRateThrottle()


@dataclass(frozen=True)
class Principal:
    """An authenticated MCP caller.

    ``request`` is the stub ``HttpRequest`` to pass to ``can()`` — it is not a
    real request and must never be used for rendering or redirects.
    """

    user: AbstractBaseUser
    token: AccessToken
    request: HttpRequest

    @property
    def scopes(self) -> list[str] | None:
        """The token's action scopes; ``None`` means unscoped (full capability)."""
        return self.token.scopes


def _bearer_token(request: Request) -> str:
    """Extract the bearer token, or raise ``MCPAuthError``.

    The auth scheme is case-insensitive per RFC 7235, matching
    ``access_tokens.auth._reject_invalid_bearer`` so a lowercased scheme cannot
    slip past a check that the REST API would have applied.
    """
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not raw.strip():
        raise MCPAuthError(
            "Missing bearer token. Configure this MCP server with an sbomify "
            "personal access token: Authorization: Bearer <token>."
        )
    return raw.strip()


def _stub_request(starlette_request: Request) -> HttpRequest:
    """A Django ``HttpRequest`` carrying just enough for ``can()`` to decide.

    Mirrors ``authz._stub_request_for_user`` (empty session, so nothing is
    granted by session state) but additionally populates ``META`` from the real
    connection. That lets ``get_client_ip`` apply its trusted-proxy rules
    unchanged, so audit records and IP-derived logic see the true client IP
    rather than Caddy's.
    """
    stub = HttpRequest()
    stub.user = AnonymousUser()
    stub.session = {}  # type: ignore[assignment]
    stub.method = "POST"
    stub.path = starlette_request.url.path
    # A real request always has a readable body. Django's ``HttpRequest.body``
    # reads ``_body`` if set and otherwise consumes ``_stream``, which a bare
    # HttpRequest() does not have — so any view that so much as logs
    # ``request.body`` (``core.apis.patch_component_metadata`` does, in an
    # eagerly-evaluated f-string) raises AttributeError. Seed it here so every
    # delegating tool is safe; ``publish._with_body`` overwrites it with the
    # artifact it is uploading.
    stub._body = b""

    client = starlette_request.client
    if client is not None:
        stub.META["REMOTE_ADDR"] = client.host
    for header in ("x-real-ip", "x-forwarded-for"):
        if (value := starlette_request.headers.get(header)) is not None:
            stub.META[f"HTTP_{header.upper().replace('-', '_')}"] = value

    return stub


async def authenticate(starlette_request: Request, *, attempted_action: str) -> Principal:
    """Resolve the bearer token into a ``Principal``.

    ``attempted_action`` is recorded on the token-auth audit event so a rejected
    MCP call is attributable to the tool that made it.

    Raises ``MCPAuthError`` when the token is absent, invalid, expired, or over
    its rate limit.
    """
    token = _bearer_token(starlette_request)
    stub = _stub_request(starlette_request)

    user, record = await sync_to_async(get_user_and_token_record)(
        token,
        source_ip=get_client_ip(stub),
        attempted_action=f"mcp {attempted_action}",
    )
    if user is None or record is None:
        raise MCPAuthError("Invalid or expired access token.")

    stub.user = user  # type: ignore[assignment]
    setattr(stub, "access_token_record", record)
    setattr(stub, "token_team", record.team)

    # The MCP app bypasses NinjaAPI, so its global throttle never runs here.
    # Re-apply it against the same sliding window: an agent and a CI job using
    # the same token share one budget, which is what an operator would expect.
    if not await sync_to_async(_throttle.allow_request)(stub):
        raise MCPAuthError("Rate limit exceeded for this access token. Retry shortly.")

    return Principal(user=user, token=record, request=stub)


async def throttle_write(principal: Principal, *, tool: str) -> None:
    """Apply the stricter write budget, on top of the global per-token one.

    Mirrors the REST API, where artifact uploads carry
    ``AccessTokenHeavyRateThrottle`` alongside the global throttle. The separate
    ``cache_key_prefix`` keeps the two sliding windows independent, so they do
    not double-count each other.
    """
    if not await sync_to_async(_write_throttle.allow_request)(principal.request):
        raise MCPAuthError(f"Write rate limit exceeded for this access token ({tool}). Retry shortly.")


def require(principal: Principal, action: str, resource: Any) -> None:
    """Authorize ``action`` on ``resource``, or raise ``MCPAuthError``.

    Thin wrapper over ``can()`` that turns a denial into an agent-legible error.
    The denial reason is included so an agent holding an under-scoped token is
    told to widen the token rather than retrying the same call.
    """
    from sbomify.apps.core.authz import can

    decision = can(principal.request, action, resource)
    if not decision:
        raise MCPAuthError(f"Not permitted ({action}): {decision.reason}")
