"""Tests for public assessment utilities."""

import pytest
from django.contrib.auth import get_user_model

from sbomify.apps.core.models import Component, Product, Project, ProjectComponent
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.public_assessment_utils import (
    PassingAssessment,
    get_component_assessment_status,
    get_product_assessment_status,
    get_project_assessment_status,
    get_sbom_passing_assessments,
    passing_assessments_to_dict,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM, ProductProject
from sbomify.apps.teams.models import Member, Team

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def team(db, user):
    """Create a test team."""
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        is_public=True,
    )
    Member.objects.create(user=user, team=team, role="owner")
    return team


@pytest.fixture
def ntia_plugin(db):
    """Create a registered NTIA plugin."""
    plugin, _ = RegisteredPlugin.objects.get_or_create(
        name="ntia-minimum-elements-2021",
        defaults={
            "display_name": "NTIA Minimum Elements",
            "description": "NTIA minimum elements compliance check",
            "category": AssessmentCategory.COMPLIANCE.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.NTIAMinimumElementsPlugin",
            "is_enabled": True,
        },
    )
    return plugin


@pytest.fixture
def cisa_plugin(db):
    """Create a registered CISA plugin."""
    plugin, _ = RegisteredPlugin.objects.get_or_create(
        name="cisa-minimum-elements-2025",
        defaults={
            "display_name": "CISA Minimum Elements",
            "description": "CISA minimum elements compliance check",
            "category": AssessmentCategory.COMPLIANCE.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.CISAMinimumElementsPlugin",
            "is_enabled": True,
        },
    )
    return plugin


@pytest.fixture
def public_component(db, team):
    """Create a public SBOM component."""
    return Component.objects.create(
        name="Public Component",
        team=team,
        is_public=True,
        component_type="sbom",
    )


@pytest.fixture
def sbom(db, public_component):
    """Create an SBOM for the component."""
    return SBOM.objects.create(
        name="Test SBOM",
        component=public_component,
        format="cyclonedx",
        format_version="1.6",
    )


class TestGetSbomPassingAssessments:
    """Tests for get_sbom_passing_assessments function."""

    def test_no_assessments_returns_empty_list(self, sbom):
        """When SBOM has no assessments, returns empty list."""
        result = get_sbom_passing_assessments(str(sbom.id))
        assert result == []

    def test_passing_assessment_is_returned(self, sbom, ntia_plugin):
        """When SBOM has a passing assessment, it's included in result."""
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {
                    "total_findings": 10,
                    "pass_count": 10,
                    "fail_count": 0,
                    "error_count": 0,
                }
            },
        )

        result = get_sbom_passing_assessments(str(sbom.id))
        assert len(result) == 1
        assert result[0].plugin_name == "ntia-minimum-elements-2021"
        # Display name comes from the registered plugin
        assert "NTIA" in result[0].plugin_display_name

    def test_failing_assessment_is_excluded(self, sbom, ntia_plugin):
        """When SBOM has a failing assessment, it's not included in result."""
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {
                    "total_findings": 10,
                    "pass_count": 8,
                    "fail_count": 2,
                    "error_count": 0,
                }
            },
        )

        result = get_sbom_passing_assessments(str(sbom.id))
        assert result == []

    def test_pending_assessment_is_excluded(self, sbom, ntia_plugin):
        """Pending assessments are not included."""
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.PENDING.value,
        )

        result = get_sbom_passing_assessments(str(sbom.id))
        assert result == []

    def test_latest_run_is_used(self, sbom, ntia_plugin):
        """When multiple runs exist, only latest is considered."""
        # Create an older failing run
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {"fail_count": 5, "error_count": 0}
            },
        )

        # Create a newer passing run
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.MANUAL.value,
            status=RunStatus.COMPLETED.value,
            result={
                "summary": {"fail_count": 0, "error_count": 0}
            },
        )

        result = get_sbom_passing_assessments(str(sbom.id))
        assert len(result) == 1


class TestGetComponentAssessmentStatus:
    """Tests for get_component_assessment_status function."""

    def test_component_without_sboms_has_no_assessments(self, public_component):
        """Component with no SBOMs has no assessments."""
        # Ensure no SBOMs exist for this component
        SBOM.objects.filter(component=public_component).delete()

        result = get_component_assessment_status(public_component)
        assert result.has_assessments is False
        assert result.all_pass is False
        assert result.passing_assessments == []

    def test_component_with_passing_assessment(self, public_component, sbom, ntia_plugin):
        """Component with all SBOMs passing shows passing assessments."""
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        result = get_component_assessment_status(public_component)
        assert result.has_assessments is True
        assert result.all_pass is True
        assert len(result.passing_assessments) == 1

    def test_component_with_multiple_sboms_requires_all_to_pass(
        self, public_component, sbom, ntia_plugin
    ):
        """All SBOMs in component must pass for component to pass."""
        # Create a second SBOM
        sbom2 = SBOM.objects.create(
            name="Test SBOM 2",
            component=public_component,
            format="cyclonedx",
            format_version="1.6",
        )

        # First SBOM passes
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        # Second SBOM fails
        AssessmentRun.objects.create(
            sbom=sbom2,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 2, "error_count": 0}},
        )

        result = get_component_assessment_status(public_component)
        # Should not be in passing_assessments since not all SBOMs pass
        assert result.has_assessments is True
        assert result.all_pass is False
        assert len(result.passing_assessments) == 0


class TestGetProjectAssessmentStatus:
    """Tests for get_project_assessment_status function."""

    def test_project_with_all_passing_components(
        self, team, public_component, sbom, ntia_plugin
    ):
        """Project shows passing when all components pass."""
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True,
        )
        ProjectComponent.objects.create(project=project, component=public_component)

        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        result = get_project_assessment_status(project)
        assert result.has_assessments is True
        assert result.all_pass is True
        assert len(result.passing_assessments) == 1


class TestGetProductAssessmentStatus:
    """Tests for get_product_assessment_status function."""

    def test_product_with_all_passing_projects(
        self, team, public_component, sbom, ntia_plugin
    ):
        """Product shows passing when all projects pass."""
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True,
        )
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True,
        )
        ProductProject.objects.create(product=product, project=project)
        ProjectComponent.objects.create(project=project, component=public_component)

        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        result = get_product_assessment_status(product)
        assert result.has_assessments is True
        assert result.all_pass is True
        assert len(result.passing_assessments) == 1


class TestPassingAssessmentsToDictHelper:
    """Tests for passing_assessments_to_dict helper."""

    def test_converts_to_dict(self):
        """Converts list of PassingAssessment to list of dicts."""
        assessments = [
            PassingAssessment(
                plugin_name="test-plugin",
                plugin_display_name="Test Plugin",
                category="compliance",
            )
        ]
        result = passing_assessments_to_dict(assessments)
        assert result == [
            {
                "plugin_name": "test-plugin",
                "display_name": "Test Plugin",
                "category": "compliance",
            }
        ]

    def test_empty_list(self):
        """Returns empty list for empty input."""
        result = passing_assessments_to_dict([])
        assert result == []
