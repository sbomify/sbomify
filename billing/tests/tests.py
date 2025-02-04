"""Generic billing functionality tests."""
import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest, HttpResponse

from billing.billing_processing import can_downgrade_to_plan, check_billing_limits
from billing.models import BillingPlan
from sboms.models import Component, Product, Project, ProductProject, ProjectComponent
from teams.models import Team

from .fixtures import (  # noqa: F401
    sample_user,
    community_plan,
    business_plan,
    enterprise_plan,
    team_with_business_plan,
    test_product,
    multiple_products,
    test_project,
    multiple_projects,
    multiple_components,
)


@pytest.mark.django_db
def test_billing_plan_str_representation(business_plan: BillingPlan):
    """Test string representation of BillingPlan model."""
    assert str(business_plan) == "Business (business)"


@pytest.mark.django_db
def test_can_downgrade_to_enterprise_plan(
    team_with_business_plan: Team, enterprise_plan: BillingPlan
):
    """
    Test that any team can upgrade to enterprise plan.

    Enterprise plan is not a downgrade but it is good the have this test.
    """
    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, enterprise_plan)
    assert can_downgrade is True
    assert message == ""


@pytest.mark.django_db
def test_cannot_downgrade_with_too_many_products(
    team_with_business_plan: Team,
    community_plan: BillingPlan,
    multiple_products: list[Product]
):
    """Test downgrade prevention when team has more products than plan allows."""
    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, community_plan)
    assert can_downgrade is False
    assert "products" in message.lower()


@pytest.mark.django_db
def test_cannot_downgrade_with_too_many_projects(
    team_with_business_plan: Team,
    community_plan: BillingPlan,
    multiple_projects: list[Project]
):
    """Test downgrade prevention when team has more projects than plan allows."""
    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, community_plan)
    assert can_downgrade is False
    assert "projects" in message.lower()


@pytest.mark.django_db
def test_cannot_downgrade_with_too_many_components(
    team_with_business_plan: Team,
    community_plan: BillingPlan,
    multiple_components: list[Component]
):
    """Test downgrade prevention when team has more components than plan allows."""
    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, community_plan)
    assert can_downgrade is False
    assert "components" in message.lower()


@pytest.mark.django_db
def test_product_creation_within_limit(team_with_business_plan: Team, business_plan: BillingPlan):
    """Test product creation within plan limits."""
    team_with_business_plan.billing_plan = business_plan.key
    team_with_business_plan.save()

    # Mock request with team session
    request = HttpRequest()
    request.method = "POST"
    request.session = {"current_team": {"key": team_with_business_plan.key}}

    @check_billing_limits("product")
    def dummy_view(request):
        return HttpResponse("Success", status=200)

    response = dummy_view(request)
    assert response.status_code == 200
    assert response.content == b"Success"


@pytest.mark.django_db
def test_product_creation_over_limit(team_with_business_plan: Team, community_plan: BillingPlan):
    """Test product creation exceeding community plan limits."""
    team_with_business_plan.billing_plan = community_plan.key
    team_with_business_plan.save()

    # Create max allowed products
    for i in range(community_plan.max_products):
        Product.objects.create(team=team_with_business_plan, name=f"Product {i}")

    # Mock request
    request = HttpRequest()
    request.method = "POST"
    request.session = {"current_team": {"key": team_with_business_plan.key}}

    @check_billing_limits("product")
    def dummy_view(request):
        return HttpResponse("Success")

    response = dummy_view(request)
    assert response.status_code == 403
    assert "maximum 1 products" in response.content.decode()


@pytest.mark.django_db
def test_component_creation_enterprise_unlimited(team_with_business_plan: Team, enterprise_plan: BillingPlan):
    """Test unlimited component creation with enterprise plan."""
    team_with_business_plan.billing_plan = enterprise_plan.key
    team_with_business_plan.save()

    # Create 1000 components
    for i in range(1000):
        Component.objects.create(team=team_with_business_plan, name=f"Component {i}")

    request = HttpRequest()
    request.method = "POST"
    request.session = {"current_team": {"key": team_with_business_plan.key}}

    @check_billing_limits("component")
    def dummy_view(request):
        return HttpResponse("Success", status=200)

    response = dummy_view(request)
    assert response.status_code == 200
    assert response.content == b"Success"


@pytest.mark.django_db
def test_project_creation_no_plan(team_with_business_plan: Team):
    """Test project creation with no billing plan."""
    team_with_business_plan.billing_plan = None
    team_with_business_plan.save()

    request = HttpRequest()
    request.method = "POST"
    request.session = {"current_team": {"key": team_with_business_plan.key}}

    @check_billing_limits("project")
    def dummy_view(request):
        return HttpResponse("Success")

    response = dummy_view(request)
    assert response.status_code == 403
    assert "No active billing plan" in response.content.decode()
