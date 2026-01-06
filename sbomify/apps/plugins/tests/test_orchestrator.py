"""Tests for the PluginOrchestrator."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.builtins.checksum import ChecksumPlugin
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.orchestrator import (
    PluginOrchestrator,
    PluginOrchestratorError,
)
from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.utils import SBOMDataError
from sbomify.apps.teams.models import Team


class MockPlugin(AssessmentPlugin):
    """A mock plugin for testing."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="mock-plugin",
            version="1.0.0",
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        return AssessmentResult(
            plugin_name="mock-plugin",
            plugin_version="1.0.0",
            category="compliance",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=1, pass_count=1),
            findings=[
                Finding(
                    id="mock:test",
                    title="Mock Finding",
                    description="Test finding from mock plugin",
                    status="pass",
                )
            ],
        )


class FailingPlugin(AssessmentPlugin):
    """A plugin that always fails for testing error handling."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="failing-plugin",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        raise ValueError("Plugin intentionally failed")


@pytest.fixture
def test_team(db) -> Team:
    """Create a test team."""
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
    team = Team.objects.create(name="Test Team", billing_plan="community")
    yield team
    team.delete()


@pytest.fixture
def test_component(test_team: Team):
    """Create a test component."""
    component = Component.objects.create(team=test_team, name="Test Component")
    yield component
    component.delete()


@pytest.fixture
def test_sbom(test_component):
    """Create a test SBOM."""
    sbom = SBOM.objects.create(
        name="test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="test.json",
        component=test_component,
    )
    yield sbom
    sbom.delete()


@pytest.fixture
def mock_sbom_data():
    """Sample SBOM data for testing."""
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "components": [],
        }
    ).encode("utf-8")


@pytest.fixture
def registered_checksum_plugin(db):
    """Register the checksum plugin for testing."""
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


@pytest.mark.django_db
class TestPluginOrchestrator:
    """Tests for PluginOrchestrator class."""

    def test_run_assessment_success(self, test_sbom, mock_sbom_data, mocker) -> None:
        """Test successful assessment run."""
        # Mock get_sbom_data_bytes
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        run = orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_UPLOAD,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.plugin_name == "mock-plugin"
        assert run.plugin_version == "1.0.0"
        assert run.category == "compliance"
        assert run.result is not None
        assert run.result["summary"]["total_findings"] == 1
        assert run.input_content_digest != ""
        assert run.started_at is not None
        assert run.completed_at is not None

    def test_run_assessment_sbom_fetch_error(self, test_sbom, mocker) -> None:
        """Test handling of SBOM fetch error."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            side_effect=SBOMDataError("SBOM not found"),
        )

        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        run = orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_UPLOAD,
        )

        assert run.status == RunStatus.FAILED.value
        assert "SBOM not found" in run.error_message
        assert run.completed_at is not None

    def test_run_assessment_plugin_error(self, test_sbom, mock_sbom_data, mocker) -> None:
        """Test handling of plugin execution error."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()
        plugin = FailingPlugin()

        run = orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.MANUAL,
        )

        assert run.status == RunStatus.FAILED.value
        assert "Plugin intentionally failed" in run.error_message

    def test_get_plugin_instance_success(self, registered_checksum_plugin, db) -> None:
        """Test loading a plugin by name."""
        orchestrator = PluginOrchestrator()

        plugin = orchestrator.get_plugin_instance("checksum")

        assert isinstance(plugin, ChecksumPlugin)
        metadata = plugin.get_metadata()
        assert metadata.name == "checksum"

    def test_get_plugin_instance_not_registered(self, db) -> None:
        """Test error when plugin is not registered."""
        orchestrator = PluginOrchestrator()

        with pytest.raises(PluginOrchestratorError) as exc_info:
            orchestrator.get_plugin_instance("nonexistent")

        assert "not registered" in str(exc_info.value)

    def test_get_plugin_instance_disabled(self, db) -> None:
        """Test error when plugin is disabled."""
        RegisteredPlugin.objects.create(
            name="disabled-plugin",
            display_name="Disabled Plugin",
            category=AssessmentCategory.COMPLIANCE.value,
            version="1.0.0",
            plugin_class_path="sbomify.apps.plugins.builtins.ChecksumPlugin",
            is_enabled=False,
        )

        orchestrator = PluginOrchestrator()

        with pytest.raises(PluginOrchestratorError) as exc_info:
            orchestrator.get_plugin_instance("disabled-plugin")

        assert "disabled" in str(exc_info.value)

    def test_run_assessment_by_name(self, test_sbom, mock_sbom_data, registered_checksum_plugin, mocker) -> None:
        """Test running assessment by plugin name."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()

        run = orchestrator.run_assessment_by_name(
            sbom_id=test_sbom.id,
            plugin_name="checksum",
            run_reason=RunReason.MANUAL,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.plugin_name == "checksum"
        assert "checksum:sha256" in str(run.result)

    def test_assessment_run_records_created(self, test_sbom, mock_sbom_data, mocker) -> None:
        """Test that AssessmentRun records are created in the database."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, mock_sbom_data),
        )

        orchestrator = PluginOrchestrator()
        plugin = MockPlugin()

        initial_count = AssessmentRun.objects.count()

        orchestrator.run_assessment(
            sbom_id=test_sbom.id,
            plugin=plugin,
            run_reason=RunReason.ON_UPLOAD,
        )

        assert AssessmentRun.objects.count() == initial_count + 1

