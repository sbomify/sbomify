"""Tests for plugin models."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import (
    AssessmentRun,
    RegisteredPlugin,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team


@pytest.fixture
def test_team(db) -> Team:
    """Create a test team for model tests."""
    # Ensure billing plan exists
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(
        name="Test Team",
        billing_plan="community",
    )
    yield team
    team.delete()


@pytest.fixture
def sample_component(test_team: Team) -> Component:
    """Create a sample component for testing."""
    component = Component.objects.create(
        team=test_team,
        name="Test Component",
    )
    yield component
    component.delete()


@pytest.fixture
def sample_component_sbom(test_team: Team) -> Component:
    """Create a sample component with component_type='sbom' for testing."""
    component = Component.objects.create(
        team=test_team,
        name="Test Component",
        component_type=Component.ComponentType.SBOM,
    )
    yield component
    component.delete()


@pytest.fixture
def sample_sbom(sample_component: Component) -> SBOM:
    """Create a sample SBOM for testing."""
    sbom = SBOM.objects.create(
        name="test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="test.json",
        component=sample_component,
    )
    yield sbom
    sbom.delete()


@pytest.fixture
def sample_sbom_for_sbom_component(sample_component_sbom: Component) -> SBOM:
    """Create a sample SBOM for a component with component_type='sbom' for testing."""
    sbom = SBOM.objects.create(
        name="test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="test.json",
        component=sample_component_sbom,
    )
    yield sbom
    sbom.delete()


@pytest.mark.django_db
class TestRegisteredPlugin:
    """Tests for RegisteredPlugin model."""

    def test_create_plugin(self, db) -> None:
        """Test creating a registered plugin."""
        plugin = RegisteredPlugin.objects.create(
            name="checksum",
            display_name="Checksum Plugin",
            description="Computes SBOM checksum",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.ChecksumPlugin",
        )

        assert plugin.name == "checksum"
        assert plugin.display_name == "Checksum Plugin"
        assert plugin.category == "compliance"
        assert plugin.is_enabled is True  # default

    def test_plugin_string_representation(self, db) -> None:
        """Test plugin string representation."""
        plugin = RegisteredPlugin.objects.create(
            name="test-plugin",
            display_name="Test Plugin",
            category=AssessmentCategory.SECURITY.value,
            version="2.0.0",
            plugin_class_path="test.path.TestPlugin",
        )

        assert str(plugin) == "Test Plugin v2.0.0 (enabled)"

    def test_disabled_plugin_string_representation(self, db) -> None:
        """Test disabled plugin string representation."""
        plugin = RegisteredPlugin.objects.create(
            name="disabled-plugin",
            display_name="Disabled Plugin",
            category=AssessmentCategory.LICENSE.value,
            version="1.0.0",
            plugin_class_path="test.path.Plugin",
            is_enabled=False,
        )

        assert str(plugin) == "Disabled Plugin v1.0.0 (disabled)"

    def test_plugin_name_unique(self, db) -> None:
        """Test that plugin names must be unique."""
        RegisteredPlugin.objects.create(
            name="unique-plugin",
            display_name="First Plugin",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="test.Plugin",
        )

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            RegisteredPlugin.objects.create(
                name="unique-plugin",  # Same name
                display_name="Second Plugin",
                category=AssessmentCategory.COMPLIANCE.value,
                version="1.0.0",
                plugin_class_path="test.Plugin2",
            )


@pytest.mark.django_db
class TestTeamPluginSettings:
    """Tests for TeamPluginSettings model."""

    def test_create_settings(self, test_team: Team) -> None:
        """Test creating team plugin settings."""
        settings = TeamPluginSettings.objects.create(
            team=test_team,
            enabled_plugins=["checksum", "ntia"],
            plugin_configs={
                "ntia": {"strict_mode": True},
            },
        )

        assert settings.team == test_team
        assert "checksum" in settings.enabled_plugins
        assert "ntia" in settings.enabled_plugins

    def test_settings_string_representation(self, test_team: Team) -> None:
        """Test settings string representation."""
        settings = TeamPluginSettings.objects.create(
            team=test_team,
            enabled_plugins=["plugin1", "plugin2", "plugin3"],
        )

        assert str(settings) == "Test Team - 3 plugins enabled"

    def test_is_plugin_enabled(self, test_team: Team) -> None:
        """Test checking if a plugin is enabled."""
        settings = TeamPluginSettings.objects.create(
            team=test_team,
            enabled_plugins=["checksum", "ntia"],
        )

        assert settings.is_plugin_enabled("checksum") is True
        assert settings.is_plugin_enabled("ntia") is True
        assert settings.is_plugin_enabled("osv") is False

    def test_get_plugin_config(self, test_team: Team) -> None:
        """Test getting plugin-specific configuration."""
        settings = TeamPluginSettings.objects.create(
            team=test_team,
            enabled_plugins=["license-policy"],
            plugin_configs={
                "license-policy": {
                    "allowed": ["MIT", "Apache-2.0"],
                    "denied": ["GPL-3.0"],
                },
            },
        )

        config = settings.get_plugin_config("license-policy")

        assert config["allowed"] == ["MIT", "Apache-2.0"]
        assert config["denied"] == ["GPL-3.0"]

    def test_get_plugin_config_not_configured(self, test_team: Team) -> None:
        """Test getting config for unconfigured plugin returns empty dict."""
        settings = TeamPluginSettings.objects.create(
            team=test_team,
            enabled_plugins=["checksum"],
        )

        config = settings.get_plugin_config("checksum")

        assert config == {}

    def test_plugins_disabled_by_default(self, test_team: Team) -> None:
        """Test that all plugins are disabled by default when TeamPluginSettings is created.

        This ensures teams must explicitly opt-in to enable plugins.
        """
        # Create settings with defaults (simulating get_or_create behavior)
        settings = TeamPluginSettings.objects.create(team=test_team)

        # Verify no plugins are enabled by default
        assert settings.enabled_plugins == []
        assert settings.is_plugin_enabled("ntia-minimum-elements-2021") is False
        assert settings.is_plugin_enabled("cisa-minimum-elements-2025") is False
        assert settings.is_plugin_enabled("checksum") is False
        assert settings.is_plugin_enabled("fda-medical-device-2025") is False


@pytest.mark.django_db
class TestAssessmentRun:
    """Tests for AssessmentRun model."""

    def test_create_assessment_run(self, sample_sbom) -> None:
        """Test creating an assessment run."""
        run = AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="checksum",
            plugin_version="1.0.0",
            plugin_config_hash="abc123" * 10 + "abcd",  # 64 chars
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
        )

        assert run.sbom == sample_sbom
        assert run.plugin_name == "checksum"
        assert run.status == RunStatus.PENDING.value  # default

    def test_assessment_run_string_representation(self, sample_sbom) -> None:
        """Test assessment run string representation."""
        run = AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="test-plugin",
            plugin_version="2.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.SECURITY.value,
            run_reason=RunReason.MANUAL.value,
            status=RunStatus.COMPLETED.value,
        )

        expected = f"test-plugin v2.0.0 on {sample_sbom.id} (completed)"
        assert str(run) == expected

    def test_duration_seconds_completed(self, sample_sbom) -> None:
        """Test duration calculation for completed run."""
        start = timezone.now()
        end = start + timedelta(seconds=5.5)

        run = AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="test",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            started_at=start,
            completed_at=end,
        )

        assert run.duration_seconds == pytest.approx(5.5, rel=0.1)

    def test_is_successful_completed(self, sample_sbom) -> None:
        """Test is_successful property for completed run."""
        run = AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="test",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
        )

        assert run.is_successful is True

    def test_is_successful_failed(self, sample_sbom) -> None:
        """Test is_successful property for failed run."""
        run = AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="test",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.FAILED.value,
        )

        assert run.is_successful is False


@pytest.mark.django_db
class TestTeamPluginSettingsSignal:
    """Tests for TeamPluginSettings signal handler that dispatches background tasks."""

    @pytest.fixture
    def registered_plugin(self, db):
        """Create a registered plugin for testing."""
        plugin = RegisteredPlugin.objects.create(
            name="checksum",
            display_name="Checksum Plugin",
            description="Computes SBOM checksum",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.ChecksumPlugin",
            is_enabled=True,
        )
        yield plugin
        plugin.delete()

    def test_signal_dispatches_background_task_when_plugins_enabled(
        self, test_team: Team, registered_plugin
    ) -> None:
        """Test that signal dispatches background task when plugins are enabled."""
        with patch(
            "sbomify.apps.plugins.signals.enqueue_assessments_for_existing_sboms_task"
        ) as mock_task:
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )

            # Verify that the background task was dispatched
            assert mock_task.send.called
            call_kwargs = mock_task.send.call_args[1]
            assert call_kwargs["team_id"] == str(test_team.id)
            assert call_kwargs["enabled_plugins"] == ["checksum"]

    def test_signal_does_not_dispatch_when_no_plugins_enabled(
        self, test_team: Team
    ) -> None:
        """Test that signal doesn't dispatch task when no plugins are enabled."""
        with patch(
            "sbomify.apps.plugins.signals.enqueue_assessments_for_existing_sboms_task"
        ) as mock_task:
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=[],
            )

            # Verify that the background task was NOT dispatched
            assert not mock_task.send.called

    def test_signal_uses_run_on_commit(self, test_team: Team, registered_plugin) -> None:
        """Test that the signal correctly uses run_on_commit to defer task dispatch."""
        with patch("sbomify.apps.plugins.signals.run_on_commit") as mock_run_on_commit:
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )

            # Verify that run_on_commit was called
            assert mock_run_on_commit.called

    def test_signal_handles_errors_gracefully(self, test_team: Team) -> None:
        """Test that the signal handles errors gracefully."""
        with patch("sbomify.apps.plugins.signals.logger") as mock_logger:
            # Simulate an error by making the task dispatch fail
            with patch(
                "sbomify.apps.plugins.signals.enqueue_assessments_for_existing_sboms_task"
            ) as mock_task:
                mock_task.send.side_effect = Exception("Task dispatch failed")
                TeamPluginSettings.objects.create(
                    team=test_team,
                    enabled_plugins=["checksum"],
                )

            # Verify that an error was logged
            assert mock_logger.error.called

    def test_signal_passes_plugin_configs_to_task(self, test_team: Team, registered_plugin) -> None:
        """Test that signal passes plugin configs to the background task."""
        plugin_configs = {"checksum": {"option": "value"}}
        with patch(
            "sbomify.apps.plugins.signals.enqueue_assessments_for_existing_sboms_task"
        ) as mock_task:
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
                plugin_configs=plugin_configs,
            )

            call_kwargs = mock_task.send.call_args[1]
            assert call_kwargs["plugin_configs"] == plugin_configs


@pytest.mark.django_db
class TestBulkEnqueueTask:
    """Tests for the background task that enqueues assessments for existing SBOMs."""

    @pytest.fixture
    def registered_plugin(self, db):
        """Create a registered plugin for testing."""
        plugin = RegisteredPlugin.objects.create(
            name="checksum",
            display_name="Checksum Plugin",
            description="Computes SBOM checksum",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.ChecksumPlugin",
            is_enabled=True,
        )
        yield plugin
        plugin.delete()

    def test_task_only_processes_recent_sboms(
        self, test_team: Team, sample_component_sbom: Component, registered_plugin
    ) -> None:
        """Test that the task only processes SBOMs within the cutoff period."""
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task

        # Create a recent SBOM (within cutoff)
        recent_sbom = SBOM.objects.create(
            name="recent-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="recent.json",
            component=sample_component_sbom,
        )

        # Create an old SBOM (outside cutoff) by manipulating created_at
        old_sbom = SBOM.objects.create(
            name="old-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="old.json",
            component=sample_component_sbom,
        )
        # Set created_at to 48 hours ago (outside 24-hour cutoff)
        SBOM.objects.filter(id=old_sbom.id).update(created_at=timezone.now() - timedelta(hours=48))

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            result = enqueue_assessments_for_existing_sboms_task(
                team_id=str(test_team.id),
                enabled_plugins=["checksum"],
                cutoff_hours=24,
            )

            # Verify only the recent SBOM was processed
            assert result["sboms_found"] == 1
            assert result["assessments_enqueued"] == 1

            # Verify enqueue_assessment was called only for the recent SBOM
            assert mock_enqueue.call_count == 1
            call_kwargs = mock_enqueue.call_args[1]
            assert call_kwargs["sbom_id"] == str(recent_sbom.id)

        # Cleanup
        recent_sbom.delete()
        old_sbom.delete()

    def test_task_skips_sboms_with_existing_runs(
        self, test_team: Team, sample_sbom_for_sbom_component, registered_plugin
    ) -> None:
        """Test that task skips SBOMs that already have assessment runs."""
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task

        # Create an existing assessment run
        AssessmentRun.objects.create(
            sbom=sample_sbom_for_sbom_component,
            plugin_name="checksum",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            result = enqueue_assessments_for_existing_sboms_task(
                team_id=str(test_team.id),
                enabled_plugins=["checksum"],
                cutoff_hours=24,
            )

            # SBOM was found but no assessments enqueued (already has a run)
            assert result["sboms_found"] == 1
            assert result["assessments_enqueued"] == 0
            assert not mock_enqueue.called

    def test_task_handles_nonexistent_team(self) -> None:
        """Test that task handles nonexistent team gracefully."""
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task

        # Use a large integer ID that won't exist in the test database
        # (Team model uses auto-incrementing integer IDs, not UUIDs)
        nonexistent_team_id = "999999999"
        result = enqueue_assessments_for_existing_sboms_task(
            team_id=nonexistent_team_id,
            enabled_plugins=["checksum"],
        )

        assert result["error"] == "Team not found"
        assert result["sboms_found"] == 0
        assert result["assessments_enqueued"] == 0

    def test_task_handles_no_sboms_gracefully(
        self, test_team: Team, registered_plugin
    ) -> None:
        """Test that task handles teams with no recent SBOMs gracefully."""
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            result = enqueue_assessments_for_existing_sboms_task(
                team_id=str(test_team.id),
                enabled_plugins=["checksum"],
            )

            assert result["sboms_found"] == 0
            assert result["assessments_enqueued"] == 0
            assert not mock_enqueue.called

    def test_task_enqueues_for_multiple_plugins(
        self, test_team: Team, sample_sbom_for_sbom_component, registered_plugin
    ) -> None:
        """Test that task enqueues assessments for multiple enabled plugins."""
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task

        # Create another registered plugin
        ntia_plugin = RegisteredPlugin.objects.create(
            name="ntia",
            display_name="NTIA Plugin",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="test.path.NTIAPlugin",
            is_enabled=True,
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            result = enqueue_assessments_for_existing_sboms_task(
                team_id=str(test_team.id),
                enabled_plugins=["checksum", "ntia"],
                cutoff_hours=24,
            )

            # Both plugins should be enqueued for the SBOM
            assert result["sboms_found"] == 1
            assert result["assessments_enqueued"] == 2
            assert mock_enqueue.call_count == 2

        ntia_plugin.delete()

    def test_task_only_enqueues_for_plugins_without_existing_runs(
        self, test_team: Team, sample_sbom_for_sbom_component, registered_plugin
    ) -> None:
        """Test that task only enqueues for plugins that don't have existing runs."""
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task

        # Create another registered plugin
        ntia_plugin = RegisteredPlugin.objects.create(
            name="ntia",
            display_name="NTIA Plugin",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="test.path.NTIAPlugin",
            is_enabled=True,
        )

        # Create existing run for ntia but not for checksum
        AssessmentRun.objects.create(
            sbom=sample_sbom_for_sbom_component,
            plugin_name="ntia",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            result = enqueue_assessments_for_existing_sboms_task(
                team_id=str(test_team.id),
                enabled_plugins=["checksum", "ntia"],
                cutoff_hours=24,
            )

            # Only checksum should be enqueued (ntia already has a run)
            assert result["assessments_enqueued"] == 1
            call_kwargs = mock_enqueue.call_args[1]
            assert call_kwargs["plugin_name"] == "checksum"

        ntia_plugin.delete()
