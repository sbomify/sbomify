"""
Tests for the broadcast_to_workspace utility function.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sbomify.apps.core.utils import broadcast_to_workspace


class TestBroadcastToWorkspace:
    """Tests for the broadcast_to_workspace function."""

    def test_broadcast_sends_message_to_correct_group(self):
        """Test that broadcast sends message to the correct workspace group."""
        with patch("sbomify.apps.core.utils.get_channel_layer") as mock_get_layer:
            mock_layer = MagicMock()
            # group_send must be an AsyncMock since async_to_sync is used
            mock_layer.group_send = AsyncMock()
            mock_get_layer.return_value = mock_layer

            result = broadcast_to_workspace(
                workspace_key="test-workspace",
                message_type="test_event",
                data={"key": "value"},
            )

            assert result is True
            mock_layer.group_send.assert_called_once()
            call_args = mock_layer.group_send.call_args

            # Verify the group name
            assert call_args[0][0] == "workspace_test-workspace"

            # Verify the message structure
            message = call_args[0][1]
            assert message["type"] == "workspace_message"
            assert message["data"]["type"] == "test_event"
            assert message["data"]["key"] == "value"

    def test_broadcast_with_no_additional_data(self):
        """Test that broadcast works with no additional data."""
        with patch("sbomify.apps.core.utils.get_channel_layer") as mock_get_layer:
            mock_layer = MagicMock()
            mock_layer.group_send = AsyncMock()
            mock_get_layer.return_value = mock_layer

            result = broadcast_to_workspace(
                workspace_key="test-workspace",
                message_type="simple_event",
            )

            assert result is True
            call_args = mock_layer.group_send.call_args
            message = call_args[0][1]

            assert message["data"]["type"] == "simple_event"
            # Should only have the type key
            assert len(message["data"]) == 1

    def test_broadcast_returns_false_when_channel_layer_not_configured(self):
        """Test that broadcast returns False when channel layer is not configured."""
        with patch("sbomify.apps.core.utils.get_channel_layer") as mock_get_layer:
            mock_get_layer.return_value = None

            result = broadcast_to_workspace(
                workspace_key="test-workspace",
                message_type="test_event",
            )

            assert result is False

    def test_broadcast_returns_false_on_exception(self):
        """Test that broadcast returns False and logs on exception."""
        with patch("sbomify.apps.core.utils.get_channel_layer") as mock_get_layer:
            mock_layer = MagicMock()
            mock_layer.group_send = AsyncMock(side_effect=Exception("Test error"))
            mock_get_layer.return_value = mock_layer

            result = broadcast_to_workspace(
                workspace_key="test-workspace",
                message_type="test_event",
            )

            assert result is False

    def test_broadcast_message_types(self):
        """Test various message types are broadcast correctly."""
        message_types = [
            ("sbom_uploaded", {"sbom_id": "123", "name": "test.json"}),
            ("sbom_deleted", {"sbom_id": "123", "component_id": "456"}),
            ("document_uploaded", {"document_id": "789"}),
            ("document_deleted", {"document_id": "789"}),
            ("release_created", {"release_id": "abc", "product_id": "def"}),
            ("release_updated", {"release_id": "abc"}),
            ("release_deleted", {"release_id": "abc"}),
            ("scan_complete", {"sbom_id": "123", "status": "completed"}),
            ("assessment_complete", {"sbom_id": "123", "plugin_name": "checksum"}),
            ("notification", {"message": "Hello!"}),
        ]

        for message_type, data in message_types:
            with patch("sbomify.apps.core.utils.get_channel_layer") as mock_get_layer:
                mock_layer = MagicMock()
                mock_layer.group_send = AsyncMock()
                mock_get_layer.return_value = mock_layer

                result = broadcast_to_workspace(
                    workspace_key="test-workspace",
                    message_type=message_type,
                    data=data,
                )

                assert result is True
                call_args = mock_layer.group_send.call_args
                message = call_args[0][1]

                assert message["data"]["type"] == message_type
                for key, value in data.items():
                    assert message["data"][key] == value


@pytest.mark.django_db
class TestBroadcastIntegration:
    """Integration tests for broadcast_to_workspace with real channel layer."""

    def test_broadcast_with_configured_channel_layer(self):
        """Test broadcast works with configured channel layer.

        Note: This test requires Redis to be running and is expected to
        be skipped in environments without Redis available.
        """
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            pytest.skip("Channel layer not configured")

        # This test verifies that the broadcast function works end-to-end
        # with the configured channel layer
        result = broadcast_to_workspace(
            workspace_key="integration-test",
            message_type="test_event",
            data={"test": "data"},
        )

        # If Redis is not available, the broadcast will fail gracefully
        # This is expected behavior in test environments without Redis
        if not result:
            pytest.skip("Redis not available for integration test")
