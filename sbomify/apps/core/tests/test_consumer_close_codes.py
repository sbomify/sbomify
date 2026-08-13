"""A close code the client never receives cannot tell it anything.

``connect()`` rejected every connection by closing before accepting the
handshake. Per the ASGI spec that makes the server refuse with HTTP 403, and a
refused handshake carries no close code — the browser reports 1006 for all of
them, which is also what it reports for a dropped network.

Two consequences, both visible in production. A broker blip was answered with

    WebSocket group join failed for workspace <key>: ConnectionError(...)
    "WebSocket /ws/workspace/<key>/" 403
    connection rejected (403 Forbidden)

so an outage was indistinguishable from "you are not a member". And the store's
``NO_RETRY_CLOSE_CODES`` guard was unreachable: it lists 1002, 1003 and 1008,
none of which ``connect()`` could ever deliver, so a client that genuinely may
not connect retried the same rejection on the full backoff schedule instead of
stopping.

These drive the ASGI application directly rather than mocking ``accept`` and
``close``, because the ordering of those two calls is the entire defect — a
test that mocks them both passes just as happily with the close first.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sbomify.apps.core.consumers import (
    WS_CLOSE_POLICY_VIOLATION,
    WS_CLOSE_SERVICE_RESTART,
    WorkspaceConsumer,
)


class _User:
    is_authenticated = True
    id = 7


async def _drive(user, *, group_add_error=None, monkeypatch=None) -> list[dict]:
    """Run the consumer's ASGI app and return the messages it sent."""
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    inbox = [{"type": "websocket.connect"}]

    async def receive() -> dict:
        return inbox.pop(0) if inbox else {"type": "websocket.disconnect", "code": 1000}

    scope = {
        "type": "websocket",
        "path": "/ws/workspace/ws-key/",
        "url_route": {"kwargs": {"workspace_key": "ws-key"}},
        "user": user,
        "headers": [],
    }

    if group_add_error is not None:
        # Patching the shared channel layer without monkeypatch would leak the
        # broken group_add into every test that ran after this one. Stated as a
        # requirement rather than left to fail on None, so a caller that forgets
        # the fixture gets told why instead of an AttributeError.
        assert monkeypatch is not None, "group_add_error requires the monkeypatch fixture to undo the patch"

        from channels.layers import get_channel_layer

        monkeypatch.setattr(get_channel_layer(), "group_add", AsyncMock(side_effect=group_add_error))

    await WorkspaceConsumer.as_asgi()(scope, receive, send)
    return sent


def _types(sent: list[dict]) -> list[str]:
    return [message["type"] for message in sent]


def _close(sent: list[dict]) -> dict:
    return next(message for message in sent if message["type"] == "websocket.close")


class TestARejectionCarriesItsCode:
    @pytest.mark.asyncio
    async def test_the_handshake_completes_before_the_close(self) -> None:
        """The defect itself. A close ahead of the accept is an HTTP 403 and
        the code on it is discarded."""
        sent = await _drive(None)

        assert _types(sent) == ["websocket.accept", "websocket.close"]

    @pytest.mark.asyncio
    async def test_an_unauthenticated_client_is_told_not_to_retry(self) -> None:
        assert _close(await _drive(None)).get("code") == WS_CLOSE_POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_a_non_member_is_told_not_to_retry(self, monkeypatch) -> None:
        monkeypatch.setattr(
            WorkspaceConsumer,
            "_check_workspace_membership",
            AsyncMock(return_value=False),
        )

        assert _close(await _drive(_User())).get("code") == WS_CLOSE_POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_a_broker_outage_is_told_to_retry(self, monkeypatch) -> None:
        """The case from production. It must not arrive looking like the two
        above — an outage is temporary and the client should come back."""
        monkeypatch.setattr(
            WorkspaceConsumer,
            "_check_workspace_membership",
            AsyncMock(return_value=True),
        )

        sent = await _drive(_User(), group_add_error=ConnectionError("reset by peer"), monkeypatch=monkeypatch)

        assert _close(sent).get("code") == WS_CLOSE_SERVICE_RESTART


class TestTheCodesMatchWhatTheClientActsOn:
    """The server and the store agree by convention only, and the store's guard
    was dead for exactly that reason. These pin the two together."""

    def test_the_rejection_code_is_one_the_store_refuses_to_retry(self) -> None:
        # Mirrors NO_RETRY_CLOSE_CODES in core/js/components/websocket-store.ts.
        assert WS_CLOSE_POLICY_VIOLATION in {1002, 1003, 1008}

    def test_the_outage_code_is_one_the_store_does_retry(self) -> None:
        assert WS_CLOSE_SERVICE_RESTART not in {1002, 1003, 1008}


class TestNothingLeaksBeforeTheVerdict:
    """Accepting ahead of the checks is only safe because the connection is
    inert until they pass."""

    @pytest.mark.asyncio
    async def test_a_rejected_client_is_sent_no_payload(self) -> None:
        sent = await _drive(None)

        assert not [m for m in sent if m["type"] == "websocket.send"]

    @pytest.mark.asyncio
    async def test_a_rejected_client_joins_no_group(self, monkeypatch) -> None:
        """Group membership is what a broadcast addresses. A client closed for
        policy must never have been in one."""
        from channels.layers import get_channel_layer

        group_add = AsyncMock()
        monkeypatch.setattr(get_channel_layer(), "group_add", group_add)
        monkeypatch.setattr(
            WorkspaceConsumer,
            "_check_workspace_membership",
            AsyncMock(return_value=False),
        )

        await _drive(_User())

        group_add.assert_not_awaited()


class TestARejectedSocketDoesNotTouchTheBroker:
    """Accepting before the verdict means Channels runs ``disconnect()`` for
    rejected sockets too, and that would discard a group they never joined.

    Harmless-looking until you notice where it lands hardest: when
    ``group_add`` has just failed because the broker is down, every rejected
    socket would add another call to the broker that is already failing.
    """

    @pytest.mark.asyncio
    async def test_a_policy_rejection_discards_no_group(self, monkeypatch) -> None:
        from channels.layers import get_channel_layer

        discard = AsyncMock()
        monkeypatch.setattr(get_channel_layer(), "group_discard", discard)

        await _drive(None)

        discard.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_broker_failure_does_not_call_it_again(self, monkeypatch) -> None:
        from channels.layers import get_channel_layer

        discard = AsyncMock()
        monkeypatch.setattr(get_channel_layer(), "group_discard", discard)
        monkeypatch.setattr(
            WorkspaceConsumer,
            "_check_workspace_membership",
            AsyncMock(return_value=True),
        )

        await _drive(_User(), group_add_error=ConnectionError("reset by peer"), monkeypatch=monkeypatch)

        discard.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_accepted_socket_still_cleans_up(self, monkeypatch) -> None:
        """The invariant that must survive: a socket that did join has to leave."""
        from channels.layers import get_channel_layer

        discard = AsyncMock()
        monkeypatch.setattr(get_channel_layer(), "group_add", AsyncMock())
        monkeypatch.setattr(get_channel_layer(), "group_discard", discard)
        monkeypatch.setattr(
            WorkspaceConsumer,
            "_check_workspace_membership",
            AsyncMock(return_value=True),
        )

        await _drive(_User())

        discard.assert_awaited()
