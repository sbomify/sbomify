"""Shared plumbing for MCP tool definitions.

``mcp_tool`` is the single way tools are declared. It ties together the three
things every tool needs and that are easy to forget individually:

* registration of the tool's required ``can()`` action (drives scope-filtered
  listing — see ``registry``),
* bearer-token authentication of the caller,
* injection of the resulting ``Principal`` as the tool's first argument.

The decorated function is written as ``async def tool(principal, ...)``; agents
never see ``principal`` because the wrapper rewrites the advertised signature.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from channels.db import database_sync_to_async
from mcp.server.fastmcp.exceptions import ToolError

from sbomify.apps.core.authz import scope_permits

from .. import registry
from ..auth import MCPAuthError, Principal, authenticate, throttle_write
from ..limits import audit, enforce_response_size

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sbomify.apps.teams.models import Team

T = TypeVar("T")

MAX_PAGE_SIZE = 100
"""Hard ceiling on any tool's page size. Agents pay for every token of a
response, and an unbounded list is the fastest way to exhaust a context window."""


def clamp_page(page: int, page_size: int, *, default_size: int = 25) -> tuple[int, int]:
    """Normalise agent-supplied pagination into something safe."""
    page = max(1, page)
    if page_size < 1:
        page_size = default_size
    return page, min(page_size, MAX_PAGE_SIZE)


def _current_request(mcp: FastMCP) -> Any:
    """The Starlette request for the in-flight tool call."""
    try:
        return mcp.get_context().request_context.request
    except (LookupError, AttributeError, ValueError):
        return None


def mcp_tool(
    mcp: FastMCP,
    name: str,
    action: str,
    *,
    also_requires: tuple[str, ...] = (),
    writes: bool = False,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Register ``fn`` as an MCP tool requiring ``action``.

    Every tool routed through here gets authentication, an audit event, and a
    response-size cap without having to remember them individually.

    ``writes=True`` marks a tool that mutates state. It adds the stricter
    per-token throttle the REST API applies to uploads, so a runaway or coerced
    agent cannot hammer the write path at read-tool rates.

    ``fn`` must be ``async``: in mcp 1.28 a sync tool function is invoked
    directly on the event loop with no thread offload, so any ORM access inside
    one would raise Django's ``SynchronousOnlyOperation``. Use ``run_db`` for
    database work.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"MCP tool {name!r} must be an async function (see mcp_tool docstring)")

        signature = inspect.signature(fn)
        params = list(signature.parameters.values())
        if not params or params[0].name != "principal":
            raise TypeError(f"MCP tool {name!r} must take 'principal' as its first parameter")

        spec = registry.register(name, action, also_requires=also_requires, writes=writes)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _current_request(mcp)
            if request is None:
                raise MCPAuthError("This tool must be called over HTTP with a bearer token.")
            principal = await authenticate(request, attempted_action=name)

            # Defence in depth: refuse anything the token's scopes don't grant,
            # before the tool body runs. The per-resource can() check inside each
            # tool remains the authoritative decision — but several tools delegate
            # to REST views that load the resource *first* and so return 404
            # before they ever reach their can() call. That ordering is right for
            # the REST API (it avoids confirming a resource exists to someone who
            # may not read it), but it means the action declared in the registry
            # would otherwise be advisory for those tools. This makes it binding:
            # a read-only token is refused at the door, whatever the wrapped view
            # would have done.
            for required in spec.actions:
                if not scope_permits(principal.scopes, required):
                    raise MCPAuthError(f"Not permitted ({required}): token scope does not grant {required!r}")

            if writes:
                await throttle_write(principal, tool=name)

            try:
                result = await fn(principal, *args, **kwargs)
                # Inside the try so an over-cap response is audited as a refusal
                # rather than logged as a success it never was.
                checked = enforce_response_size(result, tool=name)
            except ToolError as exc:
                # Expected refusals (denied, not found, over a limit). Recorded
                # so a probing pattern is visible in the audit log, then
                # re-raised unchanged for the agent.
                audit(name, principal, outcome="denied", detail=str(exc))
                raise
            except Exception:
                # Deliberately no detail: an unexpected exception's message can
                # carry query fragments or storage paths, which belong in the
                # traceback, not the audit stream.
                audit(name, principal, outcome="error")
                raise

            audit(name, principal, outcome="success")
            return checked

        # FastMCP builds the input schema from the signature, and
        # functools.wraps sets __wrapped__, which inspect.signature follows.
        # Publish the signature without `principal` so it stays an internal
        # detail rather than a parameter the agent is asked to supply.
        wrapper.__signature__ = signature.replace(parameters=params[1:])  # type: ignore[attr-defined]

        mcp.add_tool(wrapper, name=name, description=inspect.getdoc(fn))
        return fn

    return decorator


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous ORM/service call from an async tool.

    Uses channels' ``database_sync_to_async`` rather than a bare
    ``sync_to_async``: it calls ``close_old_connections()` around the call,
    which is what recycles a connection broken by a Postgres restart, failover,
    or server-side idle timeout.

    That matters here specifically because ``/mcp`` is dispatched before
    Django's ASGI handler (see ``sbomify/asgi.py``), so the
    ``request_started``/``request_finished`` signals that normally trigger
    ``close_old_connections`` never fire for MCP traffic. Without this the
    executor thread's connection would go stale and every later tool call in
    that worker would fail until the process restarted, while REST requests
    through the same process recovered on their next hit.
    """
    return await database_sync_to_async(fn)(*args, **kwargs)


def resolve_workspace(principal: Principal) -> Team:
    """The workspace this call operates in.

    Mirrors the REST API's resolution (``core.apis._get_user_team_id``) minus
    the session branch, which cannot apply: the MCP stub request carries an
    empty session by construction, so a token is the only signal available.

    A workspace-pinned token wins outright. Legacy tokens predating workspace
    scoping (``team IS NULL``) fall back to the user's default workspace, which
    keeps them working while the operator rotates them.
    """
    from sbomify.apps.core.models import User
    from sbomify.apps.teams.models import Member
    from sbomify.apps.teams.utils import get_user_default_team

    if principal.token.team is not None:
        return principal.token.team

    user = cast("User", principal.user)
    team_id = get_user_default_team(user)
    if team_id is not None:
        membership = Member.objects.filter(user=user, team_id=team_id).select_related("team").first()
        if membership is not None:
            return membership.team

    # Ordered so the fallback is deterministic: this resolves per tool call,
    # and an unordered .first() could hand consecutive calls in one agent
    # session different workspaces.
    membership = Member.objects.filter(user=user).select_related("team").order_by("pk").first()
    if membership is None:
        raise ToolError("This token is not associated with any workspace.")
    return membership.team


def workspace_key(team: Team) -> str:
    """The workspace's public key, for tools that call a ``{team_key}`` REST view.

    ``Team.key`` is nullable in the schema but populated on save, so an empty one
    means a malformed row rather than anything the caller did.
    """
    if not team.key:
        raise ToolError(f"Workspace {team.pk} has no key; this workspace is not usable over the API.")
    return team.key


def not_found(kind: str, identifier: str) -> ToolError:
    """A uniform not-found error.

    Deliberately identical whether the resource is absent or merely invisible to
    this token: distinguishing them would let a caller probe for the existence
    of resources in workspaces it cannot read.
    """
    return ToolError(f"No {kind} found with id {identifier!r} in this workspace.")
