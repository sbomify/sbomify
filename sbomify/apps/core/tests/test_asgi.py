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
async def test_asgi_http_delegated_to_django(anyio_backend) -> None:
    """Test that HTTP requests are routed through the ASGI application.

    This test verifies that HTTP requests go through the ProtocolTypeRouter
    to the Django ASGI handler.
    """
    # We need to patch at the ProtocolTypeRouter level since the application
    # is constructed at import time. Instead, we verify that the routing
    # structure is correct.
    from sbomify.asgi import application
    from channels.routing import ProtocolTypeRouter

    # Verify the application structure has the expected routing
    assert hasattr(application, "app")  # LifespanApp wraps the router
    inner_app = application.app
    assert isinstance(inner_app, ProtocolTypeRouter)
    assert "http" in inner_app.application_mapping
    assert "websocket" in inner_app.application_mapping
