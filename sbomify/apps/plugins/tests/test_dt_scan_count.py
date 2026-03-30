"""Tests for DT plugin scan count management.

Verifies that DependencyTrackServer.current_scan_count is correctly
incremented and decremented across all exit paths in the DT plugin.
"""

from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin


class TestSafeDecrement:
    """Test _safe_decrement helper."""

    def test_decrements_when_should_decrement_is_true(self):
        server = MagicMock()
        DependencyTrackPlugin._safe_decrement(server, True)
        server.decrement_scan_count.assert_called_once()

    def test_skips_when_should_decrement_is_false(self):
        server = MagicMock()
        DependencyTrackPlugin._safe_decrement(server, False)
        server.decrement_scan_count.assert_not_called()

    def test_skips_when_server_is_none(self):
        # Should not raise
        DependencyTrackPlugin._safe_decrement(None, True)

    def test_swallows_db_error(self):
        server = MagicMock()
        server.decrement_scan_count.side_effect = Exception("DB connection lost")
        server.id = "test-server-id"
        # Should not raise
        DependencyTrackPlugin._safe_decrement(server, True)
        server.decrement_scan_count.assert_called_once()


class TestSelectDtServer:
    """Test _select_dt_server increment tracking."""

    def test_returns_tuple_with_increment_flag(self):
        """_select_dt_server returns (server, was_incremented) tuple."""
        plugin = DependencyTrackPlugin(config={})
        mock_team = MagicMock()

        with patch("sbomify.apps.plugins.builtins.dependency_track.VulnerabilityScanningService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.select_dependency_track_server.return_value = MagicMock()
            # Ensure enterprise path is skipped
            mock_team.billing_plan = "business"

            server, incremented = plugin._select_dt_server(mock_team)

        assert server is not None
        assert incremented is True  # Pool selection increments


@pytest.mark.django_db
class TestCleanupDtScanCount:
    """Test _cleanup_dt_scan_count in task layer."""

    def test_cleanup_handles_no_release(self):
        """Cleanup should not crash when SBOM has no release."""
        from sbomify.apps.plugins.tasks import _cleanup_dt_scan_count

        # Non-existent SBOM ID — should handle gracefully
        _cleanup_dt_scan_count("nonexistent-sbom-id")

    def test_cleanup_handles_exception(self):
        """Cleanup should swallow exceptions and not crash the task."""
        from sbomify.apps.plugins.tasks import _cleanup_dt_scan_count

        with patch("sbomify.apps.plugins.tasks.Release.objects") as mock_qs:
            mock_qs.filter.side_effect = Exception("DB error")
            # Should not raise
            _cleanup_dt_scan_count("test-sbom-id")
