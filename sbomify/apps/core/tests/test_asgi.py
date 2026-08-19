"""Tests for ASGI application lifespan handling."""

import pytest


@pytest.fixture
def anyio_backend():
    """Use function-scoped asyncio backend to avoid event loop conflicts."""
    return "asyncio"


@pytest.mark.anyio
async def test_asgi_lifespan_startup_shutdown(anyio_backend) -> None:
    """Test that ASGI application handles lifespan startup and shutdown events."""
    sent_messages = []

    async def mock_receive():
        yield {"type": "lifespan.startup"}
        yield {"type": "lifespan.shutdown"}

    async def mock_send(message):
        sent_messages.append(message)

    receive_gen = mock_receive()
    scope = {"type": "lifespan"}

    async def receive():
        return await receive_gen.__anext__()

    from sbomify.asgi import application

    await application(scope, receive, mock_send)

    assert {"type": "lifespan.startup.complete"} in sent_messages
    assert {"type": "lifespan.shutdown.complete"} in sent_messages


@pytest.mark.anyio
async def test_mcp_requests_get_their_own_thread_sensitive_context(anyio_backend) -> None:
    """Each /mcp request must run in its own ThreadSensitiveContext.

    Django's ASGIHandler opens one per request, but /mcp is dispatched before
    Django. Without a context of its own, every thread-sensitive sync call from
    every concurrent MCP request shares asgiref's single process-wide executor
    thread, so one slow tool call blocks all MCP traffic in the worker.
    """
    from asgiref.sync import SyncToAsync

    from sbomify.asgi import MCPRouter

    seen = {}

    async def record_context(scope, receive, send):
        seen[scope["path"]] = SyncToAsync.thread_sensitive_context.get(None)

    router = MCPRouter(django_app=record_context, mcp_app=record_context)

    async def receive():  # pragma: no cover - never called
        raise AssertionError("no body expected")

    async def send(message):
        pass

    await router({"type": "http", "path": "/mcp"}, receive, send)
    await router({"type": "http", "path": "/api/v1/products"}, receive, send)

    assert seen["/mcp"] is not None, "MCP dispatch must open a ThreadSensitiveContext"
    # Django opens its own per-request context downstream; the router must not
    # wrap it in an outer one, which would defeat that isolation (the manager
    # is re-entrant and only the outermost context sets the executor).
    assert seen["/api/v1/products"] is None


@pytest.mark.anyio
async def test_asgi_http_delegated_to_django(anyio_backend) -> None:
    """Test that HTTP requests are routed through the ASGI application.

    This test verifies that HTTP requests go through the ProtocolTypeRouter
    to the Django ASGI handler.
    """
    # We need to patch at the ProtocolTypeRouter level since the application
    # is constructed at import time. Instead, we verify that the routing
    # structure is correct.
    from channels.routing import ProtocolTypeRouter

    from sbomify.asgi import application

    # Verify the application structure has the expected routing
    assert hasattr(application, "app")  # LifespanApp wraps the router
    inner_app = application.app
    assert isinstance(inner_app, ProtocolTypeRouter)
    assert "http" in inner_app.application_mapping
    assert "websocket" in inner_app.application_mapping
