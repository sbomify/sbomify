"""Generic billing functionality tests."""
import pytest
from django.contrib.auth.base_user import AbstractBaseUser

from billing.models import BillingPlan
from billing.views import can_downgrade_to_plan
from sboms.models import Component, Product, Project
from teams.models import Team

from .fixtures import (  # noqa: F401
    sample_user,
    community_plan,
    business_plan,
    enterprise_plan,
    team_with_business_plan,
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
    team_with_business_plan: Team, community_plan: BillingPlan
):
    """Test downgrade prevention when team has more products than plan allows."""
    # Create products exceeding community plan limits
    for i in range(community_plan.max_products + 1):
        Product.objects.create(
            name=f"Test Product {i}",
            team=team_with_business_plan
        )

    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, community_plan)
    assert can_downgrade is False
    assert "products" in message.lower()


@pytest.mark.django_db
def test_cannot_downgrade_with_too_many_projects(
    team_with_business_plan: Team, community_plan: BillingPlan
):
    """Test downgrade prevention when team has more projects than plan allows."""
    product = Product.objects.create(
        name="Test Product",
        team=team_with_business_plan
    )

    # Create projects exceeding community plan limits
    for i in range(community_plan.max_projects + 1):
        Project.objects.create(
            name=f"Test Project {team_with_business_plan.key} {i}",
            product=product
        )

    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, community_plan)
    assert can_downgrade is False
    assert "projects" in message.lower()


@pytest.mark.django_db
def test_cannot_downgrade_with_too_many_components(
    team_with_business_plan: Team, community_plan: BillingPlan
):
    """Test downgrade prevention when team has more components than plan allows."""
    product = Product.objects.create(
        name="Test Product",
        team=team_with_business_plan
    )
    project = Project.objects.create(
        name="Test Project",
        product=product
    )

    # Create components exceeding community plan limits
    for i in range(community_plan.max_components + 1):
        Component.objects.create(
            name=f"Test Component {i}",
            project=project
        )

    can_downgrade, message = can_downgrade_to_plan(team_with_business_plan, community_plan)
    assert can_downgrade is False
    assert "components" in message.lower()