"""A database outage at WebSocket connect is an outage, not a rejection.

Channels' ``AuthMiddleware`` read the session before the consumer ran, and with
the database unreachable the exception escaped the ASGI app:

    Exception in ASGI application
    AttributeError: 'SessionStore' object has no attribute '_session_cache'
    django.db.utils.OperationalError: connection to server ... timeout expired
    connection rejected (500 Internal Server Error)

A refused handshake carries no close code, so the client could not tell this
from a dropped network. These pin the path to a 1012 the client retries on.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import psycopg2
import pytest
from channels.auth import UserLazyObject
from django.db import InterfaceError, OperationalError, ProgrammingError

from sbomify.apps.core.consumers import WS_CLOSE_POLICY_VIOLATION, WS_CLOSE_SERVICE_RESTART, WorkspaceConsumer
from sbomify.apps.core.user_consumer import UserConsumer
from sbomify.apps.core.ws_auth import AUTH_UNAVAILABLE_SCOPE_KEY, ResilientAuthMiddleware


def _unreachable(message: str = "timeout expired") -> OperationalError:
    """Django's error wrapping the driver's, as Django raises it: the driver's
    message is what says Postgres is unreachable rather than the query wrong."""
    error = OperationalError(message)
    error.__cause__ = psycopg2.OperationalError(message)
    return error


class _User:
    is_authenticated = True
    id = 7


async def _drive(consumer: Any, path: str, kwargs: dict[str, str], **scope_extra: Any) -> list[dict]:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    inbox = [{"type": "websocket.connect"}]

    async def receive() -> dict:
        return inbox.pop(0) if inbox else {"type": "websocket.disconnect", "code": 1000}

    scope = {"type": "websocket", "path": path, "url_route": {"kwargs": kwargs}, "headers": [], **scope_extra}
    await consumer.as_asgi()(scope, receive, send)
    return sent


def _close_code(sent: list[dict]) -> int | None:
    return next(m for m in sent if m["type"] == "websocket.close").get("code")


class TestTheMiddlewareRecordsTheOutage:
    @pytest.mark.asyncio
    async def test_a_failed_session_read_reaches_the_consumer_as_a_flag(self, monkeypatch) -> None:
        monkeypatch.setattr("channels.auth.get_user", AsyncMock(side_effect=_unreachable()))
        seen: dict[str, Any] = {}

        async def inner(scope: dict, receive: Any, send: Any) -> None:
            seen.update(scope)

        await ResilientAuthMiddleware(inner)({"type": "websocket", "path": "/ws/user/", "session": {}}, None, None)

        assert seen[AUTH_UNAVAILABLE_SCOPE_KEY] is True
        assert seen["user"].is_authenticated is False

    @pytest.mark.asyncio
    async def test_a_connection_the_server_already_closed_is_an_outage_too(self, monkeypatch) -> None:
        """Django raises this one as ``InterfaceError``, which is not a ``DatabaseError``."""
        closed = InterfaceError("connection already closed")
        closed.__cause__ = psycopg2.InterfaceError("connection already closed")
        monkeypatch.setattr("channels.auth.get_user", AsyncMock(side_effect=closed))
        seen: dict[str, Any] = {}

        async def inner(scope: dict, receive: Any, send: Any) -> None:
            seen.update(scope)

        await ResilientAuthMiddleware(inner)({"type": "websocket", "path": "/ws/user/", "session": {}}, None, None)

        assert seen[AUTH_UNAVAILABLE_SCOPE_KEY] is True
        assert seen["user"].is_authenticated is False

    @pytest.mark.asyncio
    async def test_a_database_fault_that_is_not_an_outage_still_raises(self, monkeypatch) -> None:
        """A missing table is a fault to fix, not a 1012 every tab retries forever."""
        missing = ProgrammingError('relation "django_session" does not exist')
        monkeypatch.setattr("channels.auth.get_user", AsyncMock(side_effect=missing))

        async def inner(scope: dict, receive: Any, send: Any) -> None:
            raise AssertionError("the consumer must not run")

        with pytest.raises(ProgrammingError):
            await ResilientAuthMiddleware(inner)({"type": "websocket", "path": "/ws/user/", "session": {}}, None, None)

    @pytest.mark.asyncio
    async def test_a_working_session_read_sets_no_flag(self, monkeypatch) -> None:
        monkeypatch.setattr("channels.auth.get_user", AsyncMock(return_value=_User()))
        seen: dict[str, Any] = {}

        async def inner(scope: dict, receive: Any, send: Any) -> None:
            seen.update(scope)

        await ResilientAuthMiddleware(inner)({"type": "websocket", "path": "/ws/user/", "session": {}}, None, None)

        assert AUTH_UNAVAILABLE_SCOPE_KEY not in seen
        assert seen["user"].is_authenticated is True


def _anonymous() -> UserLazyObject:
    from django.contrib.auth.models import AnonymousUser

    user = UserLazyObject()
    user._wrapped = AnonymousUser()
    return user


class TestTheConsumersCloseForRetry:
    @pytest.mark.asyncio
    async def test_the_workspace_socket(self) -> None:
        sent = await _drive(
            WorkspaceConsumer,
            "/ws/workspace/ws-key/",
            {"workspace_key": "ws-key"},
            user=_anonymous(),
            **{AUTH_UNAVAILABLE_SCOPE_KEY: True},
        )

        assert [m["type"] for m in sent] == ["websocket.accept", "websocket.close"]
        assert _close_code(sent) == WS_CLOSE_SERVICE_RESTART

    @pytest.mark.asyncio
    async def test_the_user_socket(self) -> None:
        sent = await _drive(UserConsumer, "/ws/user/", {}, user=_anonymous(), **{AUTH_UNAVAILABLE_SCOPE_KEY: True})

        assert _close_code(sent) == WS_CLOSE_SERVICE_RESTART

    @pytest.mark.asyncio
    async def test_an_anonymous_client_without_the_flag_is_still_refused(self) -> None:
        """The flag is the only thing that turns an anonymous user into a retry."""
        sent = await _drive(WorkspaceConsumer, "/ws/workspace/ws-key/", {"workspace_key": "ws-key"}, user=_anonymous())

        assert _close_code(sent) == WS_CLOSE_POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_the_membership_check_failing_is_an_outage_too(self, monkeypatch) -> None:
        monkeypatch.setattr(
            WorkspaceConsumer, "_check_workspace_membership", AsyncMock(side_effect=_unreachable("connection refused"))
        )

        sent = await _drive(WorkspaceConsumer, "/ws/workspace/ws-key/", {"workspace_key": "ws-key"}, user=_User())

        assert _close_code(sent) == WS_CLOSE_SERVICE_RESTART


class TestThroughTheApplication:
    """``asgi.py`` is what puts the middleware in front of the consumers, so
    these drive the real application with the session table unreachable."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/ws/user/", "/ws/workspace/ws-key/"])
    async def test_a_session_that_cannot_be_read_closes_with_1012(self, monkeypatch, path: str) -> None:
        from unittest.mock import Mock

        from django.conf import settings

        from sbomify.asgi import application

        monkeypatch.setattr(
            "django.contrib.sessions.backends.db.SessionStore.load",
            Mock(side_effect=_unreachable()),
        )
        sent: list[dict] = []
        inbox = [{"type": "websocket.connect"}]

        async def send(message: dict) -> None:
            sent.append(message)

        async def receive() -> dict:
            return inbox.pop(0) if inbox else {"type": "websocket.disconnect", "code": 1000}

        scope = {
            "type": "websocket",
            "path": path,
            "raw_path": path.encode(),
            "headers": [(b"cookie", f"{settings.SESSION_COOKIE_NAME}=some-session-key".encode())],
            "query_string": b"",
            "subprotocols": [],
        }
        await application(scope, receive, send)

        assert [m["type"] for m in sent] == ["websocket.accept", "websocket.close"]
        assert _close_code(sent) == WS_CLOSE_SERVICE_RESTART
