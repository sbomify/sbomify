from __future__ import annotations

import uuid

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus, ControlStatusLog
from sbomify.apps.controls.services.automation_service import (
    PLUGIN_CONTROL_MAP,
    auto_update_from_assessment,
    get_automation_mappings,
    sync_from_latest_assessments,
)
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunStatus


@pytest.fixture
def automation_catalog(sample_team_with_owner_member):
    """Catalog with controls that match PLUGIN_CONTROL_MAP entries."""
    team = sample_team_with_owner_member.team
    return ControlCatalog.objects.create(
        team=team, name="SOC 2 Type II", version="2024", source=ControlCatalog.Source.BUILTIN
    )


@pytest.fixture
def automation_controls(automation_catalog):
    """Create controls matching the NTIA and OSV plugin mappings."""
    controls = []
    control_defs = [
        ("CC2.1", "Information quality — communication", "Security"),
        ("CC2.2", "Internal communication of objectives", "Security"),
        ("CC2.3", "External communication", "Security"),
        ("CC6.8", "Malware prevention", "Security"),
        ("CC7.1", "Detection and monitoring of threats", "Availability"),
        ("CC7.2", "Monitoring of system components", "Availability"),
        ("CC7.3", "Evaluation of security events", "Availability"),
    ]
    for i, (cid, title, group) in enumerate(control_defs):
        controls.append(
            Control.objects.create(catalog=automation_catalog, group=group, control_id=cid, title=title, sort_order=i)
        )
    return controls


@pytest.fixture
def _sbom_for_team(sample_team_with_owner_member):
    """Create a minimal component + SBOM belonging to the test team."""
    from sbomify.apps.sboms.models import SBOM, Component

    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="test-component", team=team)
    sbom = SBOM.objects.create(component=component, name="test-sbom")
    return sbom


@pytest.mark.django_db
class TestAutoUpdateFromAssessment:
    def test_passing_assessment_updates_not_implemented_to_compliant(
        self, sample_team_with_owner_member, automation_controls
    ) -> None:
        team = sample_team_with_owner_member.team
        result = auto_update_from_assessment(team, "ntia-minimum-elements-2021", passed=True)
        assert result.ok
        assert result.value == 3  # CC2.1, CC2.2, CC2.3

        # Verify all three controls are now compliant
        for control in automation_controls[:3]:
            cs = ControlStatus.objects.get(control=control, product__isnull=True)
            assert cs.status == ControlStatus.Status.COMPLIANT
            assert "ntia-minimum-elements-2021" in cs.notes
            assert cs.updated_by is None  # system-level update

    def test_passing_assessment_does_not_downgrade_existing_compliant(
        self, sample_team_with_owner_member, automation_controls, sample_user
    ) -> None:
        team = sample_team_with_owner_member.team

        # Manually set CC2.1 to compliant and CC2.2 to partial
        ControlStatus.objects.create(
            control=automation_controls[0], product=None, status=ControlStatus.Status.COMPLIANT, updated_by=sample_user
        )
        ControlStatus.objects.create(
            control=automation_controls[1], product=None, status=ControlStatus.Status.PARTIAL, updated_by=sample_user
        )

        result = auto_update_from_assessment(team, "ntia-minimum-elements-2021", passed=True)
        assert result.ok
        # Only CC2.3 should be updated (CC2.1 already compliant, CC2.2 is partial — not overwritten)
        assert result.value == 1

        # CC2.1 unchanged (still manually set)
        cs1 = ControlStatus.objects.get(control=automation_controls[0], product__isnull=True)
        assert cs1.status == ControlStatus.Status.COMPLIANT
        assert cs1.updated_by == sample_user  # still manual

        # CC2.2 unchanged (partial, not overwritten)
        cs2 = ControlStatus.objects.get(control=automation_controls[1], product__isnull=True)
        assert cs2.status == ControlStatus.Status.PARTIAL

    def test_failing_assessment_does_not_change_statuses(
        self, sample_team_with_owner_member, automation_controls
    ) -> None:
        team = sample_team_with_owner_member.team
        result = auto_update_from_assessment(team, "ntia-minimum-elements-2021", passed=False)
        assert result.ok
        assert result.value == 0

        # No ControlStatus records should be created
        assert ControlStatus.objects.filter(control__in=automation_controls).count() == 0

    def test_unknown_plugin_returns_zero_updates(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = auto_update_from_assessment(team, "nonexistent-plugin", passed=True)
        assert result.ok
        assert result.value == 0

    def test_creates_status_log_entry(self, sample_team_with_owner_member, automation_controls) -> None:
        team = sample_team_with_owner_member.team
        auto_update_from_assessment(team, "ntia-minimum-elements-2021", passed=True)

        logs = ControlStatusLog.objects.filter(control__in=automation_controls[:3])
        assert logs.count() == 3
        for log in logs:
            assert log.new_status == ControlStatus.Status.COMPLIANT
            assert log.changed_by is None

    def test_no_active_catalog_returns_zero(self, sample_team_with_owner_member) -> None:
        """When the team has no active catalog, nothing should be updated."""
        team = sample_team_with_owner_member.team
        result = auto_update_from_assessment(team, "ntia-minimum-elements-2021", passed=True)
        assert result.ok
        assert result.value == 0


@pytest.mark.django_db
class TestSyncFromLatestAssessments:
    def test_sync_with_passing_assessment(
        self, sample_team_with_owner_member, automation_controls, _sbom_for_team
    ) -> None:
        team = sample_team_with_owner_member.team

        # Create a completed passing NTIA assessment run
        AssessmentRun.objects.create(
            id=uuid.uuid4(),
            sbom=_sbom_for_team,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category="compliance",
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {
                    "total_findings": 0,
                    "pass_count": 5,
                    "fail_count": 0,
                    "error_count": 0,
                }
            },
        )

        result = sync_from_latest_assessments(team)
        assert result.ok
        data = result.value
        assert data["total_updated"] == 3
        assert data["by_plugin"]["ntia-minimum-elements-2021"] == 3

    def test_sync_with_failing_assessment(
        self, sample_team_with_owner_member, automation_controls, _sbom_for_team
    ) -> None:
        team = sample_team_with_owner_member.team

        # Create a completed failing NTIA assessment run
        AssessmentRun.objects.create(
            id=uuid.uuid4(),
            sbom=_sbom_for_team,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category="compliance",
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {
                    "total_findings": 2,
                    "pass_count": 3,
                    "fail_count": 2,
                    "error_count": 0,
                }
            },
        )

        result = sync_from_latest_assessments(team)
        assert result.ok
        assert result.value["total_updated"] == 0

    def test_sync_with_no_assessments(self, sample_team_with_owner_member, automation_controls) -> None:
        team = sample_team_with_owner_member.team
        result = sync_from_latest_assessments(team)
        assert result.ok
        assert result.value["total_updated"] == 0
        assert result.value["by_plugin"] == {}

    def test_sync_with_security_plugin_passing(
        self, sample_team_with_owner_member, automation_controls, _sbom_for_team
    ) -> None:
        team = sample_team_with_owner_member.team

        # Create a completed passing OSV security assessment (no vulnerabilities)
        AssessmentRun.objects.create(
            id=uuid.uuid4(),
            sbom=_sbom_for_team,
            plugin_name="osv",
            plugin_version="1.0.0",
            plugin_config_hash="def456",
            category="security",
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {
                    "total_findings": 0,
                    "by_severity": {
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                    },
                }
            },
        )

        result = sync_from_latest_assessments(team)
        assert result.ok
        # OSV maps to CC6.8, CC7.1, CC7.2, CC7.3
        assert result.value["total_updated"] == 4
        assert result.value["by_plugin"]["osv"] == 4


@pytest.mark.django_db
class TestGetAutomationMappings:
    def test_returns_mapping_dict(self) -> None:
        mappings = get_automation_mappings()
        assert isinstance(mappings, dict)
        assert "ntia-minimum-elements-2021" in mappings
        assert "osv" in mappings
        assert mappings == PLUGIN_CONTROL_MAP
