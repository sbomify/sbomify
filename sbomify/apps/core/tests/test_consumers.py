"""
Tests for WebSocket consumers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sbomify.apps.core.consumers import WorkspaceConsumer


class TestWorkspaceConsumer:
    """Tests for the WorkspaceConsumer."""

    @pytest.fixture
    def consumer(self):
        """Create a consumer instance for testing."""
        return WorkspaceConsumer()

    @pytest.fixture
    def mock_channel_layer(self):
        """Create a mock channel layer."""
        layer = MagicMock()
        layer.group_add = AsyncMock()
        layer.group_discard = AsyncMock()
        layer.group_send = AsyncMock()
        return layer

    @pytest.mark.asyncio
    async def test_connect_unauthenticated_user_rejected(self, consumer, mock_channel_layer):
        """Test that unauthenticated users are rejected."""
        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": None,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        await consumer.connect()

        consumer.close.assert_called_once()
        consumer.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_anonymous_user_rejected(self, consumer, mock_channel_layer):
        """Test that anonymous users are rejected."""
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        await consumer.connect()

        consumer.close.assert_called_once()
        consumer.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_authenticated_user_accepted(self, consumer, mock_channel_layer):
        """Test that authenticated workspace members can connect."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        # Mock the membership check to return True
        consumer._check_workspace_membership = AsyncMock(return_value=True)

        await consumer.connect()

        consumer.accept.assert_called_once()
        consumer.close.assert_not_called()
        mock_channel_layer.group_add.assert_called_once_with(
            "workspace_test-workspace", "test-channel"
        )

    @pytest.mark.asyncio
    async def test_connect_non_member_rejected(self, consumer, mock_channel_layer):
        """Test that authenticated users who are not workspace members are rejected."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        # Mock the membership check to return False
        consumer._check_workspace_membership = AsyncMock(return_value=False)

        await consumer.connect()

        consumer.close.assert_called_once()
        consumer.accept.assert_not_called()
        mock_channel_layer.group_add.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_sets_workspace_key_and_group_name(self, consumer, mock_channel_layer):
        """Test that connect sets the workspace_key and group_name."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "my-team-key"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.accept = AsyncMock()
        consumer._check_workspace_membership = AsyncMock(return_value=True)

        await consumer.connect()

        assert consumer.workspace_key == "my-team-key"
        assert consumer.group_name == "workspace_my-team-key"

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_group(self, consumer, mock_channel_layer):
        """Test that disconnect removes the channel from the group."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 123

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.group_name = "workspace_test-workspace"

        await consumer.disconnect(1000)

        mock_channel_layer.group_discard.assert_called_once_with(
            "workspace_test-workspace", "test-channel"
        )

    @pytest.mark.asyncio
    async def test_disconnect_without_group_name(self, consumer, mock_channel_layer):
        """Test that disconnect handles missing group_name gracefully."""
        mock_user = MagicMock()
        mock_user.is_authenticated = False

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "test-workspace"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        # group_name not set (connection was rejected)

        # Should not raise an exception
        await consumer.disconnect(1006)

        # group_discard should not be called since there's no group_name
        mock_channel_layer.group_discard.assert_not_called()

    @pytest.mark.asyncio
    async def test_workspace_message_sends_data(self, consumer, mock_channel_layer):
        """Test that workspace_message sends data to the client."""
        consumer.send_json = AsyncMock()

        event = {
            "type": "workspace_message",
            "data": {
                "type": "sbom_uploaded",
                "sbom_id": "123",
                "name": "test.json",
            },
        }

        await consumer.workspace_message(event)

        consumer.send_json.assert_called_once_with(event["data"])

    @pytest.mark.asyncio
    async def test_workspace_message_different_event_types(self, consumer):
        """Test workspace_message handles different event types."""
        consumer.send_json = AsyncMock()

        event_types = [
            {"type": "sbom_uploaded", "sbom_id": "123"},
            {"type": "sbom_deleted", "sbom_id": "456"},
            {"type": "document_uploaded", "document_id": "789"},
            {"type": "scan_complete", "sbom_id": "123", "status": "completed"},
            {"type": "assessment_complete", "sbom_id": "123", "plugin_name": "checksum"},
            {"type": "notification", "message": "Hello!"},
        ]

        for data in event_types:
            consumer.send_json.reset_mock()
            event = {"type": "workspace_message", "data": data}
            await consumer.workspace_message(event)
            consumer.send_json.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_receive_json_logs_unexpected_message(self, consumer):
        """Test that receive_json logs unexpected client messages."""
        with patch("sbomify.apps.core.consumers.logger") as mock_logger:
            await consumer.receive_json({"action": "ping"})
            mock_logger.debug.assert_called()


class TestWorkspaceConsumerGroupBroadcast:
    """Tests for group broadcast functionality."""

    @pytest.mark.asyncio
    async def test_group_name_format(self):
        """Test that group names are formatted correctly."""
        consumer = WorkspaceConsumer()
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 1

        mock_channel_layer = MagicMock()
        mock_channel_layer.group_add = AsyncMock()

        consumer.scope = {
            "url_route": {"kwargs": {"workspace_key": "abc-123-def"}},
            "user": mock_user,
        }
        consumer.channel_layer = mock_channel_layer
        consumer.channel_name = "test-channel"
        consumer.accept = AsyncMock()
        consumer._check_workspace_membership = AsyncMock(return_value=True)

        await consumer.connect()

        # Verify the group name format
        assert consumer.group_name == "workspace_abc-123-def"
        mock_channel_layer.group_add.assert_called_with(
            "workspace_abc-123-def", "test-channel"
        )
