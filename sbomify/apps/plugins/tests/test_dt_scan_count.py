"""Tests for DT plugin server selection and project naming.

Verifies that DependencyTrackPlugin._select_dt_server correctly selects
a server, that capacity is determined by actual mapping count
(not a fragile counter), and that the DT project naming follows the
DT-canonical one-project-per-component pattern.
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
        """tracked_object_count returns the number of component mappings."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import (
            ComponentDependencyTrackMapping,
            DependencyTrackServer,
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

        component = Component.objects.create(name="Test Component", team=team)
        ComponentDependencyTrackMapping.objects.create(
            component=component,
            dt_server=server,
            dt_project_uuid="00000000-0000-0000-0000-000000000001",
            dt_project_name="test-project",
        )

        assert server.tracked_object_count == 1
        assert server.is_available_for_scan is True

    def test_at_capacity(self) -> None:
        """is_available_for_scan returns False when at capacity."""
        from sbomify.apps.core.models import Component
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import (
            ComponentDependencyTrackMapping,
            DependencyTrackServer,
        )

        team = Team.objects.create(name="Test Team", key="test-team-cap", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="Test Server",
            url="https://dt-cap.example.com",
            api_key="key",
            health_status="healthy",
            max_concurrent_scans=1,
        )

        component = Component.objects.create(name="Test Component", team=team)
        ComponentDependencyTrackMapping.objects.create(
            component=component,
            dt_server=server,
            dt_project_uuid="00000000-0000-0000-0000-000000000001",
            dt_project_name="test-project",
        )

        assert server.tracked_object_count == 1
        assert server.is_available_for_scan is False


class TestUnsupportedFormatSkipped:
    """DT should return a skipped (not error) result when given a non-CycloneDX SBOM.

    SPDX is a deliberate format choice, not an error condition — DT simply doesn't
    support it. The UI/reporting layer should surface this as "not applicable"
    rather than a hard error finding.
    """

    def test_spdx_input_returns_skipped_not_error(self, tmp_path) -> None:
        """Passing an SPDX 2.3 SBOM to DT should yield a skipped result."""
        import json

        spdx_sbom = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {"created": "2026-01-01T00:00:00Z", "creators": ["Tool: test"]},
            "packages": [],
        }
        sbom_path = tmp_path / "test.spdx.json"
        sbom_path.write_text(json.dumps(spdx_sbom))

        plugin = DependencyTrackPlugin(config={})
        result = plugin.assess("sbom-id-does-not-matter", sbom_path)

        assert result.summary.error_count == 0, f"SPDX input should not produce errors, got {result.summary}"
        assert result.summary.warning_count == 1
        assert result.metadata.get("skipped") is True
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.id == "dependency-track:unsupported-format"
        assert finding.status == "warning"
        assert "skipped" in (finding.description or "").lower()

    def test_unrecognized_format_also_returns_skipped(self, tmp_path) -> None:
        """Anything that isn't valid CycloneDX (random JSON, truncated file, etc.)
        should skip rather than error. The old behavior returned a hard error for
        anything that failed _validate_cyclonedx — we want that path to remain
        user-friendly for non-CycloneDX input of any kind."""
        import json

        garbage = {"hello": "world", "notAnSBOM": True}
        sbom_path = tmp_path / "garbage.json"
        sbom_path.write_text(json.dumps(garbage))

        plugin = DependencyTrackPlugin(config={})
        result = plugin.assess("sbom-id", sbom_path)

        assert result.summary.error_count == 0
        assert result.summary.warning_count == 1
        assert result.metadata.get("skipped") is True
        assert result.findings[0].id == "dependency-track:unsupported-format"
