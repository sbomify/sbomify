"""Integration tests for NTIA compliance plugin workflow.

Tests the complete workflow from SBOM creation through plugin assessment.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.plugins.tasks import run_assessment_task
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.signals import trigger_plugin_assessments
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
class TestNTIAPluginIntegration:
    """Integration tests for NTIA plugin workflow."""

    @pytest.fixture
    def team(self) -> Team:
        """Create a test team with business plan."""
        BillingPlan.objects.get_or_create(
            key="business",
            defaults={"name": "Business Plan"},
        )
        return Team.objects.create(
            name="Test Team",
            key="test-team-ntia",
            billing_plan="business",
        )

    @pytest.fixture
    def component(self, team: Team) -> Component:
        """Create a test component."""
        return Component.objects.create(
            name="test-component",
            team=team,
            component_type="sbom",
        )

    @pytest.fixture
    def ntia_plugin(self) -> RegisteredPlugin:
        """Register the NTIA plugin."""
        plugin, _ = RegisteredPlugin.objects.update_or_create(
            name="ntia-minimum-elements-2021",
            defaults={
                "display_name": "NTIA Minimum Elements (2021)",
                "description": "NTIA compliance checking",
                "category": "compliance",
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                "is_enabled": True,
            },
        )
        return plugin

    @pytest.fixture
    def compliant_cyclonedx_sbom(self) -> dict:
        """Sample compliant CycloneDX SBOM."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

    @pytest.fixture
    def non_compliant_cyclonedx_sbom(self) -> dict:
        """Sample non-compliant CycloneDX SBOM."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version, publisher, unique identifiers
                }
            ],
            # Missing dependencies
            "metadata": {
                # Missing authors and timestamp
            },
        }

    def test_signal_triggers_plugin_assessments(
        self, team: Team, component: Component, ntia_plugin: RegisteredPlugin
    ) -> None:
        """Test that SBOM creation signal triggers plugin assessments."""
        from sbomify.apps.plugins.models import TeamPluginSettings

        # Enable the NTIA plugin for this team
        TeamPluginSettings.objects.create(
            team=team,
            enabled_plugins=["ntia-minimum-elements-2021"],
        )

        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.json",
            source="test",
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom") as mock_enqueue:
            trigger_plugin_assessments(sender=SBOM, instance=sbom, created=True)

            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args[1]
            assert call_kwargs["sbom_id"] == sbom.id
            assert call_kwargs["team_id"] == team.id
            assert call_kwargs["run_reason"] == RunReason.ON_UPLOAD

    def test_signal_triggers_for_all_teams(self, component: Component) -> None:
        """Test that SBOM creation signal triggers plugin assessment check for all teams.

        The actual filtering of which plugins run is handled by enqueue_assessments_for_sbom
        based on TeamPluginSettings.
        """
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.json",
            source="test",
        )

        with patch("sbomify.apps.plugins.tasks.enqueue_assessments_for_sbom") as mock_enqueue:
            trigger_plugin_assessments(sender=SBOM, instance=sbom, created=True)

            # Should always be called - filtering happens inside the function
            mock_enqueue.assert_called_once()

    def test_full_assessment_workflow_compliant(
        self,
        team: Team,
        component: Component,
        ntia_plugin: RegisteredPlugin,
        compliant_cyclonedx_sbom: dict,
    ) -> None:
        """Test complete workflow for compliant SBOM assessment."""
        sbom = SBOM.objects.create(
            name="compliant-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="compliant.json",
            source="test",
        )

        # Mock SBOM data retrieval
        mock_sbom_bytes = json.dumps(compliant_cyclonedx_sbom).encode("utf-8")

        with patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, mock_sbom_bytes),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        # Verify assessment completed successfully
        assessment_run = AssessmentRun.objects.filter(sbom=sbom, plugin_name="ntia-minimum-elements-2021").first()
        assert assessment_run is not None
        assert assessment_run.status == RunStatus.COMPLETED.value
        assert assessment_run.result is not None
        assert assessment_run.result["summary"]["fail_count"] == 0
        assert assessment_run.result["summary"]["pass_count"] == 7
        assert assessment_run.completed_at is not None

    def test_full_assessment_workflow_non_compliant(
        self,
        team: Team,
        component: Component,
        ntia_plugin: RegisteredPlugin,
        non_compliant_cyclonedx_sbom: dict,
    ) -> None:
        """Test complete workflow for non-compliant SBOM assessment."""
        sbom = SBOM.objects.create(
            name="non-compliant-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="non-compliant.json",
            source="test",
        )

        # Mock SBOM data retrieval
        mock_sbom_bytes = json.dumps(non_compliant_cyclonedx_sbom).encode("utf-8")

        with patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, mock_sbom_bytes),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        # Verify assessment completed with failures
        assessment_run = AssessmentRun.objects.filter(sbom=sbom, plugin_name="ntia-minimum-elements-2021").first()
        assert assessment_run is not None
        assert assessment_run.status == RunStatus.COMPLETED.value
        assert assessment_run.result is not None
        assert assessment_run.result["summary"]["fail_count"] > 0

    def test_assessment_run_preserves_history(
        self,
        team: Team,
        component: Component,
        ntia_plugin: RegisteredPlugin,
        compliant_cyclonedx_sbom: dict,
    ) -> None:
        """Test that multiple assessment runs are preserved for audit trail."""
        sbom = SBOM.objects.create(
            name="history-test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="history.json",
            source="test",
        )

        mock_sbom_bytes = json.dumps(compliant_cyclonedx_sbom).encode("utf-8")

        with patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, mock_sbom_bytes),
        ):
            # Run first assessment
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD.value,
            )

            # Run second assessment (manual re-run)
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.MANUAL.value,
            )

        # Verify both runs exist
        runs = AssessmentRun.objects.filter(sbom=sbom, plugin_name="ntia-minimum-elements-2021")
        assert runs.count() == 2

        # Both should be completed
        for run in runs:
            assert run.status == RunStatus.COMPLETED.value


class TestNTIAPluginAPIIntegration(TestCase):
    """Integration tests for NTIA plugin API endpoints."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.team = Team.objects.create(
            name="API Test Team",
            key="api-test-team",
            billing_plan="business",
        )
        BillingPlan.objects.get_or_create(
            key="business",
            defaults={"name": "Business Plan"},
        )
        self.component = Component.objects.create(
            name="api-test-component",
            team=self.team,
            component_type="sbom",
        )
        RegisteredPlugin.objects.update_or_create(
            name="ntia-minimum-elements-2021",
            defaults={
                "display_name": "NTIA Minimum Elements (2021)",
                "description": "NTIA compliance checking",
                "category": "compliance",
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.ntia.NTIAMinimumElementsPlugin",
                "is_enabled": True,
            },
        )

    def test_assessment_api_returns_ntia_results(self) -> None:
        """Test that assessment API returns NTIA plugin results."""
        from sbomify.apps.plugins.apis import get_sbom_assessments

        sbom = SBOM.objects.create(
            name="api-test-sbom",
            component=self.component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="api-test.json",
            source="test",
        )

        # Create completed assessment run with all required fields
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            category="compliance",
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            completed_at=timezone.now(),
            result={
                "plugin_name": "ntia-minimum-elements-2021",
                "plugin_version": "1.0.0",
                "category": "compliance",
                "assessed_at": timezone.now().isoformat(),
                "summary": {
                    "total_findings": 7,
                    "pass_count": 7,
                    "fail_count": 0,
                    "error_count": 0,
                    "info_count": 0,
                },
                "findings": [],
                "metadata": {
                    "standard_name": "NTIA Minimum Elements",
                    "standard_version": "2021-07",
                },
            },
        )

        # Mock request
        mock_request = MagicMock()

        response = get_sbom_assessments(mock_request, str(sbom.id))

        assert response.status_summary.overall_status == "all_pass"
        assert len(response.latest_runs) == 1
        assert response.latest_runs[0].plugin_name == "ntia-minimum-elements-2021"

    def test_badge_api_returns_status_summary(self) -> None:
        """Test that badge API returns correct status summary."""
        from sbomify.apps.plugins.apis import get_sbom_assessment_badge

        sbom = SBOM.objects.create(
            name="badge-test-sbom",
            component=self.component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="badge-test.json",
            source="test",
        )

        # Create completed assessment with failures
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            category="compliance",
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            completed_at=timezone.now(),
            result={
                "summary": {
                    "total_findings": 7,
                    "pass_count": 4,
                    "fail_count": 3,
                    "error_count": 0,
                    "info_count": 0,
                },
            },
        )

        mock_request = MagicMock()
        response = get_sbom_assessment_badge(mock_request, str(sbom.id))

        assert response.overall_status == "has_failures"
        assert response.failing_count == 1
