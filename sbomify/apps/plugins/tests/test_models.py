"""Tests for plugin models."""

from datetime import timedelta

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

