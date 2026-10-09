"""
ASGI config for sbomify project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
from contextlib import AsyncExitStack
from typing import Any

from asgiref.sync import ThreadSensitiveContext
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
from sbomify.apps.mcp.server import MCP_PATH_PREFIX, build_app, mcp  # noqa: E402

# Builds the MCP Starlette app and registers its tools. Must run after
# get_asgi_application() because the tool modules import Django models.
# Calling this also creates the StreamableHTTPSessionManager that
# LifespanApp starts below — ``mcp.session_manager`` raises until it has.
mcp_application = build_app()


class MCPRouter:
    """Routes ``/mcp`` to the MCP server; everything else to Django.

    Dispatch happens on the unmodified scope path, so the MCP app's single route
    (``streamable_http_path``) must equal ``MCP_PATH_PREFIX``.
    """

    def __init__(self, django_app: ASGIApp, mcp_app: ASGIApp) -> None:
        self.django_app = django_app
        self.mcp_app = mcp_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if path == MCP_PATH_PREFIX or path.startswith(f"{MCP_PATH_PREFIX}/"):
            # Django's ASGIHandler opens a ThreadSensitiveContext per request;
            # this dispatch happens before Django, so without one here every
            # thread-sensitive sync call from every concurrent MCP request —
            # all ORM work via database_sync_to_async — shares asgiref's single
            # process-wide executor thread. One agent parsing a large SBOM
            # would then head-of-line-block every other MCP call in the worker.
            # A per-request context gives each request its own executor, the
            # same isolation Django requests get.
            async with ThreadSensitiveContext():
                await self.mcp_app(scope, receive, send)
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
