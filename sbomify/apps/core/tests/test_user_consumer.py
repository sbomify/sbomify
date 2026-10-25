"""The user channel: news addressed to one signed-in person, wherever they are."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sbomify.apps.core.consumers import WS_CLOSE_POLICY_VIOLATION, WS_CLOSE_SERVICE_RESTART
from sbomify.apps.core.user_consumer import UserConsumer
from sbomify.apps.core.utils import broadcast_to_user


def _consumer(user) -> UserConsumer:
    consumer = UserConsumer()
    consumer.scope = {"url_route": {"kwargs": {}}, "user": user}
    consumer.channel_layer = MagicMock(group_add=AsyncMock(), group_discard=AsyncMock())
    consumer.channel_name = "test-channel"
    consumer.accept = AsyncMock()
    consumer.close = AsyncMock()
    return consumer


def _user(user_id: int = 7, authenticated: bool = True) -> MagicMock:
    user = MagicMock()
    user.is_authenticated = authenticated
    user.id = user_id
    return user


@pytest.mark.asyncio
async def test_a_signed_in_user_joins_only_their_own_group() -> None:
    consumer = _consumer(_user(7))

    await consumer.connect()

    consumer.close.assert_not_called()
    consumer.channel_layer.group_add.assert_called_once_with("user_7", "test-channel")


@pytest.mark.asyncio
async def test_a_visitor_who_is_not_signed_in_is_refused() -> None:
    consumer = _consumer(_user(authenticated=False))

    await consumer.connect()

    consumer.close.assert_called_once_with(code=WS_CLOSE_POLICY_VIOLATION)
    consumer.channel_layer.group_add.assert_not_called()


@pytest.mark.asyncio
async def test_a_broker_outage_asks_the_client_to_retry() -> None:
    consumer = _consumer(_user(7))
    consumer.channel_layer.group_add = AsyncMock(side_effect=ConnectionError("down"))

    await consumer.connect()

    consumer.close.assert_called_once_with(code=WS_CLOSE_SERVICE_RESTART)


@pytest.mark.asyncio
async def test_it_leaves_its_group_on_disconnect() -> None:
    consumer = _consumer(_user(7))
    await consumer.connect()

    await consumer.disconnect(1000)

    consumer.channel_layer.group_discard.assert_called_once_with("user_7", "test-channel")


def test_broadcast_to_user_reaches_that_users_group() -> None:
    layer = MagicMock(group_send=AsyncMock())
    with patch("sbomify.apps.core.utils.get_channel_layer", return_value=layer):
        assert broadcast_to_user(7, "access_request_updated", {"status": "approved"})

    layer.group_send.assert_called_once_with(
        "user_7",
        {"type": "workspace_message", "data": {"type": "access_request_updated", "status": "approved"}},
    )


def test_broadcast_to_user_without_a_channel_layer_is_a_no_op() -> None:
    with patch("sbomify.apps.core.utils.get_channel_layer", return_value=None):
        assert not broadcast_to_user(7, "access_request_updated")
