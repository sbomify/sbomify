"""Tests for plugin models."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.models import (
    AssessmentRun,
    RegisteredPlugin,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
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

    @pytest.fixture
    def sample_component(self, test_team: Team):
        """Create a sample component for testing."""
        from sbomify.apps.sboms.models import Component

        component = Component.objects.create(
            team=test_team,
            name="Test Component",
        )
        yield component
        component.delete()

    @pytest.fixture
    def sample_sbom(self, sample_component):
        """Create a sample SBOM for testing."""
        from sbomify.apps.sboms.models import SBOM

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
    """Tests for TeamPluginSettings signal handler that triggers assessments for existing SBOMs."""

    @pytest.fixture
    def sample_component(self, test_team: Team):
        """Create a sample component for testing."""
        from sbomify.apps.core.models import Component

        component = Component.objects.create(
            team=test_team,
            name="Test Component",
            component_type="sbom",
        )
        yield component
        component.delete()

    @pytest.fixture
    def sample_sbom(self, sample_component):
        """Create a sample SBOM for testing."""
        from sbomify.apps.sboms.models import SBOM

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

    def test_signal_triggers_when_plugins_enabled_first_time(
        self, test_team: Team, sample_sbom, registered_plugin
    ) -> None:
        """Test that assessments are triggered when plugins are enabled for the first time."""
        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            # Create settings with plugins enabled - this should trigger the signal
            # run_on_commit runs immediately in tests, so the callback executes right away
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )

            # Verify that enqueue_assessment was called for the SBOM
            assert mock_enqueue.called
            # Check that it was called with the correct parameters
            call_args = mock_enqueue.call_args
            assert call_args[1]["sbom_id"] == str(sample_sbom.id)
            assert call_args[1]["plugin_name"] == "checksum"
            assert call_args[1]["run_reason"] == RunReason.CONFIG_CHANGE

    def test_signal_does_not_trigger_when_no_plugins_enabled(
        self, test_team: Team, sample_sbom
    ) -> None:
        """Test that the signal doesn't trigger when no plugins are enabled."""
        with patch("sbomify.apps.plugins.tasks.enqueue_assessment") as mock_enqueue:
            # Create settings with no plugins enabled
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=[],
            )

            # Verify that enqueue_assessment was not called
            assert not mock_enqueue.called

    def test_signal_only_enqueues_for_sboms_without_existing_runs(
        self, test_team: Team, sample_sbom, registered_plugin
    ) -> None:
        """Test that assessments are only enqueued for SBOMs without existing runs for those plugins."""
        # Create an existing assessment run for this SBOM and plugin
        AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="checksum",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            # Create settings with plugins enabled
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )

            # Verify that enqueue_assessment was NOT called since a run already exists
            assert not mock_enqueue.called

    def test_signal_enqueues_for_re_enabled_plugins(
        self, test_team: Team, sample_sbom, registered_plugin
    ) -> None:
        """Test that re-enabling plugins triggers new assessments."""
        # Create an existing assessment run for a different plugin
        AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="ntia",
            plugin_version="1.0.0",
            plugin_config_hash="x" * 64,
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
        )

        # Create a registered plugin for checksum
        RegisteredPlugin.objects.create(
            name="ntia",
            display_name="NTIA Plugin",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="test.path.NTIAPlugin",
            is_enabled=True,
        )

        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            # Create settings with checksum enabled (but ntia already has a run)
            # run_on_commit runs immediately in tests, so the callback executes right away
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum", "ntia"],
            )

            # Verify that enqueue_assessment was called for checksum (no existing run)
            # but not for ntia (has existing run)
            assert mock_enqueue.called
            # Check that it was only called for checksum
            call_args_list = mock_enqueue.call_args_list
            plugin_names = [call[1]["plugin_name"] for call in call_args_list]
            assert "checksum" in plugin_names
            assert "ntia" not in plugin_names

    def test_signal_handles_errors_gracefully(self, test_team: Team) -> None:
        """Test that the signal handles errors gracefully."""
        with patch("sbomify.apps.plugins.signals.logger") as mock_logger:
            # Create a real TeamPluginSettings instance but make Component query fail
            settings = TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )
            
            # Make Component.objects.filter raise an exception to trigger error handling
            from sbomify.apps.core.models import Component
            with patch.object(Component.objects, "filter", side_effect=Exception("Database error")):
                # Import the signal handler
                from sbomify.apps.plugins.signals import trigger_assessments_for_existing_sboms

                # Call the signal handler - should not raise an exception
                trigger_assessments_for_existing_sboms(
                    sender=TeamPluginSettings, instance=settings, created=False
                )

                # Verify that error was logged
                error_calls = [str(call) for call in mock_logger.error.call_args_list]
                assert any("Failed to trigger assessments" in call or "Unexpected error" in call for call in error_calls)

    def test_signal_uses_run_on_commit(self, test_team: Team, sample_sbom, registered_plugin) -> None:
        """Test that the signal correctly uses run_on_commit to defer execution."""
        # Patch run_on_commit where it's used in the signals module
        with patch("sbomify.apps.plugins.signals.run_on_commit") as mock_run_on_commit:
            # Create settings with plugins enabled
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )

            # Verify that run_on_commit was called
            assert mock_run_on_commit.called

    def test_signal_handles_no_sboms_gracefully(
        self, test_team: Team, registered_plugin
    ) -> None:
        """Test that the signal handles teams with no SBOMs gracefully."""
        with patch("sbomify.apps.plugins.signals.enqueue_assessment") as mock_enqueue:
            # Create settings with plugins enabled but no SBOMs exist
            # run_on_commit runs immediately in tests, so the callback executes right away
            TeamPluginSettings.objects.create(
                team=test_team,
                enabled_plugins=["checksum"],
            )

            # Verify that enqueue_assessment was not called (no SBOMs to process)
            assert not mock_enqueue.called
