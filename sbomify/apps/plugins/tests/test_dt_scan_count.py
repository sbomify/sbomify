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


@pytest.mark.django_db
class TestDependencyTrackProjectNaming:
    """Verify the DT-canonical one-project-per-component naming pattern.

    DT Best Practices and issue #695 recommend: one DT project per logical
    component, with multiple versions inside — one per release. This test
    class asserts that _get_or_create_mapping_and_upload always produces
    project_name = '{env}-sbomify-{product}-{component}' (independent of
    release name) and project_version = release.name.
    """

    def _make_env(self):
        """Create team, product, component, DT server."""
        from sbomify.apps.core.models import Component, Product
        from sbomify.apps.teams.models import Team
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        team = Team.objects.create(name="DT Naming Team", key="dt-naming", billing_plan="business")
        product = Product.objects.create(name="My Product", team=team)
        component = Component.objects.create(name="my-service", team=team)
        server = DependencyTrackServer.objects.create(
            name="Naming Test Server",
            url="https://dt-naming.example.com",
            api_key="key",
            health_status="healthy",
        )
        return team, product, component, server

    def _make_sbom(self, component, disconnect_signal=True):
        """Create a minimal CycloneDX SBOM for the component."""
        from django.db.models.signals import post_save

        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.sboms.signals import trigger_plugin_assessments

        if disconnect_signal:
            post_save.disconnect(trigger_plugin_assessments, sender=SBOM)
        try:
            sbom = SBOM.objects.create(name="test-sbom", component=component, format="cyclonedx")
        finally:
            if disconnect_signal:
                post_save.connect(trigger_plugin_assessments, sender=SBOM)
        return sbom

    def test_project_name_uses_product_and_component_not_release(self):
        """project_name encodes product+component; release.name becomes project_version."""
        from sbomify.apps.core.models import Release

        team, product, component, server = self._make_env()
        release = Release.objects.create(name="v1.0.0", product=product)
        sbom = self._make_sbom(component)

        plugin = DependencyTrackPlugin(config={})
        captured: list[dict] = []

        def fake_upload_with_project_creation(*, project_name, project_version, sbom_data, auto_create):
            captured.append({"project_name": project_name, "project_version": project_version})

        def fake_find_project(name, version):
            return {"uuid": "00000000-0000-0000-0000-000000000001"}

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload_with_project_creation
        mock_client.find_project_by_name_version.side_effect = fake_find_project

        with (
            patch(
                "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
                return_value=mock_client,
            ),
            patch(
                "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService._get_environment_prefix",
                return_value="dev",
            ),
        ):
            plugin._get_or_create_mapping_and_upload(release, sbom, b'{"bomFormat":"CycloneDX"}', server, None)

        assert len(captured) == 1
        assert captured[0]["project_name"] == "dev-sbomify-my-product-my-service"
        assert captured[0]["project_version"] == "v1.0.0"

    def test_same_component_multiple_releases_share_one_project(self):
        """Two named releases for the same component produce ONE DT project with two versions."""
        from sbomify.apps.core.models import Release
        from sbomify.apps.vulnerability_scanning.models import ComponentDependencyTrackMapping

        team, product, component, server = self._make_env()
        release_v1 = Release.objects.create(name="v1.0.0", product=product)
        release_v2 = Release.objects.create(name="v2.0.0", product=product)
        sbom = self._make_sbom(component)

        plugin = DependencyTrackPlugin(config={})

        captured_calls: list[dict] = []
        # Track which (name, version) pairs have been "uploaded" so the lookup mock
        # can model real DT behavior: 404 before upload, project dict after.
        uploaded_versions: set[tuple[str, str]] = set()
        next_uuid = [0]

        def fake_upload_with_project_creation(*, project_name, project_version, sbom_data, auto_create):
            captured_calls.append({"project_name": project_name, "project_version": project_version})
            uploaded_versions.add((project_name, project_version))

        def fake_find_project(name, version):
            if (name, version) not in uploaded_versions:
                return None
            next_uuid[0] += 1
            return {"uuid": f"00000000-0000-0000-0000-{next_uuid[0]:012d}"}

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload_with_project_creation
        mock_client.find_project_by_name_version.side_effect = fake_find_project

        with (
            patch(
                "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
                return_value=mock_client,
            ),
            patch(
                "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService._get_environment_prefix",
                return_value="dev",
            ),
        ):
            # First run: v1 — creates the mapping
            plugin._get_or_create_mapping_and_upload(release_v1, sbom, b'{"bomFormat":"CycloneDX"}', server, None)

            # Second run: v2 — reuses the existing mapping. v2.0.0 doesn't exist in DT yet,
            # so the lookup returns None and we upload it as a new project version inside
            # the same DT project as v1.
            existing = ComponentDependencyTrackMapping.objects.get(component=component, dt_server=server)
            plugin._get_or_create_mapping_and_upload(release_v2, sbom, b'{"bomFormat":"CycloneDX"}', server, existing)

        # Both calls share the same project_name
        assert len(captured_calls) == 2
        assert captured_calls[0]["project_name"] == captured_calls[1]["project_name"], (
            "Both releases must map to the same DT project"
        )
        # But each call uses a different version
        assert captured_calls[0]["project_version"] == "v1.0.0"
        assert captured_calls[1]["project_version"] == "v2.0.0"

        # Only ONE mapping row exists in the DB
        assert ComponentDependencyTrackMapping.objects.filter(component=component, dt_server=server).count() == 1

    def test_category_a_customer_uses_latest_as_version(self):
        """Category A customer (no named releases) gets project_version='latest'."""
        from sbomify.apps.core.models import Release

        team, product, component, server = self._make_env()
        # Category A: auto-maintained 'latest' release (is_latest=True)
        latest_release = Release.objects.create(name="latest", product=product, is_latest=True)
        sbom = self._make_sbom(component)

        plugin = DependencyTrackPlugin(config={})
        captured: list[dict] = []

        def fake_upload_with_project_creation(*, project_name, project_version, sbom_data, auto_create):
            captured.append({"project_name": project_name, "project_version": project_version})

        def fake_find_project(name, version):
            return {"uuid": "00000000-0000-0000-0000-000000000001"}

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload_with_project_creation
        mock_client.find_project_by_name_version.side_effect = fake_find_project

        with (
            patch(
                "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
                return_value=mock_client,
            ),
            patch(
                "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService._get_environment_prefix",
                return_value="dev",
            ),
        ):
            plugin._get_or_create_mapping_and_upload(latest_release, sbom, b'{"bomFormat":"CycloneDX"}', server, None)

        assert len(captured) == 1
        # Category A: version is 'latest' (the auto-release name)
        assert captured[0]["project_version"] == "latest"
        # project_name encodes component, NOT the release name
        assert "latest" not in captured[0]["project_name"]
        assert "my-service" in captured[0]["project_name"]

    def test_fresh_mapping_does_not_short_circuit_second_release_upload(self):
        """Regression test for two related per-release upload bugs:

        1. Pre-refactor: a 24-hour staleness check on existing_mapping.last_sbom_upload
           silently dropped a named-release upload when it followed a 'latest' upload
           within the window. (mapping is per-component, not per-release.)
        2. Post-refactor (lookup-based): the plugin must distinguish "fresh release
           we haven't uploaded yet — upload it" from "we already uploaded this version
           — go straight to polling". The lookup against DT decides which path to take.

        This test repros the timing: latest upload, then v1.0.0 upload using the same
        mapping. v1.0.0 must reach the upload client (it's a new project version that
        DT doesn't know about yet).
        """
        from sbomify.apps.core.models import Release
        from sbomify.apps.vulnerability_scanning.models import ComponentDependencyTrackMapping

        team, product, component, server = self._make_env()
        latest_release = Release.objects.create(name="latest", product=product, is_latest=True)
        named_release = Release.objects.create(name="v1.0.0", product=product)
        sbom = self._make_sbom(component)

        plugin = DependencyTrackPlugin(config={})
        captured: list[dict] = []
        # Model real DT behavior in the lookup mock: 404 before upload, dict after.
        uploaded_versions: set[tuple[str, str]] = set()
        next_uuid = [0]

        def fake_upload_with_project_creation(*, project_name, project_version, sbom_data, auto_create):
            captured.append({"project_name": project_name, "project_version": project_version})
            uploaded_versions.add((project_name, project_version))

        def fake_find_project(name, version):
            if (name, version) not in uploaded_versions:
                return None
            next_uuid[0] += 1
            return {"uuid": f"00000000-0000-0000-0000-{next_uuid[0]:012d}"}

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload_with_project_creation
        mock_client.find_project_by_name_version.side_effect = fake_find_project

        with (
            patch(
                "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
                return_value=mock_client,
            ),
            patch(
                "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService._get_environment_prefix",
                return_value="dev",
            ),
        ):
            # First call: 'latest' upload — creates the mapping.
            plugin._get_or_create_mapping_and_upload(
                latest_release, sbom, b'{"bomFormat":"CycloneDX"}', server, None
            )

            # The mapping is now fresh; v1.0.0 doesn't exist in DT yet so the lookup
            # returns None and the plugin must upload it (NOT short-circuit on freshness).
            existing = ComponentDependencyTrackMapping.objects.get(component=component, dt_server=server)
            assert existing.last_sbom_upload is not None, "First upload should have set the timestamp"

            plugin._get_or_create_mapping_and_upload(
                named_release, sbom, b'{"bomFormat":"CycloneDX"}', server, existing
            )

        # Both uploads MUST have reached the DT client.
        assert len(captured) == 2, (
            f"Expected 2 uploads (latest + v1.0.0), got {len(captured)}. "
            "If this is 1, the existing_mapping branch is short-circuiting per-release "
            "uploads and Category B customers' named-release uploads will be silently dropped."
        )
        # Same project, two distinct versions
        assert captured[0]["project_name"] == captured[1]["project_name"]
        assert captured[0]["project_version"] == "latest"
        assert captured[1]["project_version"] == "v1.0.0"

    def test_existing_release_version_skips_reupload_and_returns_for_polling(self):
        """When a (project, release-version) pair already exists in DT, skip re-upload.

        This is the retry path: the orchestrator re-runs the plugin after the first
        RetryLater raise, and the plugin should fetch metrics this time, not push the
        same BOM again. The lookup against DT decides upload vs poll.
        """
        from sbomify.apps.core.models import Release
        from sbomify.apps.vulnerability_scanning.models import ComponentDependencyTrackMapping

        team, product, component, server = self._make_env()
        named_release = Release.objects.create(name="v1.0.0", product=product)
        sbom = self._make_sbom(component)

        plugin = DependencyTrackPlugin(config={})
        captured: list[dict] = []
        # Simulate that v1.0.0 ALREADY exists in DT (the retry case).
        next_uuid = [0]

        def fake_upload_with_project_creation(*, project_name, project_version, sbom_data, auto_create):
            captured.append({"project_name": project_name, "project_version": project_version})

        def fake_find_project(name, version):
            next_uuid[0] += 1
            return {"uuid": f"00000000-0000-0000-0000-{next_uuid[0]:012d}"}

        mock_client = MagicMock()
        mock_client.upload_sbom_with_project_creation.side_effect = fake_upload_with_project_creation
        mock_client.find_project_by_name_version.side_effect = fake_find_project

        # Pre-create a mapping as if a previous run had already created it.
        existing = ComponentDependencyTrackMapping.objects.create(
            component=component,
            dt_server=server,
            dt_project_uuid="00000000-0000-0000-0000-000000000099",
            dt_project_name="dev-sbomify-my-product-my-service",
        )

        with patch(
            "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient",
            return_value=mock_client,
        ):
            mapping, just_uploaded = plugin._get_or_create_mapping_and_upload(
                named_release, sbom, b'{"bomFormat":"CycloneDX"}', server, existing
            )

        assert mapping is existing
        assert just_uploaded is False, (
            "When DT already has the (project, version) pair, plugin must signal "
            "just_uploaded=False so the assess() flow goes to polling instead of "
            "raising RetryLater again."
        )
        assert len(captured) == 0, (
            f"Plugin must NOT re-upload when DT already has the version. "
            f"Got {len(captured)} upload calls."
        )
