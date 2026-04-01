"""Tests for DT plugin server selection.

Verifies that DependencyTrackPlugin._select_dt_server correctly selects
a server, and that capacity is determined by actual mapping count
(not a fragile counter).
"""

from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin


class TestSelectDtServer:
    """Test _select_dt_server selection."""

    def test_returns_server(self) -> None:
        """_select_dt_server returns a server instance."""
        plugin = DependencyTrackPlugin(config={})
        mock_team = MagicMock()

        with patch(
            "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService.select_dependency_track_server"
        ) as mock_select:
            mock_select.return_value = MagicMock()
            mock_team.billing_plan = "business"

            server = plugin._select_dt_server(mock_team)

        assert server is not None


@pytest.mark.django_db
class TestTrackedObjectCount:
    """Test that capacity is based on actual mapping count."""

    def test_tracked_object_count(self) -> None:
        """tracked_object_count returns the number of release mappings."""
        from sbomify.apps.core.models import Product, Release
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import (
            DependencyTrackServer,
            ReleaseDependencyTrackMapping,
        )

        team = Team.objects.create(name="Test Team", key="test-team-count", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="Test Server",
            url="https://dt-count.example.com",
            api_key="key",
            health_status="healthy",
            max_concurrent_scans=10,
        )

        assert server.tracked_object_count == 0

        product = Product.objects.create(name="Test Product", team=team)
        release = Release.objects.create(name="v1.0", product=product)
        ReleaseDependencyTrackMapping.objects.create(
            release=release,
            dt_server=server,
            dt_project_uuid="00000000-0000-0000-0000-000000000001",
            dt_project_name="test-project",
        )

        assert server.tracked_object_count == 1
        assert server.is_available_for_scan is True

    def test_at_capacity(self) -> None:
        """is_available_for_scan returns False when at capacity."""
        from sbomify.apps.core.models import Product, Release
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import (
            DependencyTrackServer,
            ReleaseDependencyTrackMapping,
        )

        team = Team.objects.create(name="Test Team", key="test-team-cap", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="Test Server",
            url="https://dt-cap.example.com",
            api_key="key",
            health_status="healthy",
            max_concurrent_scans=1,
        )

        product = Product.objects.create(name="Test Product", team=team)
        release = Release.objects.create(name="v1.0", product=product)
        ReleaseDependencyTrackMapping.objects.create(
            release=release,
            dt_server=server,
            dt_project_uuid="00000000-0000-0000-0000-000000000001",
            dt_project_name="test-project",
        )

        assert server.tracked_object_count == 1
        assert server.is_available_for_scan is False
