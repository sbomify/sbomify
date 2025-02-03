"""Generic billing functionality tests."""
import pytest
from django.contrib.auth.base_user import AbstractBaseUser

from billing.billing_processing import can_downgrade_to_plan
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