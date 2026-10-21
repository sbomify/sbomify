"""
ASGI config for sbomify project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import asyncio
import json
import os
from contextlib import AsyncExitStack
from typing import Any

from asgiref.sync import ThreadSensitiveContext
from django.conf import settings
from django.core.asgi import get_asgi_application
from starlette.types import Receive, Scope, Send

# The apps composed below come from three libraries (Django, channels, starlette)
# whose ASGI type vocabularies are mutually incompatible under strict checking
# even though they interoperate fine at runtime. Type the wrapped app as Any and
# keep the precise types on __call__, where they actually catch mistakes.
ASGIApp = Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")

# Get the Django ASGI application - must be called before importing channels
django_application = get_asgi_application()

# Import channels after Django is initialized
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from sbomify.apps.core.routing import websocket_urlpatterns  # noqa: E402
from sbomify.apps.mcp.auth import authenticate_request, may_send_large_body  # noqa: E402
from sbomify.apps.mcp.server import MCP_PATH_PREFIX, build_app, mcp  # noqa: E402

# Builds the MCP Starlette app and registers its tools. Must run after
# get_asgi_application() because the tool modules import Django models.
# Calling this also creates the StreamableHTTPSessionManager that
# LifespanApp starts below — ``mcp.session_manager`` raises until it has.
mcp_application = build_app()

# How long an MCP request waits for a free slot before it is told to retry.
MCP_SLOT_WAIT_SECONDS = 5.0



async def _send_error(send: Send, status: int, message: str, *, retry_after: int | None = None) -> None:
    """A JSON-RPC error sent before the body is read, so it cannot name the request's id."""
    body = json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": message}}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _may_carry_large_body(scope: Scope) -> bool:
    """Whether the body may exceed ``MCP_MAX_REQUEST_BYTES``.

    A request without Content-Length or Transfer-Encoding has no body (RFC 9112
    6.3), and the server holds the client to the length it states, so the
    header answers before anything is read.
    """
    headers = dict(scope.get("headers") or [])
    length = headers.get(b"content-length")
    if length is None:
        return b"transfer-encoding" in headers
    try:
        return int(length) > settings.MCP_MAX_REQUEST_BYTES
    except ValueError:
        return True


class MCPRouter:
    """Routes ``/mcp`` to the MCP server; everything else to Django.

    Dispatch happens on the unmodified scope path, so the MCP app's single route
    (``streamable_http_path``) must equal ``MCP_PATH_PREFIX``.

    Each in-flight MCP request holds an executor thread and a database
    connection of its own (see below), so the number in flight is capped per
    process at ``MCP_MAX_CONCURRENT_REQUESTS``. The cap applies before the
    per-token throttle, which only runs once a request is inside. A request
    over the cap waits up to ``MCP_SLOT_WAIT_SECONDS`` for a slot, then gets a
    503 with ``Retry-After``. Django requests never wait behind it.

    The transport buffers a body of up to three times ``MCP_MAX_UPLOAD_BYTES``,
    so a request whose body may exceed ``MCP_MAX_REQUEST_BYTES`` also needs one
    of ``MCP_MAX_CONCURRENT_UPLOADS`` slots. It takes that slot first, holding
    nothing else while it waits, so small calls are not queued behind uploads.

    Then, before the MCP app reads anything, the request is authenticated from
    its headers (``authenticate_request``): every request is charged and
    audited, including a malformed one FastMCP would refuse before any tool
    code ran. A caller over its budget is refused here, and so is a body over
    ``MCP_MAX_REQUEST_BYTES`` from anyone whose token cannot call an upload
    tool, since only an artifact needs that much. Neither body is read.
    """

    def __init__(self, django_app: ASGIApp, mcp_app: ASGIApp) -> None:
        self.django_app = django_app
        self.mcp_app = mcp_app
        self.mcp_slots = asyncio.Semaphore(settings.MCP_MAX_CONCURRENT_REQUESTS)
        self.upload_slots = asyncio.Semaphore(settings.MCP_MAX_CONCURRENT_UPLOADS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if path == MCP_PATH_PREFIX or path.startswith(f"{MCP_PATH_PREFIX}/"):
            wanted = [self.upload_slots, self.mcp_slots] if _may_carry_large_body(scope) else [self.mcp_slots]
            held: list[asyncio.Semaphore] = []
            # One finally gives back whatever was taken however the request
            # ends: a timeout, a client that hangs up mid-wait (a cancellation,
            # not a timeout), or a normal finish.
            try:
                try:
                    async with asyncio.timeout(MCP_SLOT_WAIT_SECONDS):
                        for slot in wanted:
                            await slot.acquire()
                            held.append(slot)
                except TimeoutError:
                    await _send_error(send, 503, "The server is busy. Retry in a moment.", retry_after=1)
                    return
                # Django's ASGIHandler opens a ThreadSensitiveContext per request;
                # this dispatch happens before Django, so without one here every
                # thread-sensitive sync call from every concurrent MCP request
                # (all ORM work via database_sync_to_async) shares asgiref's single
                # process-wide executor thread. One agent parsing a large SBOM
                # would then head-of-line-block every other MCP call in the worker.
                # A per-request context gives each request its own executor, the
                # same isolation Django requests get.
                async with ThreadSensitiveContext():
                    if (over_budget := await authenticate_request(scope)) is not None:
                        await _send_error(send, 429, str(over_budget), retry_after=over_budget.retry_after)
                        return
                    if _may_carry_large_body(scope) and not may_send_large_body(scope):
                        await _send_error(
                            send,
                            413,
                            f"Request body over {settings.MCP_MAX_REQUEST_BYTES} bytes. "
                            "Only a token that may upload artifacts can send one this large.",
                        )
                        return
                    await self.mcp_app(scope, receive, send)
            finally:
                for slot in held:
                    slot.release()
        else:
            await self.django_app(scope, receive, send)


class LifespanApp:
    """
    Handles ASGI lifespan events (startup/shutdown).

    This is necessary because Django's ASGI application doesn't handle
    lifespan events, which are sent by ASGI servers like uvicorn.

    It is also where the MCP server's StreamableHTTPSessionManager is started.
    That manager owns an anyio task group which must be entered before it can
    serve a request; without it every ``/mcp`` call fails with "Task group is
    not initialized. Make sure to use run()." The manager may only be entered
    once per process, so this is its single owner — the MCP Starlette app also
    declares ``lifespan=session_manager.run()``, but we never drive that app's
    lifespan, precisely to avoid a second entry.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            async with AsyncExitStack() as stack:
                started = False
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        try:
                            await stack.enter_async_context(mcp.session_manager.run())
                            started = True
                        except Exception as exc:  # pragma: no cover - startup failure
                            await send({"type": "lifespan.startup.failed", "message": str(exc)})
                            return
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        # Leaving the stack cancels the session manager's task
                        # group. Do it before acknowledging so shutdown is
                        # actually complete when the server hears back.
                        if started:
                            await stack.aclose()
                        await send({"type": "lifespan.shutdown.complete"})
                        return
        else:
            await self.app(scope, receive, send)


# Main ASGI application with protocol routing
application = LifespanApp(
    ProtocolTypeRouter(
        {
            "http": MCPRouter(django_application, mcp_application),
            "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        }
    )
)
