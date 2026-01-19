"""Tests for public assessment utilities."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model

from sbomify.apps.core.models import Component, Product, Project, ProjectComponent
from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
from sbomify.apps.plugins.public_assessment_utils import (
    PassingAssessment,
    get_component_assessment_status,
    get_component_latest_sbom_assessment_status,
    get_latest_sbom_for_component,
    get_product_assessment_status,
    get_product_latest_sbom_assessment_status,
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
        visibility=Component.Visibility.PUBLIC,
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
            result={"summary": {"fail_count": 5, "error_count": 0}},
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
            result={"summary": {"fail_count": 0, "error_count": 0}},
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

    def test_component_with_multiple_sboms_requires_all_to_pass(self, public_component, sbom, ntia_plugin):
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

    def test_project_with_all_passing_components(self, team, public_component, sbom, ntia_plugin):
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

    def test_product_with_all_passing_projects(self, team, public_component, sbom, ntia_plugin):
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


class TestGetLatestSbomForComponent:
    """Tests for get_latest_sbom_for_component function."""

    def test_returns_none_for_component_without_sboms(self, public_component):
        """Returns None when component has no SBOMs."""
        SBOM.objects.filter(component=public_component).delete()
        result = get_latest_sbom_for_component(public_component)
        assert result is None

    def test_returns_latest_sbom(self, public_component, sbom):
        """Returns the most recent SBOM by created_at."""
        # Create an older SBOM
        older_sbom = SBOM.objects.create(
            name="Older SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.5",
        )
        # Force older timestamp
        SBOM.objects.filter(pk=older_sbom.pk).update(created_at=sbom.created_at - timedelta(days=1))

        # Create a newer SBOM
        newer_sbom = SBOM.objects.create(
            name="Newer SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.6",
        )

        result = get_latest_sbom_for_component(public_component)
        assert result.id == newer_sbom.id


class TestGetComponentLatestSbomAssessmentStatus:
    """Tests for get_component_latest_sbom_assessment_status function."""

    def test_component_without_sboms_has_no_assessments(self, public_component):
        """Component with no SBOMs has no assessments."""
        SBOM.objects.filter(component=public_component).delete()
        result = get_component_latest_sbom_assessment_status(public_component)
        assert result.has_assessments is False
        assert result.all_pass is False
        assert result.passing_assessments == []

    def test_uses_only_latest_sbom(self, public_component, ntia_plugin):
        """Only the latest SBOM's assessments are considered."""
        # Create older SBOM that passes
        older_sbom = SBOM.objects.create(
            name="Older SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.5",
        )
        AssessmentRun.objects.create(
            sbom=older_sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        # Create newer SBOM that fails
        newer_sbom = SBOM.objects.create(
            name="Newer SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.6",
        )
        AssessmentRun.objects.create(
            sbom=newer_sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 2, "error_count": 0}},
        )

        result = get_component_latest_sbom_assessment_status(public_component)
        # Only latest (failing) SBOM should be considered
        # has_assessments is True because assessments were run
        # all_pass is False because the assessment failed
        # passing_assessments is empty because no assessments passed
        assert result.has_assessments is True
        assert result.all_pass is False
        assert len(result.passing_assessments) == 0

    def test_latest_sbom_passing_returns_assessments(self, public_component, ntia_plugin):
        """When latest SBOM passes, assessments are returned."""
        # Create older SBOM that fails
        older_sbom = SBOM.objects.create(
            name="Older SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.5",
        )
        AssessmentRun.objects.create(
            sbom=older_sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 5, "error_count": 0}},
        )

        # Create newer SBOM that passes
        newer_sbom = SBOM.objects.create(
            name="Newer SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.6",
        )
        AssessmentRun.objects.create(
            sbom=newer_sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        result = get_component_latest_sbom_assessment_status(public_component)
        # Only latest (passing) SBOM should be considered
        assert result.has_assessments is True
        assert result.all_pass is True
        assert len(result.passing_assessments) == 1


class TestGetProductLatestSbomAssessmentStatus:
    """Tests for get_product_latest_sbom_assessment_status function."""

    def test_product_without_public_components_has_no_assessments(self, team):
        """Product without public components has no assessments."""
        product = Product.objects.create(
            name="Empty Product",
            team=team,
            is_public=True,
        )
        result = get_product_latest_sbom_assessment_status(product)
        assert result.has_assessments is False
        assert result.all_pass is False
        assert result.passing_assessments == []

    def test_uses_only_latest_sbom_per_component(self, team, public_component, ntia_plugin):
        """Only the latest SBOM of each component is considered."""
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

        # Create older SBOM that fails
        older_sbom = SBOM.objects.create(
            name="Older SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.5",
        )
        AssessmentRun.objects.create(
            sbom=older_sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 3, "error_count": 0}},
        )

        # Create newer SBOM that passes
        newer_sbom = SBOM.objects.create(
            name="Newer SBOM",
            component=public_component,
            format="cyclonedx",
            format_version="1.6",
        )
        AssessmentRun.objects.create(
            sbom=newer_sbom,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        result = get_product_latest_sbom_assessment_status(product)
        # Only latest (passing) SBOM should be considered
        assert result.has_assessments is True
        assert result.all_pass is True
        assert len(result.passing_assessments) == 1

    def test_all_components_latest_sbom_must_pass(self, team, ntia_plugin):
        """All components' latest SBOMs must pass for product to pass."""
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

        # Create first component with passing latest SBOM
        component1 = Component.objects.create(
            name="Component 1",
            team=team,
            visibility=Component.Visibility.PUBLIC,
            component_type="sbom",
        )
        ProjectComponent.objects.create(project=project, component=component1)
        sbom1 = SBOM.objects.create(
            name="SBOM 1",
            component=component1,
            format="cyclonedx",
            format_version="1.6",
        )
        AssessmentRun.objects.create(
            sbom=sbom1,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc123",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        # Create second component with failing latest SBOM
        component2 = Component.objects.create(
            name="Component 2",
            team=team,
            visibility=Component.Visibility.PUBLIC,
            component_type="sbom",
        )
        ProjectComponent.objects.create(project=project, component=component2)
        sbom2 = SBOM.objects.create(
            name="SBOM 2",
            component=component2,
            format="cyclonedx",
            format_version="1.6",
        )
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

        result = get_product_latest_sbom_assessment_status(product)
        # One component passes, one fails - no common passing assessments
        assert result.has_assessments is True
        assert result.all_pass is False
        assert len(result.passing_assessments) == 0

    def test_multiple_plugins_all_must_pass(self, team, ntia_plugin, cisa_plugin):
        """All plugins must pass on all components' latest SBOMs."""
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

        component = Component.objects.create(
            name="Component",
            team=team,
            visibility=Component.Visibility.PUBLIC,
            component_type="sbom",
        )
        ProjectComponent.objects.create(project=project, component=component)

        sbom = SBOM.objects.create(
            name="SBOM",
            component=component,
            format="cyclonedx",
            format_version="1.6",
        )

        # Both plugins pass
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
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="cisa-minimum-elements-2025",
            plugin_version="1.0.0",
            plugin_config_hash="def456",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        result = get_product_latest_sbom_assessment_status(product)
        assert result.has_assessments is True
        assert result.all_pass is True
        assert len(result.passing_assessments) == 2


@pytest.mark.django_db
class TestGetProductsLatestSbomAssessmentsBatch:
    """Tests for get_products_latest_sbom_assessments_batch function."""

    def test_empty_product_list_returns_empty_dict(self):
        """Empty list of products returns empty dict."""
        from sbomify.apps.plugins.public_assessment_utils import get_products_latest_sbom_assessments_batch

        result = get_products_latest_sbom_assessments_batch([])
        assert result == {}

    def test_batch_matches_individual_results(self, team, ntia_plugin):
        """Batch function returns same results as individual calls."""
        from sbomify.apps.plugins.public_assessment_utils import (
            get_product_latest_sbom_assessment_status,
            get_products_latest_sbom_assessments_batch,
        )

        # Create two products with components and SBOMs
        product1 = Product.objects.create(name="Product 1", team=team, is_public=True)
        product2 = Product.objects.create(name="Product 2", team=team, is_public=True)

        project1 = Project.objects.create(name="Project 1", team=team, is_public=True)
        project2 = Project.objects.create(name="Project 2", team=team, is_public=True)

        ProductProject.objects.create(product=product1, project=project1)
        ProductProject.objects.create(product=product2, project=project2)

        comp1 = Component.objects.create(
            name="Comp 1", team=team, visibility=Component.Visibility.PUBLIC, component_type="sbom"
        )
        comp2 = Component.objects.create(
            name="Comp 2", team=team, visibility=Component.Visibility.PUBLIC, component_type="sbom"
        )

        ProjectComponent.objects.create(project=project1, component=comp1)
        ProjectComponent.objects.create(project=project2, component=comp2)

        sbom1 = SBOM.objects.create(name="SBOM 1", component=comp1, format="cyclonedx", format_version="1.6")
        sbom2 = SBOM.objects.create(name="SBOM 2", component=comp2, format="cyclonedx", format_version="1.6")

        # Product 1 passes
        AssessmentRun.objects.create(
            sbom=sbom1,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        # Product 2 fails
        AssessmentRun.objects.create(
            sbom=sbom2,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 3, "error_count": 0}},
        )

        # Get individual results
        individual_1 = get_product_latest_sbom_assessment_status(product1)
        individual_2 = get_product_latest_sbom_assessment_status(product2)

        # Get batch results
        batch_result = get_products_latest_sbom_assessments_batch([product1, product2])

        # Verify batch matches individual
        assert str(product1.id) in batch_result
        assert str(product2.id) in batch_result

        batch_1_plugins = {a.plugin_name for a in batch_result[str(product1.id)]}
        individual_1_plugins = {a.plugin_name for a in individual_1.passing_assessments}
        assert batch_1_plugins == individual_1_plugins

        batch_2_plugins = {a.plugin_name for a in batch_result[str(product2.id)]}
        individual_2_plugins = {a.plugin_name for a in individual_2.passing_assessments}
        assert batch_2_plugins == individual_2_plugins

    def test_product_without_components_returns_empty_list(self, team):
        """Product with no public components returns empty list of assessments."""
        from sbomify.apps.plugins.public_assessment_utils import get_products_latest_sbom_assessments_batch

        product = Product.objects.create(name="Empty Product", team=team, is_public=True)
        # Create project but don't add any components
        project = Project.objects.create(name="Empty Project", team=team, is_public=True)
        ProductProject.objects.create(product=product, project=project)

        result = get_products_latest_sbom_assessments_batch([product])
        assert result[str(product.id)] == []


@pytest.mark.django_db
class TestGetComponentsLatestSbomAssessmentsBatch:
    """Tests for get_components_latest_sbom_assessments_batch function."""

    def test_empty_component_list_returns_empty_dict(self):
        """Empty list of components returns empty dict."""
        from sbomify.apps.plugins.public_assessment_utils import get_components_latest_sbom_assessments_batch

        result = get_components_latest_sbom_assessments_batch([])
        assert result == {}

    def test_batch_matches_individual_results(self, team, ntia_plugin):
        """Batch function returns same results as individual calls."""
        from sbomify.apps.plugins.public_assessment_utils import (
            get_component_latest_sbom_assessment_status,
            get_components_latest_sbom_assessments_batch,
        )

        # Create two components with SBOMs
        comp1 = Component.objects.create(
            name="Comp 1", team=team, visibility=Component.Visibility.PUBLIC, component_type="sbom"
        )
        comp2 = Component.objects.create(
            name="Comp 2", team=team, visibility=Component.Visibility.PUBLIC, component_type="sbom"
        )

        sbom1 = SBOM.objects.create(name="SBOM 1", component=comp1, format="cyclonedx", format_version="1.6")
        sbom2 = SBOM.objects.create(name="SBOM 2", component=comp2, format="cyclonedx", format_version="1.6")

        # Component 1 passes
        AssessmentRun.objects.create(
            sbom=sbom1,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 0, "error_count": 0}},
        )

        # Component 2 fails
        AssessmentRun.objects.create(
            sbom=sbom2,
            plugin_name="ntia-minimum-elements-2021",
            plugin_version="1.0.0",
            plugin_config_hash="abc",
            category=AssessmentCategory.COMPLIANCE.value,
            run_reason=RunReason.ON_UPLOAD.value,
            status=RunStatus.COMPLETED.value,
            result={"summary": {"fail_count": 3, "error_count": 0}},
        )

        # Get individual results
        individual_1 = get_component_latest_sbom_assessment_status(comp1)
        individual_2 = get_component_latest_sbom_assessment_status(comp2)

        # Get batch results
        batch_result = get_components_latest_sbom_assessments_batch([comp1, comp2])

        # Verify batch matches individual
        assert str(comp1.id) in batch_result
        assert str(comp2.id) in batch_result

        batch_1_plugins = {a.plugin_name for a in batch_result[str(comp1.id)]}
        individual_1_plugins = {a.plugin_name for a in individual_1.passing_assessments}
        assert batch_1_plugins == individual_1_plugins

        batch_2_plugins = {a.plugin_name for a in batch_result[str(comp2.id)]}
        individual_2_plugins = {a.plugin_name for a in individual_2.passing_assessments}
        assert batch_2_plugins == individual_2_plugins

    def test_component_without_sboms_returns_empty_list(self, team):
        """Component with no SBOMs returns empty list of assessments."""
        from sbomify.apps.plugins.public_assessment_utils import get_components_latest_sbom_assessments_batch

        component = Component.objects.create(
            name="Empty Component", team=team, visibility=Component.Visibility.PUBLIC, component_type="sbom"
        )

        result = get_components_latest_sbom_assessments_batch([component])
        assert result[str(component.id)] == []
