"""Integration tests for OSV vulnerability scanning plugin.

Tests the complete workflow from SBOM creation through plugin assessment,
including plugin registration and scheduled scan tasks.
"""

import json
from unittest.mock import patch

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.plugins.tasks import run_assessment_task
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team

# Mock osv-scanner output with vulnerabilities
MOCK_OSV_OUTPUT_WITH_VULNS = json.dumps(
    {
        "results": [
            {
                "packages": [
                    {
                        "package": {"name": "lodash", "version": "4.17.20", "ecosystem": "npm"},
                        "vulnerabilities": [
                            {
                                "id": "GHSA-jf85-cpcp-j695",
                                "summary": "Prototype Pollution in lodash",
                                "details": "Lodash is vulnerable.",
                                "aliases": ["CVE-2021-23337"],
                                "severity": [],
                                "references": [],
                                "affected": [
                                    {
                                        "ranges": [
                                            {
                                                "type": "SEMVER",
                                                "database_specific": {"severity": "high"},
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }
)


@pytest.mark.django_db
class TestOSVPluginIntegration:
    """Integration tests for OSV plugin workflow."""

    @pytest.fixture
    def team(self) -> Team:
        """Create a test team with business plan."""
        BillingPlan.objects.get_or_create(key="business", defaults={"name": "Business Plan"})
        return Team.objects.create(
            name="OSV Test Team",
            key="osv-test-team",
            billing_plan="business",
        )

    @pytest.fixture
    def component(self, team: Team) -> Component:
        """Create a test component."""
        return Component.objects.create(
            name="osv-test-component",
            team=team,
            component_type="sbom",
        )

    @pytest.fixture
    def osv_plugin(self) -> RegisteredPlugin:
        """Register the OSV plugin."""
        plugin, _ = RegisteredPlugin.objects.update_or_create(
            name="osv",
            defaults={
                "display_name": "OSV Vulnerability Scanner",
                "description": "OSV scanning",
                "category": "security",
                "version": "1.0.0",
                "plugin_class_path": "sbomify.apps.plugins.builtins.osv.OSVPlugin",
                "is_enabled": True,
                "default_config": {
                    "timeout": 300,
                    "scanner_path": "/usr/local/bin/osv-scanner",
                },
            },
        )
        return plugin

    @pytest.fixture
    def cyclonedx_sbom_bytes(self) -> bytes:
        """Sample CycloneDX SBOM bytes."""
        return json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "components": [
                    {
                        "name": "lodash",
                        "version": "4.17.20",
                        "purl": "pkg:npm/lodash@4.17.20",
                    }
                ],
            }
        ).encode("utf-8")

    def test_full_assessment_workflow_with_vulns(
        self,
        team: Team,
        component: Component,
        osv_plugin: RegisteredPlugin,
        cyclonedx_sbom_bytes: bytes,
    ) -> None:
        """Test complete workflow for SBOM with vulnerabilities."""
        import subprocess

        sbom = SBOM.objects.create(
            name="osv-test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.cdx.json",
            source="test",
        )

        mock_process = subprocess.CompletedProcess(args=[], returncode=1, stdout=MOCK_OSV_OUTPUT_WITH_VULNS, stderr="")

        with (
            patch(
                "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
                return_value=(sbom, cyclonedx_sbom_bytes),
            ),
            patch("subprocess.run", return_value=mock_process),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="osv",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        assessment_run = AssessmentRun.objects.filter(sbom=sbom, plugin_name="osv").first()
        assert assessment_run is not None
        assert assessment_run.status == RunStatus.COMPLETED.value
        assert assessment_run.category == "security"
        assert assessment_run.result is not None
        assert assessment_run.result["summary"]["total_findings"] == 1
        assert assessment_run.result["summary"]["by_severity"]["high"] == 1
        assert assessment_run.completed_at is not None

        # Verify findings
        findings = assessment_run.result["findings"]
        assert len(findings) == 1
        assert findings[0]["id"] == "GHSA-jf85-cpcp-j695"
        assert findings[0]["component"]["name"] == "lodash"

    def test_full_assessment_workflow_no_vulns(
        self,
        team: Team,
        component: Component,
        osv_plugin: RegisteredPlugin,
        cyclonedx_sbom_bytes: bytes,
    ) -> None:
        """Test complete workflow for SBOM with no vulnerabilities."""
        import subprocess

        sbom = SBOM.objects.create(
            name="osv-clean-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="clean.cdx.json",
            source="test",
        )

        mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch(
                "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
                return_value=(sbom, cyclonedx_sbom_bytes),
            ),
            patch("subprocess.run", return_value=mock_process),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="osv",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        assessment_run = AssessmentRun.objects.filter(sbom=sbom, plugin_name="osv").first()
        assert assessment_run is not None
        assert assessment_run.status == RunStatus.COMPLETED.value
        assert assessment_run.result["summary"]["total_findings"] == 0

    def test_assessment_run_stored_correctly(
        self,
        team: Team,
        component: Component,
        osv_plugin: RegisteredPlugin,
        cyclonedx_sbom_bytes: bytes,
    ) -> None:
        """Test AssessmentRun record has correct denormalized fields."""
        import subprocess

        sbom = SBOM.objects.create(
            name="osv-fields-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="fields.cdx.json",
            source="test",
        )

        mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch(
                "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
                return_value=(sbom, cyclonedx_sbom_bytes),
            ),
            patch("subprocess.run", return_value=mock_process),
        ):
            run_assessment_task(
                sbom_id=str(sbom.id),
                plugin_name="osv",
                run_reason=RunReason.ON_UPLOAD.value,
            )

        run = AssessmentRun.objects.get(sbom=sbom, plugin_name="osv")
        assert run.plugin_version == "1.0.0"
        assert run.category == "security"
        assert run.run_reason == RunReason.ON_UPLOAD.value
        assert run.result_schema_version == "1.0"
        assert run.input_content_digest is not None

    def test_signal_skips_old_flow_when_osv_plugin_enabled(
        self,
        team: Team,
        component: Component,
        osv_plugin: RegisteredPlugin,
    ) -> None:
        """Test that trigger_vulnerability_scan skips old flow when OSV plugin is enabled."""
        from sbomify.apps.sboms.signals import _team_has_osv_plugin_enabled, trigger_vulnerability_scan

        # Enable OSV plugin for the team
        TeamPluginSettings.objects.create(
            team=team,
            enabled_plugins=["osv"],
        )

        assert _team_has_osv_plugin_enabled(team) is True

        sbom = SBOM.objects.create(
            name="signal-test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="signal.cdx.json",
            source="test",
        )

        # The old scan task should NOT be called
        with patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified") as mock_old_task:
            trigger_vulnerability_scan(sender=SBOM, instance=sbom, created=True)
            mock_old_task.send_with_options.assert_not_called()

    def test_signal_uses_old_flow_when_osv_plugin_not_enabled(
        self,
        team: Team,
        component: Component,
    ) -> None:
        """Test that trigger_vulnerability_scan uses old flow when OSV plugin is NOT enabled."""
        from sbomify.apps.sboms.signals import _team_has_osv_plugin_enabled, trigger_vulnerability_scan

        assert _team_has_osv_plugin_enabled(team) is False

        sbom = SBOM.objects.create(
            name="signal-old-flow-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="old.cdx.json",
            source="test",
        )

        # The old scan task SHOULD be called (wrapped in run_on_commit)
        with patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified"):
            trigger_vulnerability_scan(sender=SBOM, instance=sbom, created=True)

    def test_plugin_registered_in_post_migrate(self) -> None:
        """Test that the OSV plugin is registered by the apps.py post_migrate handler."""
        from sbomify.apps.plugins.apps import PluginsConfig

        config = PluginsConfig("sbomify.apps.plugins", __import__("sbomify.apps.plugins"))
        config._register_builtin_plugins()

        plugin = RegisteredPlugin.objects.get(name="osv")
        assert plugin.display_name == "OSV Vulnerability Scanner"
        assert plugin.category == "security"
        assert plugin.is_enabled is True
        assert plugin.is_beta is True
        assert plugin.default_config["timeout"] == 300


@pytest.mark.django_db
class TestScheduledOSVScanTasks:
    """Tests for scheduled OSV scan tasks."""

    @pytest.fixture
    def community_team(self) -> Team:
        """Create a community team."""
        return Team.objects.create(
            name="Community Team",
            key="community-osv-test",
            billing_plan=None,
        )

    @pytest.fixture
    def business_team(self) -> Team:
        """Create a business team."""
        BillingPlan.objects.get_or_create(key="business", defaults={"name": "Business Plan"})
        return Team.objects.create(
            name="Business Team",
            key="business-osv-test",
            billing_plan="business",
        )

    def test_is_community_team(self, community_team: Team) -> None:
        """Test community team filter."""
        from sbomify.apps.plugins.tasks import _is_community_team, _is_paid_team

        assert _is_community_team(community_team) is True
        assert _is_paid_team(community_team) is False

    def test_is_paid_team(self, business_team: Team) -> None:
        """Test paid team filter."""
        from sbomify.apps.plugins.tasks import _is_community_team, _is_paid_team

        assert _is_paid_team(business_team) is True
        assert _is_community_team(business_team) is False
