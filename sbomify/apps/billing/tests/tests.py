"""Generic billing functionality tests."""
import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest, HttpResponse

from sbomify.apps.billing.billing_processing import check_billing_limits
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.sboms.models import Component, Product, Project, ProductProject, ProjectComponent
from sbomify.apps.teams.models import Team

from .fixtures import (  # noqa: F401
    sample_user,
    community_plan,
    business_plan,
    enterprise_plan,
    test_product,
    multiple_products,
    test_project,
    multiple_projects,
    multiple_components,
)
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401


@pytest.mark.django_db
def test_billing_plan_str_representation(business_plan: BillingPlan):
    """Test string representation of BillingPlan model."""
    assert str(business_plan) == "Business (business)"





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
