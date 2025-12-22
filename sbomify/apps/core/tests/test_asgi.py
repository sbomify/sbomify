"""Tests for ASGI application lifespan handling."""

import pytest
from unittest.mock import AsyncMock, patch


class TestAsgiLifespan:
    """Test ASGI lifespan handling without event loop conflicts."""

    def test_asgi_lifespan_startup_shutdown(self) -> None:
        """Test that ASGI application handles lifespan startup and shutdown events."""
        import asyncio

        async def run_test():
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

        asyncio.run(run_test())

    def test_asgi_http_delegated_to_django(self) -> None:
        """Test that HTTP requests are delegated to Django ASGI application."""
        import asyncio

        async def run_test():
            mock_django_app = AsyncMock()

            with patch("sbomify.asgi.django_application", mock_django_app):
                from sbomify.asgi import application

                scope = {
                    "type": "http",
                    "method": "GET",
                    "path": "/",
                    "query_string": b"",
                    "headers": [],
                }

                async def mock_receive():
                    return {"type": "http.request", "body": b""}

                async def mock_send(message):
                    pass

                await application(scope, mock_receive, mock_send)

                mock_django_app.assert_called_once_with(scope, mock_receive, mock_send)

        asyncio.run(run_test())
