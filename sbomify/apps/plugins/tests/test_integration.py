"""Integration tests for the plugin framework end-to-end flow."""

import hashlib
import json

import pytest
from django.db import transaction

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.builtins.checksum import ChecksumPlugin
from sbomify.apps.plugins.models import (
    AssessmentRun,
    RegisteredPlugin,
    TeamPluginSettings,
)
from sbomify.apps.plugins.orchestrator import PluginOrchestrator
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.plugins.tasks import enqueue_assessment, run_assessment_task
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team


@pytest.fixture
def test_team(db) -> Team:
    """Create a test team for integration tests."""
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
    team = Team.objects.create(name="Integration Test Team", billing_plan="business")
    yield team
    team.delete()


@pytest.fixture
def test_component(test_team: Team):
    """Create a test component."""
    component = Component.objects.create(team=test_team, name="Integration Component")
    yield component
    component.delete()


@pytest.fixture
def test_sbom(test_component):
    """Create a test SBOM."""
    sbom = SBOM.objects.create(
        name="integration-test-sbom",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.5",
        sbom_filename="integration-test.json",
        component=test_component,
    )
    yield sbom
    sbom.delete()


@pytest.fixture
def sample_sbom_bytes():
    """Sample SBOM content for testing."""
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {
                "timestamp": "2024-01-15T12:00:00Z",
            },
            "components": [
                {
                    "type": "library",
                    "name": "requests",
                    "version": "2.31.0",
                    "purl": "pkg:pypi/requests@2.31.0",
                }
            ],
        }
    ).encode("utf-8")


@pytest.fixture
def registered_checksum_plugin(db):
    """Register the checksum plugin."""
    plugin = RegisteredPlugin.objects.create(
        name="checksum",
        display_name="Checksum Plugin",
        description="Computes SHA256 checksum of SBOM content",
        category=AssessmentCategory.COMPLIANCE.value,
        version="1.0.0",
        plugin_class_path="sbomify.apps.plugins.builtins.ChecksumPlugin",
        is_enabled=True,
    )
    yield plugin
    plugin.delete()


@pytest.fixture
def team_with_checksum_enabled(test_team: Team, registered_checksum_plugin):
    """Create team settings with checksum plugin enabled."""
    settings = TeamPluginSettings.objects.create(
        team=test_team,
        enabled_plugins=["checksum"],
    )
    yield settings
    settings.delete()


@pytest.mark.django_db
class TestChecksumPluginEndToEnd:
    """End-to-end integration tests for the checksum plugin."""

    def test_full_assessment_flow(self, test_sbom, sample_sbom_bytes, registered_checksum_plugin, mocker) -> None:
        """Test the complete flow from SBOM to stored assessment result.

        This test verifies:
        1. Plugin can be loaded by name
        2. Orchestrator fetches SBOM and creates temp file
        3. Plugin receives correct data and computes checksum
        4. AssessmentRun record is created with correct data
        5. Result is properly serialized and stored
        """
        # Mock the S3 fetch
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, sample_sbom_bytes),
        )

        # Run assessment via orchestrator
        orchestrator = PluginOrchestrator()
        run = orchestrator.run_assessment_by_name(
            sbom_id=test_sbom.id,
            plugin_name="checksum",
            run_reason=RunReason.ON_UPLOAD,
        )

        # Verify the run completed successfully
        assert run.status == RunStatus.COMPLETED.value
        assert run.plugin_name == "checksum"
        assert run.plugin_version == "1.1.0"
        assert run.category == "compliance"
        assert run.run_reason == RunReason.ON_UPLOAD.value

        # Verify the result is stored correctly
        assert run.result is not None
        assert run.result["schema_version"] == "1.0"
        assert run.result["plugin_name"] == "checksum"
        assert run.result["summary"]["total_findings"] == 1
        # Without a stored hash, the plugin produces a warning (not a pass)
        assert run.result["summary"]["warning_count"] == 1

        # Verify the finding contains the checksum
        findings = run.result["findings"]
        assert len(findings) == 1
        # Without a stored hash, the plugin produces a warning finding
        assert findings[0]["id"] == "checksum:no-stored-hash"
        assert "SHA256:" in findings[0]["description"]

        # Verify checksum is correct
        expected_checksum = hashlib.sha256(sample_sbom_bytes).hexdigest()
        assert expected_checksum in findings[0]["description"]
        assert findings[0]["metadata"]["computed_hash"] == expected_checksum

        # Verify input content digest matches
        assert run.input_content_digest == expected_checksum

        # Verify timestamps
        assert run.started_at is not None
        assert run.completed_at is not None
        assert run.completed_at > run.started_at

    def test_assessment_run_persisted_to_database(
        self, test_sbom, sample_sbom_bytes, registered_checksum_plugin, mocker
    ) -> None:
        """Test that assessment run is correctly persisted to database."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, sample_sbom_bytes),
        )

        orchestrator = PluginOrchestrator()
        run = orchestrator.run_assessment_by_name(
            sbom_id=test_sbom.id,
            plugin_name="checksum",
            run_reason=RunReason.MANUAL,
        )

        # Reload from database
        db_run = AssessmentRun.objects.get(id=run.id)

        assert db_run.sbom_id == test_sbom.id
        assert db_run.plugin_name == "checksum"
        assert db_run.status == RunStatus.COMPLETED.value
        assert db_run.result is not None

    def test_team_plugin_settings_integration(
        self, test_team, test_sbom, sample_sbom_bytes, team_with_checksum_enabled, mocker
    ) -> None:
        """Test that team settings correctly control which plugins run."""
        # Verify checksum is enabled for the team
        settings = TeamPluginSettings.objects.get(team=test_team)
        assert settings.is_plugin_enabled("checksum") is True
        assert settings.is_plugin_enabled("nonexistent") is False

    def test_registered_plugin_loads_checksum_class(self, registered_checksum_plugin) -> None:
        """Test that the registered plugin class path correctly loads ChecksumPlugin."""
        orchestrator = PluginOrchestrator()
        plugin = orchestrator.get_plugin_instance("checksum")

        assert isinstance(plugin, ChecksumPlugin)

        metadata = plugin.get_metadata()
        assert metadata.name == "checksum"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_assessment_result_schema_compliance(
        self, test_sbom, sample_sbom_bytes, registered_checksum_plugin, mocker
    ) -> None:
        """Test that assessment result follows the expected schema."""
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(test_sbom, sample_sbom_bytes),
        )

        orchestrator = PluginOrchestrator()
        run = orchestrator.run_assessment_by_name(
            sbom_id=test_sbom.id,
            plugin_name="checksum",
            run_reason=RunReason.ON_UPLOAD,
        )

        result = run.result

        # Verify top-level schema
        assert "schema_version" in result
        assert "plugin_name" in result
        assert "plugin_version" in result
        assert "category" in result
        assert "assessed_at" in result
        assert "summary" in result
        assert "findings" in result

        # Verify summary schema
        summary = result["summary"]
        assert "total_findings" in summary
        assert "pass_count" in summary
        assert "fail_count" in summary

        # Verify finding schema
        finding = result["findings"][0]
        assert "id" in finding
        assert "title" in finding
        assert "description" in finding
        assert "status" in finding
        assert "severity" in finding


@pytest.mark.django_db(transaction=True)
class TestEnqueueAssessmentTransactionSafety:
    """Tests for transaction-safe task enqueueing behavior."""

    def test_enqueue_assessment_deferred_until_commit(self, mocker) -> None:
        """Verify task dispatch is deferred until transaction commits.

        This test ensures that when enqueue_assessment() is called inside a
        transaction, the Dramatiq task is not sent until after the transaction
        commits. This prevents race conditions where workers try to fetch
        SBOMs that don't exist yet.
        """
        mock_send = mocker.patch.object(run_assessment_task, "send_with_options")

        with transaction.atomic():
            enqueue_assessment(
                sbom_id="test-sbom-id",
                plugin_name="checksum",
                run_reason=RunReason.ON_UPLOAD,
            )
            # Task should NOT be sent yet - we're still inside the transaction
            mock_send.assert_not_called()

        # After transaction commits, task should be sent
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs["kwargs"]
        assert call_kwargs["sbom_id"] == "test-sbom-id"
        assert call_kwargs["plugin_name"] == "checksum"
        assert call_kwargs["run_reason"] == "on_upload"

    def test_enqueue_assessment_immediate_outside_transaction(self, mocker) -> None:
        """Verify task is sent immediately when called outside a transaction.

        When not inside an explicit transaction (autocommit mode), the task
        should be dispatched immediately since data is already committed.
        """
        mock_send = mocker.patch.object(run_assessment_task, "send_with_options")

        # Call outside any transaction block
        enqueue_assessment(
            sbom_id="test-sbom-id",
            plugin_name="checksum",
            run_reason=RunReason.MANUAL,
        )

        # Task should be sent immediately
        mock_send.assert_called_once()

    def test_enqueue_assessment_not_sent_on_rollback(self, mocker) -> None:
        """Verify task is NOT sent if transaction is rolled back.

        If the transaction fails and rolls back, the on_commit callback
        should never execute, preventing orphaned tasks.
        """
        mock_send = mocker.patch.object(run_assessment_task, "send_with_options")

        try:
            with transaction.atomic():
                enqueue_assessment(
                    sbom_id="test-sbom-id",
                    plugin_name="checksum",
                    run_reason=RunReason.ON_UPLOAD,
                )
                # Force a rollback
                raise ValueError("Simulated error to trigger rollback")
        except ValueError:
            pass

        # Task should NOT be sent because transaction rolled back
        mock_send.assert_not_called()
