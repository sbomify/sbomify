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

A personal access token is not the only credential this endpoint will ever
accept: OAuth is the next one (#1235). Two contracts carry that, and both are
satisfied by a PAT today rather than being speculative shapes:

``Principal`` holds what the server needs about a caller — a workspace, action
scopes, and an id to throttle and audit under — instead of an ``AccessToken``
row. It does not keep the row at all, so there is nothing for a credential
without one to leave empty and nothing to disagree with the fields.

``request.access_token_record`` is the one still tied to a row, because
``can()``, the rate throttle and the upload path read it directly rather than
through the ``Principal``. What they need of it:

* ``.scopes`` — action strings, or ``None`` for unscoped. Read by ``can()``.
* ``.pk`` — stable per credential; what the rate-limit window keys on.

Those two, and no more. ``oidc.permissions.request_is_oidc_authed`` also reads
``.encoded_token`` and ``.user_id``, and it runs on the component-scoped upload
endpoints ``upload_artifact`` and ``create_release`` delegate into, to decide
whether the caller is a Trusted Publishing bot confined to its bound component.
It reads both defensively: a credential carrying neither is not a bot, which is
the answer that predicate exists to give, and the call falls through to the
ordinary ``can()`` path rather than raising.

``token_team`` on the stub is ours rather than the row's contract. It is the
workspace the credential is scoped to, the same value ``Principal.workspace``
holds, and a credential with no row fills both from wherever it knows its
workspace from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from mcp.server.fastmcp.exceptions import ToolError

from sbomify.apps.access_tokens.throttling import (
    AccessTokenHeavyRateThrottle,
    AccessTokenRateThrottle,
    AnonymousIPRateThrottle,
)
from sbomify.apps.access_tokens.utils import get_user_and_token_record
from sbomify.apps.core.utils import get_client_ip

from .limits import audit

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from starlette.requests import Request

    from sbomify.apps.teams.models import Team


class MCPAuthError(ToolError):
    """Raised when the caller presents no token, or a bad/expired one.

    Subclasses ``ToolError`` so FastMCP surfaces it to the agent as a tool error
    with our message intact, rather than an opaque 500.
    """


class MCPRateLimitedError(MCPAuthError):
    """Raised when a *valid* token is over its rate limit.

    Distinct from a credential failure so ``tools/list`` can tell the two
    apart: a bad token means advertise nothing, but a throttled one must get
    an error it can retry — an empty catalogue would be cached by the client
    as "this server has no tools".
    """


WORKSPACE_ATTR = "mcp_workspace"
"""Where ``resolve_workspace`` caches the workspace it resolved for this call.

On the stub request, alongside ``access_token_record`` and ``token_team``,
because that object is built fresh per call and thrown away after it."""


@dataclass(frozen=True)
class Principal:
    """An authenticated MCP caller, however it authenticated.

    ``request`` is the stub ``HttpRequest`` to pass to ``can()`` — it is not a
    real request and must never be used for rendering or redirects.

    The facts below are what the rest of the server actually needs: a workspace
    to scope to, action scopes to narrow by, and an identity to throttle and
    audit under. They are held here rather than reached for through an
    ``AccessToken`` row because a personal access token is not the only
    credential this endpoint will ever accept, and the four consumers should
    not each learn about the next one.

    The row itself is deliberately not kept. It would be a second description
    of the same credential with nothing holding the two in agreement, and OAuth
    would have to fill both.
    """

    user: AbstractBaseUser
    request: HttpRequest
    workspace: Team | None
    scopes: list[str] | None
    #: Stable per credential, for the rate-limit window and the audit line. Two
    #: credentials belonging to one user throttle independently, which is what
    #: an operator expects of a token they can revoke on its own.
    credential_id: str
    #: What kind of credential this is, so an audit line says how someone got
    #: in rather than only that they did.
    credential_kind: str = "pat"

    @property
    def resolved_workspace(self) -> Any:
        """The workspace a tool resolved for this call, or ``None`` if none has.

        ``resolve_workspace`` stashes its answer on the stub request, which is
        built fresh per call. Reading it here rather than resolving again keeps
        the audit line off the database and out of the refusals that
        ``resolve_workspace`` itself raises.
        """
        return getattr(self.request, WORKSPACE_ATTR, None)


def _credential_kind(stub: HttpRequest) -> str:
    """How this caller got in, for the audit line.

    An ``AccessToken`` row is not always a personal access token: OIDC Trusted
    Publishing mints rows too, and ``get_user_and_token_record`` resolves both,
    so a bot uploading over ``/mcp`` would otherwise be recorded as a PAT and
    the field would say nothing.

    Asked through ``request_is_oidc_authed`` rather than by reading the signed
    claim directly, so the label cannot disagree with the answer the upload
    path's authorization uses. Its work is memoised on the request and on the
    token row, so the binding probe happens at most once per call and the
    upload path reuses it.
    """
    from sbomify.apps.oidc.permissions import request_is_oidc_authed

    return "oidc" if request_is_oidc_authed(stub) else "pat"


def current_request(mcp: Any) -> Any:
    """The Starlette request for the in-flight tool call, or ``None``.

    The streamable-HTTP transport threads the request through
    ``ServerMessageMetadata`` and the low-level server re-exposes it as
    ``RequestContext.request``. One accessor, because the two callers that need
    it fail differently when the SDK moves it: the tool wrapper raises, while
    ``list_tools`` would quietly advertise everything.
    """
    try:
        return mcp.get_context().request_context.request
    except (LookupError, AttributeError, ValueError):
        return None


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
    # X-Real-IP only. get_client_ip reads REMOTE_ADDR and HTTP_X_REAL_IP and
    # nothing else — X-Forwarded-For is deliberately never honoured anywhere in
    # the tree, so copying it here would only make the stub look like it were
    # trusted.
    if (real_ip := starlette_request.headers.get("x-real-ip")) is not None:
        stub.META["HTTP_X_REAL_IP"] = real_ip

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

    # database_sync_to_async, not a bare sync_to_async: this is the first DB
    # access of every MCP request — and the only one on the tools/list path —
    # and /mcp never fires the request signals that normally run
    # close_old_connections (see run_db in tools/_base.py). A bare wrapper here
    # would leave the per-request executor's connection to die of old age and
    # make a Postgres restart surface as an error auth can't recover from.
    user, record = await database_sync_to_async(get_user_and_token_record)(
        token,
        source_ip=get_client_ip(stub),
        attempted_action=f"mcp {attempted_action}",
    )
    if user is None or record is None:
        # A rejected credential never reaches the per-token throttle, so charge
        # the per-IP window the REST API keeps for tokenless surfaces instead —
        # each attempt costs a JWT decode plus an audit-log line, and without a
        # budget a loop of them amplifies both for free. Only failures are
        # charged: valid tokens stay on their own (larger) budget.
        anon_throttle = AnonymousIPRateThrottle()
        if not await sync_to_async(anon_throttle.allow_request)(stub):
            raise MCPRateLimitedError("Too many failed authentication attempts from this address. Retry later.")
        raise MCPAuthError("Invalid or expired access token.")

    stub.user = user  # type: ignore[assignment]
    setattr(stub, "access_token_record", record)
    setattr(stub, "token_team", record.team)

    # The MCP app bypasses NinjaAPI, so its global throttle never runs here.
    # Re-apply it against the same sliding window: an agent and a CI job using
    # the same token share one budget, which is what an operator would expect.
    #
    # A fresh instance per check, never a shared module-level one: ninja's
    # SimpleRateThrottle keeps per-request scratch (self.key/history/now) on
    # the instance, and MCP requests each run in their own executor thread, so
    # concurrent calls on a shared instance would write one token's window
    # under another token's key. The budget itself is unaffected — the sliding
    # window lives in the cache, keyed on the token pk.
    principal = Principal(
        user=user,
        request=stub,
        workspace=record.team,
        scopes=record.scopes,
        credential_id=str(record.pk),
        credential_kind=await sync_to_async(_credential_kind)(stub),
    )

    throttle = AccessTokenRateThrottle()
    if not await sync_to_async(throttle.allow_request)(stub):
        # Audited here rather than left to the tool wrapper, which only audits
        # what happens after this function returns. A token being hammered is
        # exactly what the audit stream exists to surface, and it is the one
        # refusal that reaches an authenticated, identifiable caller.
        message = f"Rate limit exceeded for this access token.{_retry_hint(stub)}"
        audit(attempted_action, principal, outcome="denied", detail=message)
        raise MCPRateLimitedError(message)

    return principal


def _retry_hint(stub: HttpRequest) -> str:
    """When to retry, from the budget the throttle stashed on the request.

    The REST API surfaces this as ``Retry-After``/``X-RateLimit-*`` headers via
    middleware /mcp never passes through; folding it into the error message is
    the only channel an MCP client has, and without it the natural agent
    behaviour is an immediate retry loop that keeps the window saturated.
    """
    import time

    budget = getattr(stub, "_access_token_ratelimit", None)
    if budget is None:
        return " Retry shortly."
    _, _, reset = budget
    return f" Retry in {max(1, int(reset - time.time()))} seconds."


async def throttle_write(principal: Principal, *, tool: str) -> None:
    """Apply the stricter write budget, on top of the global per-token one.

    Mirrors the REST API, where artifact uploads carry
    ``AccessTokenHeavyRateThrottle`` alongside the global throttle. The separate
    ``cache_key_prefix`` keeps the two sliding windows independent, so they do
    not double-count each other. Fresh instance per check for the same reason
    as in ``authenticate``.
    """
    throttle = AccessTokenHeavyRateThrottle()
    if not await sync_to_async(throttle.allow_request)(principal.request):
        raise MCPRateLimitedError(
            f"Write rate limit exceeded for this access token ({tool}).{_retry_hint(principal.request)}"
        )


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
