"""Session authentication for WebSockets that survives the database being down.

Channels' ``AuthMiddleware`` loads the session and the user before the consumer
runs. With the database unreachable that load raises, the exception escapes the
ASGI application, and the server refuses the handshake with HTTP 500 — before
``connect()`` has had the chance to answer with a close code. The browser sees
1006, the same as a dropped network, and every open tab reconnects into the
same traceback.

Here the failure is recorded on the scope instead, with the user left
anonymous, so the consumer accepts the handshake and closes with 1012: the
client is told the server is unavailable and retries, rather than being told it
may not connect.
"""

from __future__ import annotations

from typing import Any

from channels.auth import AuthMiddleware
from channels.sessions import CookieMiddleware, SessionMiddleware
from django.contrib.auth.models import AnonymousUser
from django.db import DatabaseError

from sbomify.logging import getLogger

logger = getLogger(__name__)

# Set on the scope when the session or user could not be read. A consumer that
# finds it must close for an outage, not for an unauthenticated client.
AUTH_UNAVAILABLE_SCOPE_KEY = "auth_unavailable"


class ResilientAuthMiddleware(AuthMiddleware):
    async def resolve_scope(self, scope: Any) -> None:
        try:
            await super().resolve_scope(scope)
        except DatabaseError as exc:
            # One line per socket, no traceback: a database outage fails every
            # reconnecting tab at once.
            logger.warning(f"WebSocket session lookup failed for {scope.get('path')}: {exc!r}")
            scope["user"]._wrapped = AnonymousUser()
            scope[AUTH_UNAVAILABLE_SCOPE_KEY] = True


def ResilientAuthMiddlewareStack(inner: Any) -> CookieMiddleware:
    """``channels.auth.AuthMiddlewareStack`` with :class:`ResilientAuthMiddleware`."""
    return CookieMiddleware(SessionMiddleware(ResilientAuthMiddleware(inner)))
