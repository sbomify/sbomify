"""Tests for billing API endpoints."""

import json
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.urls import reverse

from billing.models import BillingPlan
from teams.models import Member, Team

from .fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe_checkout_session,
    mock_stripe_customer,
    mock_stripe_subscription,
    sample_user,
    team_with_business_plan,
)


@pytest.fixture
def mock_stripe_customer(monkeypatch):
    """Mock Stripe customer for testing."""

    class MockCustomer:
        @classmethod
        def retrieve(cls, id, **kwargs):
            if id.startswith("c_test"):
                instance = cls()
                instance.id = id
                return instance
            raise stripe.error.InvalidRequestError("Customer not found", param="customer")

    monkeypatch.setattr(stripe.Customer, "retrieve", MockCustomer.retrieve)
    return MockCustomer


@pytest.fixture
def mock_stripe_subscription(monkeypatch):
    """Mock Stripe subscription for testing."""

    class MockSubscription:
        @classmethod
        def list(cls, customer, limit=1):
            class SubscriptionList:
                data = []

            return SubscriptionList()

        @classmethod
        def modify(cls, subscription_id, **kwargs):
            pass

    monkeypatch.setattr(stripe.Subscription, "list", MockSubscription.list)
    monkeypatch.setattr(stripe.Subscription, "modify", MockSubscription.modify)
    return MockSubscription


@pytest.mark.django_db
def test_get_plans_unauthenticated(client: Client):
    """Test that unauthenticated users cannot access plans endpoint."""
    response = client.get(reverse("api-1:get_plans"))
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_plans(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
    enterprise_plan: BillingPlan,  # noqa: F811
):
    """Test retrieving all available billing plans."""
    client.force_login(sample_user)
    response = client.get(reverse("api-1:get_plans"))

    assert response.status_code == 200
    data = json.loads(response.content)

    assert len(data) == 3
    plan_keys = {plan["key"] for plan in data}
    assert plan_keys == {"community", "business", "enterprise"}


@pytest.mark.django_db
def test_get_usage_no_team(client: Client, sample_user: AbstractBaseUser):  # noqa: F811
    """Test usage endpoint without team selection."""
    client.force_login(sample_user)

    # Ensure session is empty
    session = client.session
    session["current_team"] = {}
    session.save()

    response = client.get(reverse("api-1:get_usage"))

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "detail" in data
    assert data["detail"] == "No team selected"


@pytest.mark.django_db
def test_get_usage(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
):
    """Test retrieving team's usage statistics."""
    client.force_login(sample_user)

    # Create some test data
    product = team_with_business_plan.product_set.create(name="Test Product")
    project = product.project_set.create(
        name="Test Project",
        team=team_with_business_plan,  # Add the team reference
    )
    project.component_set.create(
        name="Test Component",
        team=team_with_business_plan,  # Add the team reference
    )

    response = client.get(f"{reverse('api-1:get_usage')}?team_key={team_with_business_plan.key}")

    assert response.status_code == 200
    data = json.loads(response.content)

    assert data["products"] == 1
    assert data["projects"] == 1
    assert data["components"] == 1


@pytest.mark.django_db
def test_change_plan_unauthorized_user(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
):
    """Test that non-team-owners cannot change plans."""
    # Add guest user as a regular member (not owner) of the team
    Member.objects.create(
        user=guest_user,
        team=team_with_business_plan,
        role="member",  # Make sure this matches the role choices in settings
    )

    client.force_login(guest_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Only team owners can change billing plans" in data["detail"]


@pytest.mark.django_db
def test_change_plan_to_community(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811,
    mock_stripe_customer,
    mock_stripe_subscription,
):
    """Test downgrading to community plan."""
    client.force_login(sample_user)

    # Update team key to one that won't have a Stripe customer
    team_with_business_plan.key = "no-stripe-customer"
    team_with_business_plan.save()

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "redirect_url" in data

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == community_plan.key
    assert "max_products" in team_with_business_plan.billing_plan_limits
    assert "max_projects" in team_with_business_plan.billing_plan_limits
    assert "max_components" in team_with_business_plan.billing_plan_limits


@pytest.mark.django_db
def test_change_plan_no_team_selected(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
):
    """Test changing plan without selecting a team."""
    client.force_login(sample_user)

    # Explicitly clear the session data
    session = client.session
    session["current_team"] = {}
    session.save()

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "No team selected" in data["detail"]


@pytest.mark.django_db
def test_change_plan_invalid_plan(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
):
    """Test changing to a non-existent plan."""
    client.force_login(sample_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": "non_existent_plan", "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert "Invalid plan" in data["detail"]


@pytest.mark.django_db
def test_change_plan_to_business_monthly(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811,
    mock_stripe_checkout_session,  # noqa: F811
    mock_stripe_customer,  # noqa: F811
):
    """Test upgrading to business plan with monthly billing."""
    client.force_login(sample_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": business_plan.key, "billing_period": "monthly"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["redirect_url"] == "https://checkout.stripe.com/test"

    # Fix: Access the stored create arguments using the class variable
    assert mock_stripe_checkout_session.create_kwargs["line_items"][0]["price"] == business_plan.stripe_price_monthly_id


@pytest.mark.django_db
def test_change_plan_to_business_annual(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811,
    mock_stripe_checkout_session,  # noqa: F811
    mock_stripe_customer,  # noqa: F811
):
    """Test upgrading to business plan with annual billing."""
    client.force_login(sample_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": business_plan.key, "billing_period": "annual"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["redirect_url"] == "https://checkout.stripe.com/test"

    # Fix: Access the stored create arguments using the class variable
    assert mock_stripe_checkout_session.create_kwargs["line_items"][0]["price"] == business_plan.stripe_price_annual_id


@pytest.mark.django_db
def test_change_plan_to_community_with_active_subscription(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811,
    mock_stripe_customer,  # noqa: F811
    mock_stripe_subscription,  # noqa: F811
):
    """Test downgrading to community plan with an active subscription."""
    client.force_login(sample_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "redirect_url" in data

    # Verify team was updated
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == community_plan.key
