"""Tests for the SBOM compliance service (BSI TR-03183-2 gate)."""

from __future__ import annotations

import pytest

from sbomify.apps.compliance.services.sbom_compliance_service import (
    BSI_PLUGIN_NAME,
    check_sbom_gate,
    get_bsi_assessment_status,
)
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM, Component, Product, Project, ProductProject, ProjectComponent


def _create_product_with_component(team, *, component_name: str = "comp-1") -> tuple[Product, Component]:
    """Helper: create a product with a project and a component linked through it."""
    product = Product.objects.create(name="Test Product", team=team)
    project = Project.objects.create(name="Test Project", team=team)
    ProductProject.objects.create(product=product, project=project)
    component = Component.objects.create(name=component_name, team=team)
    ProjectComponent.objects.create(project=project, component=component)
    return product, component


def _create_sbom(component: Component, *, fmt: str = "cyclonedx", fmt_version: str = "1.6") -> SBOM:
    """Helper: create an SBOM for a component."""
    return SBOM.objects.create(
        component=component,
        name="test.cdx.json",
        format=fmt,
        format_version=fmt_version,
    )


def _create_assessment_run(
    sbom: SBOM,
    *,
    status: str = "completed",
    pass_count: int = 5,
    fail_count: int = 0,
    warning_count: int = 0,
) -> AssessmentRun:
    """Helper: create a BSI AssessmentRun for an SBOM."""
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=BSI_PLUGIN_NAME,
        plugin_version="1.0.0",
        plugin_config_hash="abc123",
        category="compliance",
        run_reason="on_upload",
        status=status,
        result={
            "summary": {
                "pass_count": pass_count,
                "fail_count": fail_count,
                "warning_count": warning_count,
            }
        },
    )


@pytest.mark.django_db
class TestGetBsiAssessmentStatus:
    """Tests for get_bsi_assessment_status()."""

    def test_no_components(self, sample_team_with_owner_member):
        """Empty product with no components returns empty result and gate=False."""
        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="Empty Product", team=team)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert data["components"] == []
        assert data["summary"]["total_components"] == 0
        assert data["summary"]["components_with_sbom"] == 0
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False

    def test_component_without_sbom(self, sample_team_with_owner_member):
        """Component with no SBOM should have has_sbom=False and gate=False."""
        team = sample_team_with_owner_member.team
        product, _component = _create_product_with_component(team)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert len(data["components"]) == 1
        comp = data["components"][0]
        assert comp["has_sbom"] is False
        assert comp["sbom_format"] is None
        assert comp["sbom_format_version"] is None
        assert comp["format_compliant"] is False
        assert comp["bsi_assessment"] is None
        assert data["summary"]["overall_gate"] is False

    def test_sbom_without_bsi_assessment(self, sample_team_with_owner_member):
        """Component with SBOM but no BSI assessment should have bsi_assessment=None."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        _create_sbom(component)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        comp = data["components"][0]
        assert comp["has_sbom"] is True
        assert comp["sbom_format"] == "cyclonedx"
        assert comp["bsi_assessment"] is None
        assert data["summary"]["components_with_sbom"] == 1
        assert data["summary"]["overall_gate"] is False

    def test_passing_bsi_assessment(self, sample_team_with_owner_member):
        """Component with passing BSI assessment should set gate=True."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", pass_count=5, fail_count=0)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        comp = data["components"][0]
        assert comp["bsi_assessment"] is not None
        assert comp["bsi_assessment"]["status"] == "completed"
        assert comp["bsi_assessment"]["pass_count"] == 5
        assert comp["bsi_assessment"]["fail_count"] == 0
        assert data["summary"]["components_passing_bsi"] == 1
        assert data["summary"]["overall_gate"] is True

    def test_failing_bsi_assessment(self, sample_team_with_owner_member):
        """Component with failing BSI assessment (fail_count > 0) should set gate=False."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", pass_count=3, fail_count=2)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        comp = data["components"][0]
        assert comp["bsi_assessment"]["fail_count"] == 2
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False

    def test_failed_status_assessment(self, sample_team_with_owner_member):
        """Assessment with status=failed should not count as passing."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="failed", pass_count=0, fail_count=0)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False

    def test_pending_status_assessment(self, sample_team_with_owner_member):
        """Assessment with status=pending should not count as passing."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="pending", pass_count=0, fail_count=0)

        result = get_bsi_assessment_status(product)

        assert result.ok
        data = result.value
        assert data["summary"]["components_passing_bsi"] == 0
        assert data["summary"]["overall_gate"] is False


@pytest.mark.django_db
class TestFormatCompliance:
    """Tests for SBOM format version compliance checking."""

    def test_cyclonedx_1_6_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team)
        _create_sbom(component, fmt="cyclonedx", fmt_version="1.6")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is True

    def test_cyclonedx_1_5_not_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-cdx15")
        _create_sbom(component, fmt="cyclonedx", fmt_version="1.5")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is False

    def test_spdx_3_0_1_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-spdx301")
        _create_sbom(component, fmt="spdx", fmt_version="3.0.1")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is True

    def test_spdx_2_3_not_compliant(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-spdx23")
        _create_sbom(component, fmt="spdx", fmt_version="2.3")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is False

    def test_cyclonedx_1_7_compliant(self, sample_team_with_owner_member):
        """Versions above the minimum should also be compliant."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-cdx17")
        _create_sbom(component, fmt="cyclonedx", fmt_version="1.7")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is True

    def test_unknown_format_not_compliant(self, sample_team_with_owner_member):
        """Unknown SBOM formats should not be considered compliant."""
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="comp-unknown")
        _create_sbom(component, fmt="unknown", fmt_version="1.0")

        result = get_bsi_assessment_status(product)
        assert result.value["components"][0]["format_compliant"] is False


@pytest.mark.django_db
class TestCheckSbomGate:
    """Tests for check_sbom_gate()."""

    def test_gate_false_no_components(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product = Product.objects.create(name="Empty Gate Product", team=team)

        result = check_sbom_gate(product)
        assert result.ok
        assert result.value is False

    def test_gate_true_with_passing_assessment(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="gate-pass")
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", fail_count=0)

        result = check_sbom_gate(product)
        assert result.ok
        assert result.value is True

    def test_gate_false_with_failing_assessment(self, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        product, component = _create_product_with_component(team, component_name="gate-fail")
        sbom = _create_sbom(component)
        _create_assessment_run(sbom, status="completed", fail_count=3)

        result = check_sbom_gate(product)
        assert result.ok
        assert result.value is False
