"""Tests for the generic plugin configuration UI system."""

import uuid
from unittest.mock import patch

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.apis import (
    _resolve_config_schema,
    _resolve_dt_servers,
    get_team_plugin_settings,
)
from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.teams.models import Team


@pytest.fixture
def test_team(db) -> Team:
    """Create a test team."""
    BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business",
            "max_products": 10,
            "max_projects": 10,
            "max_components": 100,
            "max_users": 10,
        },
    )
    team = Team.objects.create(name="Config Test Team", billing_plan="business")
    yield team
    team.delete()


@pytest.fixture
def enterprise_team(db) -> Team:
    """Create a test team with enterprise billing plan."""
    BillingPlan.objects.get_or_create(
        key="enterprise",
        defaults={
            "name": "Enterprise",
            "max_products": 100,
            "max_projects": 100,
            "max_components": 1000,
            "max_users": 100,
        },
    )
    team = Team.objects.create(name="Enterprise Test Team", billing_plan="enterprise")
    yield team
    team.delete()


@pytest.fixture
def plugin_with_schema(db) -> RegisteredPlugin:
    """Create a plugin with config schema."""
    plugin = RegisteredPlugin.objects.create(
        name="test-plugin",
        display_name="Test Plugin",
        description="A test plugin with config schema",
        category=AssessmentCategory.SECURITY.value,
        version="1.0.0",
        plugin_class_path="test.path.TestPlugin",
        is_enabled=True,
        config_schema=[
            {
                "key": "server_id",
                "label": "Server",
                "type": "select",
                "required": False,
                "help_text": "Select a server.",
                "choices_source": "dt_servers",
            },
        ],
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def plugin_with_static_choices(db) -> RegisteredPlugin:
    """Create a plugin with static choices in config schema."""
    plugin = RegisteredPlugin.objects.create(
        name="static-plugin",
        display_name="Static Plugin",
        description="A plugin with static choices",
        category=AssessmentCategory.COMPLIANCE.value,
        version="1.0.0",
        plugin_class_path="test.path.StaticPlugin",
        is_enabled=True,
        config_schema=[
            {
                "key": "mode",
                "label": "Mode",
                "type": "select",
                "required": False,
                "help_text": "Select a mode.",
                "choices": [
                    {"value": "strict", "label": "Strict"},
                    {"value": "lenient", "label": "Lenient"},
                ],
            },
            {
                "key": "timeout",
                "label": "Timeout",
                "type": "number",
                "required": False,
                "help_text": "Timeout in seconds.",
            },
            {
                "key": "verbose",
                "label": "Verbose Output",
                "type": "boolean",
                "required": False,
                "help_text": "Enable verbose output.",
            },
        ],
    )
    yield plugin
    plugin.delete()


@pytest.mark.django_db
class TestResolveConfigSchema:
    """Tests for _resolve_config_schema."""

    def test_resolves_dynamic_choices(self) -> None:
        """Test that choices_source is resolved to choices list."""
        schema = [
            {
                "key": "server_id",
                "label": "Server",
                "type": "select",
                "choices_source": "dt_servers",
            },
        ]

        with patch(
            "sbomify.apps.plugins.apis._resolve_dt_servers",
            return_value=[{"value": "1", "label": "Server 1"}],
        ):
            from sbomify.apps.plugins.apis import CHOICE_RESOLVERS

            original = CHOICE_RESOLVERS["dt_servers"]
            CHOICE_RESOLVERS["dt_servers"] = lambda **kwargs: [{"value": "1", "label": "Server 1"}]
            try:
                resolved = _resolve_config_schema(schema)
            finally:
                CHOICE_RESOLVERS["dt_servers"] = original

        assert len(resolved) == 1
        assert "choices_source" not in resolved[0]
        assert resolved[0]["choices"] == [{"value": "1", "label": "Server 1"}]

    def test_preserves_static_choices(self) -> None:
        """Test that static choices are preserved unchanged."""
        schema = [
            {
                "key": "mode",
                "label": "Mode",
                "type": "select",
                "choices": [
                    {"value": "a", "label": "A"},
                    {"value": "b", "label": "B"},
                ],
            },
        ]

        resolved = _resolve_config_schema(schema)

        assert len(resolved) == 1
        assert resolved[0]["choices"] == [
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ]

    def test_handles_non_select_fields(self) -> None:
        """Test that non-select fields pass through unchanged."""
        schema = [
            {"key": "timeout", "label": "Timeout", "type": "number"},
            {"key": "name", "label": "Name", "type": "text"},
            {"key": "enabled", "label": "Enabled", "type": "boolean"},
        ]

        resolved = _resolve_config_schema(schema)

        assert len(resolved) == 3
        assert resolved[0] == {"key": "timeout", "label": "Timeout", "type": "number"}

    def test_handles_empty_schema(self) -> None:
        """Test that empty schema returns empty list."""
        assert _resolve_config_schema([]) == []

    def test_handles_unknown_choices_source(self) -> None:
        """Test that unknown choices_source is removed without adding choices."""
        schema = [
            {
                "key": "thing",
                "label": "Thing",
                "type": "select",
                "choices_source": "nonexistent_resolver",
            },
        ]

        resolved = _resolve_config_schema(schema)

        assert len(resolved) == 1
        assert "choices_source" not in resolved[0]
        assert "choices" not in resolved[0]

    def test_does_not_mutate_input(self) -> None:
        """Test that the input schema is not mutated."""
        schema = [
            {
                "key": "server_id",
                "label": "Server",
                "type": "select",
                "choices_source": "dt_servers",
            },
        ]

        from sbomify.apps.plugins.apis import CHOICE_RESOLVERS

        original = CHOICE_RESOLVERS.get("dt_servers")
        CHOICE_RESOLVERS["dt_servers"] = lambda **kwargs: [{"value": "1", "label": "S1"}]
        try:
            _resolve_config_schema(schema)
        finally:
            if original:
                CHOICE_RESOLVERS["dt_servers"] = original

        assert "choices_source" in schema[0]
        assert "choices" not in schema[0]


@pytest.mark.django_db
class TestResolveDtServers:
    """Tests for _resolve_dt_servers."""

    def test_returns_active_servers_for_enterprise(self, enterprise_team: Team) -> None:
        """Test that active DT servers are returned for enterprise teams."""
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        server = DependencyTrackServer.objects.create(
            name="Test DT Server",
            url="https://dt.example.com",
            api_key="test-key",
            is_active=True,
        )
        try:
            result = _resolve_dt_servers(team=enterprise_team)
            assert any(c["value"] == str(server.id) and c["label"] == "Test DT Server" for c in result)
        finally:
            server.delete()

    def test_returns_empty_for_non_enterprise(self, test_team: Team) -> None:
        """Test that non-enterprise teams get no server choices."""
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        server = DependencyTrackServer.objects.create(
            name="Test DT Server",
            url="https://dt.example.com",
            api_key="test-key",
            is_active=True,
        )
        try:
            result = _resolve_dt_servers(team=test_team)
            assert result == []
        finally:
            server.delete()

    def test_returns_empty_when_no_team(self) -> None:
        """Test that no team returns no server choices."""
        result = _resolve_dt_servers()
        assert result == []

    def test_excludes_inactive_servers(self, enterprise_team: Team) -> None:
        """Test that inactive DT servers are excluded."""
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        server = DependencyTrackServer.objects.create(
            name="Inactive Server",
            url="https://inactive.example.com",
            api_key="test-key",
            is_active=False,
        )
        try:
            result = _resolve_dt_servers(team=enterprise_team)
            assert not any(c["value"] == str(server.id) for c in result)
        finally:
            server.delete()

    def test_uses_name_as_label(self, enterprise_team: Team) -> None:
        """Test that server name is used as label (never exposing URL)."""
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        server = DependencyTrackServer.objects.create(
            name="My DT Server",
            url="https://dt-secret.example.com",
            api_key="test-key",
            is_active=True,
        )
        try:
            result = _resolve_dt_servers(team=enterprise_team)
            matching = [c for c in result if c["value"] == str(server.id)]
            assert len(matching) == 1
            assert matching[0]["label"] == "My DT Server"
        finally:
            server.delete()


@pytest.mark.django_db
class TestPluginSettingsWithSchema:
    """Tests for plugin settings API including config_schema."""

    def test_config_schema_included_in_available_plugins(
        self, test_team: Team, plugin_with_schema: RegisteredPlugin
    ) -> None:
        """Test that config_schema is included in available plugins response."""
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = type("User", (), {"is_authenticated": True})()

        status_code, data = get_team_plugin_settings(request, test_team.key)

        assert status_code == 200
        plugin_data = next(p for p in data["available_plugins"] if p["name"] == "test-plugin")
        assert "config_schema" in plugin_data
        assert len(plugin_data["config_schema"]) == 1
        assert plugin_data["config_schema"][0]["key"] == "server_id"
        # choices_source should be resolved (removed)
        assert "choices_source" not in plugin_data["config_schema"][0]

    def test_empty_config_schema(self, test_team: Team) -> None:
        """Test that plugins with no config_schema return empty list."""
        plugin = RegisteredPlugin.objects.create(
            name="no-config-plugin",
            display_name="No Config Plugin",
            description="No config",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="test.path.Plugin",
            is_enabled=True,
        )

        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = type("User", (), {"is_authenticated": True})()

        try:
            status_code, data = get_team_plugin_settings(request, test_team.key)
            plugin_data = next(p for p in data["available_plugins"] if p["name"] == "no-config-plugin")
            assert plugin_data["config_schema"] == []
        finally:
            plugin.delete()


@pytest.mark.django_db
class TestViewPostPluginConfig:
    """Tests for view POST handler correctly parsing plugin configs."""

    @pytest.fixture
    def dt_plugin(self, db) -> RegisteredPlugin:
        """Ensure dependency-track plugin is registered."""
        plugin, _ = RegisteredPlugin.objects.get_or_create(
            name="dependency-track",
            defaults={
                "display_name": "Dependency Track",
                "category": AssessmentCategory.SECURITY.value,
                "version": "1.0.0",
                "plugin_class_path": "test.path.DTPlugin",
                "is_enabled": True,
            },
        )
        return plugin

    def test_post_handler_parses_config(self, test_team: Team, dt_plugin) -> None:
        """Test that plugin config is correctly parsed from POST data."""
        from django.test import RequestFactory

        from sbomify.apps.plugins.apis import UpdateTeamPluginSettingsRequest, update_team_plugin_settings

        payload = UpdateTeamPluginSettingsRequest(
            enabled_plugins=["dependency-track"],
            plugin_configs={"dependency-track": {"dt_server_id": str(uuid.uuid4())}},
        )

        request = RequestFactory().post("/")
        request.user = type("User", (), {"is_authenticated": True})()

        status_code, result = update_team_plugin_settings(request, test_team.key, payload)

        assert status_code == 200
        settings = TeamPluginSettings.objects.get(team=test_team)
        assert "dependency-track" in settings.plugin_configs
        assert "dt_server_id" in settings.plugin_configs["dependency-track"]

    def test_post_handler_preserves_existing_config(self, test_team: Team, dt_plugin) -> None:
        """Test that config is updated correctly on subsequent saves."""
        from django.test import RequestFactory

        from sbomify.apps.plugins.apis import UpdateTeamPluginSettingsRequest, update_team_plugin_settings

        request = RequestFactory().post("/")
        request.user = type("User", (), {"is_authenticated": True})()

        server_id = str(uuid.uuid4())
        payload = UpdateTeamPluginSettingsRequest(
            enabled_plugins=["dependency-track"],
            plugin_configs={"dependency-track": {"dt_server_id": server_id}},
        )
        update_team_plugin_settings(request, test_team.key, payload)

        # Update again with different config
        new_server_id = str(uuid.uuid4())
        payload2 = UpdateTeamPluginSettingsRequest(
            enabled_plugins=["dependency-track"],
            plugin_configs={"dependency-track": {"dt_server_id": new_server_id}},
        )
        status_code, result = update_team_plugin_settings(request, test_team.key, payload2)

        assert status_code == 200
        settings = TeamPluginSettings.objects.get(team=test_team)
        assert settings.plugin_configs["dependency-track"]["dt_server_id"] == new_server_id


@pytest.mark.django_db
class TestDTPluginConfigIntegration:
    """Tests for DT plugin reading config from self.config."""

    def test_select_dt_server_with_config(self) -> None:
        """Test that _select_dt_server uses config override."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer

        server = DependencyTrackServer.objects.create(
            name="Custom DT Server",
            url="https://custom-dt.example.com",
            api_key="custom-key",
            is_active=True,
        )

        try:
            plugin = DependencyTrackPlugin(config={"dt_server_id": str(server.id)})
            team = type("Team", (), {"id": 1, "key": "test"})()

            selected = plugin._select_dt_server(team)
            assert selected.id == server.id
            assert selected.name == "Custom DT Server"
        finally:
            server.delete()

    def test_select_dt_server_falls_back_to_pool(self) -> None:
        """Test that _select_dt_server falls back to pool when no config."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        plugin = DependencyTrackPlugin(config={})
        team = type("Team", (), {"id": 1, "key": "test"})()

        with patch(
            "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService.select_dependency_track_server"
        ) as mock_select:
            mock_server = type("Server", (), {"id": uuid.uuid4(), "name": "Pool Server"})()
            mock_select.return_value = mock_server

            selected = plugin._select_dt_server(team)
            assert selected == mock_server
            mock_select.assert_called_once_with(team)

    def test_select_dt_server_falls_back_on_invalid_id(self) -> None:
        """Test that _select_dt_server falls back to pool when configured server doesn't exist."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        plugin = DependencyTrackPlugin(config={"dt_server_id": str(uuid.uuid4())})
        team = type("Team", (), {"id": 1, "key": "test"})()

        with patch(
            "sbomify.apps.vulnerability_scanning.services.VulnerabilityScanningService.select_dependency_track_server"
        ) as mock_select:
            mock_server = type("Server", (), {"id": uuid.uuid4(), "name": "Pool Server"})()
            mock_select.return_value = mock_server

            selected = plugin._select_dt_server(team)
            assert selected == mock_server

    def test_team_has_dt_enabled_via_plugin_settings(self, test_team: Team) -> None:
        """Test _team_has_dt_enabled checks TeamPluginSettings."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        plugin = DependencyTrackPlugin(config={})

        # No settings yet
        assert plugin._team_has_dt_enabled(test_team) is False

        # Create settings with DT enabled
        settings = TeamPluginSettings.objects.create(
            team=test_team,
            enabled_plugins=["dependency-track"],
        )

        assert plugin._team_has_dt_enabled(test_team) is True

        # Disable DT
        settings.enabled_plugins = ["osv"]
        settings.save()

        assert plugin._team_has_dt_enabled(test_team) is False

        settings.delete()


@pytest.mark.django_db
class TestHourlyDTScanTaskPluginSettings:
    """Tests for hourly_dt_scan_task using TeamPluginSettings."""

    @pytest.fixture
    def business_team(self, db) -> Team:
        """Create a business team."""
        BillingPlan.objects.get_or_create(
            key="business",
            defaults={
                "name": "Business",
                "max_products": 10,
                "max_projects": 10,
                "max_components": 100,
                "max_users": 10,
            },
        )
        team = Team.objects.create(name="DT Task Team", billing_plan="business")
        yield team
        team.delete()

    def test_finds_teams_with_dt_plugin_enabled(self, business_team: Team) -> None:
        """Test that hourly task finds teams via TeamPluginSettings."""
        settings = TeamPluginSettings.objects.create(
            team=business_team,
            enabled_plugins=["dependency-track"],
            plugin_configs={"dependency-track": {"dt_server_id": str(uuid.uuid4())}},
        )

        from sbomify.apps.plugins.tasks import hourly_dt_scan_task

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment"):
            result = hourly_dt_scan_task()

        # Team should be found (even if no SBOMs to scan)
        assert result["status"] == "completed"
        assert result["teams_scanned"] == 1

        settings.delete()

    def test_ignores_teams_without_dt_plugin(self, business_team: Team) -> None:
        """Test that hourly task skips teams without DT plugin enabled."""
        settings = TeamPluginSettings.objects.create(
            team=business_team,
            enabled_plugins=["osv"],
        )

        from sbomify.apps.plugins.tasks import hourly_dt_scan_task

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment"):
            result = hourly_dt_scan_task()

        assert result["teams_scanned"] == 0

        settings.delete()

    def test_passes_plugin_config_to_enqueue(self, business_team: Team) -> None:
        """Test that the task passes plugin config when enqueuing."""
        from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM

        server_id = str(uuid.uuid4())
        settings = TeamPluginSettings.objects.create(
            team=business_team,
            enabled_plugins=["dependency-track"],
            plugin_configs={"dependency-track": {"dt_server_id": server_id}},
        )

        # Create a component, SBOM, product, release, and artifact
        component = Component.objects.create(
            team=business_team,
            name="DT Test Component",
            component_type=Component.ComponentType.SBOM,
        )
        sbom = SBOM.objects.create(
            name="dt-test-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="dt-test.json",
            component=component,
        )
        product = Product.objects.create(
            team=business_team,
            name="DT Test Product",
        )
        release = Release.objects.create(
            product=product,
            name="v1.0",
        )
        artifact = ReleaseArtifact.objects.create(
            release=release,
            sbom=sbom,
        )

        from sbomify.apps.plugins.tasks import hourly_dt_scan_task

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            result = hourly_dt_scan_task()

        assert result["assessments_enqueued"] == 1
        call_kwargs = mock_enqueue.call_args[1]
        assert call_kwargs["config"] == {"dt_server_id": server_id}

        # Cleanup
        artifact.delete()
        release.delete()
        product.delete()
        sbom.delete()
        component.delete()
        settings.delete()
