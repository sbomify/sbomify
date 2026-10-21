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
from sbomify.apps.mcp.auth import audit_rejected, authenticate_request, may_send_large_body  # noqa: E402
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


def _states_large_body(scope: Scope) -> bool:
    """Whether the headers say the body is over ``MCP_MAX_REQUEST_BYTES``, or of unbounded length."""
    headers = dict(scope.get("headers") or [])
    length = headers.get(b"content-length")
    if length is None:
        return b"transfer-encoding" in headers
    try:
        return int(length) > settings.MCP_MAX_REQUEST_BYTES
    except ValueError:
        return True


def _may_carry_large_body(scope: Scope) -> bool:
    """Whether the body may exceed ``MCP_MAX_REQUEST_BYTES``.

    Under HTTP/1.1 a request without Content-Length or Transfer-Encoding has no
    body (RFC 9112 6.3). HTTP/2 and HTTP/3 need neither header to send one, so
    there an unstated length may be large.
    """
    if _states_large_body(scope):
        return True
    headers = dict(scope.get("headers") or [])
    return b"content-length" not in headers and scope.get("http_version") not in ("1.0", "1.1")


_ANSWER_KEPT = 64 * 1024
"""How much of an answer the router keeps to tell a rejection apart. Rejections are a few hundred bytes."""


class _BodyCap:
    """Counts the body as the app reads it and stops it at ``cap`` bytes.

    The headers cannot size every body (see ``_may_carry_large_body``), so this
    is the limit that holds. Past the cap the app is told the client hung up,
    so it reads nothing more, and whatever it answers to that is dropped: the
    router sends the 413 itself.

    It also keeps the answer's status and its first and last bytes, so the
    router can audit a call the app rejected before any tool ran.
    """

    def __init__(self, receive: Receive, send: Send, cap: int) -> None:
        self._receive = receive
        self._send = send
        self.cap = cap
        self.seen = 0
        self.exceeded = False
        self.started = False
        self.status = 0
        self.answer = bytearray()
        self.answer_size = 0
        self.tail = b""

    async def receive(self) -> Any:
        if self.exceeded:
            return {"type": "http.disconnect"}
        message = await self._receive()
        if message["type"] == "http.request":
            self.seen += len(message.get("body", b""))
            if self.seen > self.cap:
                self.exceeded = True
                return {"type": "http.disconnect"}
        return message

    async def send(self, message: Any) -> None:
        if self.exceeded:
            return
        if message["type"] == "http.response.start":
            self.started = True
            self.status = message["status"]
        elif message["type"] == "http.response.body":
            chunk = message.get("body", b"")
            self.answer_size += len(chunk)
            if len(self.answer) < _ANSWER_KEPT:
                self.answer += chunk[: _ANSWER_KEPT - len(self.answer)]
            self.tail = (self.tail + chunk)[-256:]
        await self._send(message)

    @property
    def whole_answer(self) -> bytes | None:
        """The whole answer when it was small enough to keep, else None."""
        return bytes(self.answer) if self.answer_size <= _ANSWER_KEPT else None


async def _send_too_large(send: Send, cap: int, *, may_upload: bool) -> None:
    reason = "" if may_upload else " Only a token that may upload artifacts can send one this large."
    await _send_error(send, 413, f"Request body over {cap} bytes.{reason}")


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
    tool, since only an artifact needs that much. Neither body is read. When
    FastMCP refuses an authenticated call itself (a parse error, an unknown
    tool, arguments that fail the schema), the router audits it after the
    answer, since the tool wrapper never saw it (``audit_rejected``).

    Headers cannot size every body: HTTP/2 and HTTP/3 send one without stating
    its length. So the body is also counted as the app reads it, and cut off
    with a 413 past the same cap, or past the transport's own cap for a token
    that may upload (``_BodyCap``).
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
                    may_upload = may_send_large_body(scope)
                    cap = mcp.settings.max_request_body_size if may_upload else settings.MCP_MAX_REQUEST_BYTES
                    if _states_large_body(scope) and not may_upload:
                        await _send_too_large(send, cap, may_upload=False)
                        return
                    body = _BodyCap(receive, send, cap)
                    try:
                        await self.mcp_app(scope, body.receive, body.send)
                    except Exception:
                        # The app may raise on the hang-up it was told about.
                        if not body.exceeded:
                            raise
                    if body.exceeded and not body.started:
                        await _send_too_large(send, cap, may_upload=may_upload)
                    elif not body.exceeded:
                        audit_rejected(scope, body.status, body.whole_answer, body.tail)
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
