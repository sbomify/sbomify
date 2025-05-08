"""Tests for billing views and Stripe integration."""

import json
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from billing.models import BillingPlan
from teams.models import Member, Team, User

from .fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe,  # Use the new comprehensive mock
    sample_user,
    team_with_business_plan,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    """Create a test client."""
    return Client()


@pytest.fixture
def factory():
    """Create a request factory."""
    return RequestFactory()


@pytest.fixture
def team(db):
    """Create a test team."""
    user = User.objects.create_user(
        email="test@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
    )
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        billing_plan="business",
        billing_plan_limits={
            "max_products": 10,
            "max_projects": 20,
            "max_components": 100,
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
            "subscription_status": "active",
            "last_updated": "2024-01-01T00:00:00Z",
        },
    )
    Member.objects.create(
        team=team,
        user=user,
        role="owner",
    )
    return team


@pytest.fixture
def business_plan(db):
    """Create a business plan."""
    return BillingPlan.objects.create(
        key="business",
        name="Business",
        max_products=10,
        max_projects=20,
        max_components=100,
        stripe_price_monthly_id="price_monthly",
        stripe_price_annual_id="price_annual",
    )


@pytest.mark.django_db
def test_select_plan_requires_login(client: Client, team_with_business_plan: Team):  # noqa: F811
    """Test that plan selection page requires authentication."""
    response = client.get(reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}))
    assert response.status_code == 302
    assert response.url.startswith(settings.LOGIN_URL)


@pytest.mark.django_db
def test_select_plan_requires_team_owner(client: Client, guest_user: AbstractBaseUser, team_with_business_plan: Team):  # noqa: F811
    """Test that only team owners can access plan selection."""
    client.force_login(guest_user)
    response = client.get(reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}))
    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")


@pytest.mark.django_db
def test_select_plan_page(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
):
    """Test plan selection page display."""
    client.force_login(sample_user)
    response = client.get(reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}))

    assert response.status_code == 200


@pytest.mark.django_db
def test_select_community_plan(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
):
    """Test switching to community plan."""
    client.force_login(sample_user)
    response = client.post(
        reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}), {"plan": community_plan.key}
    )

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")

    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1
    assert "successfully switched" in str(messages[0]).lower()

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == community_plan.key


@pytest.mark.django_db
def test_select_business_plan(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
):
    """Test initiating business plan subscription."""
    client.force_login(sample_user)

    # First request to select_plan endpoint
    response = client.post(
        reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}),
        {"plan": business_plan.key, "billing_period": "monthly"},
    )

    # Should redirect to billing_redirect
    assert response.status_code == 302
    assert response.url == reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key})

    # Follow the redirect to billing_redirect endpoint
    response = client.get(response.url)

    # Should redirect to Stripe checkout
    assert response.status_code == 302
    assert "checkout.stripe.com/test" in response.url


@pytest.mark.django_db
def test_stripe_webhook_invalid_signature(factory):
    """Test webhook with invalid signature."""
    request = factory.post(
        reverse("billing:stripe_webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "invalid_sig"}

    with patch("billing.billing_processing.verify_stripe_webhook", return_value=False):
        response = billing_processing.stripe_webhook(request)
        assert response.status_code == 403


@pytest.mark.django_db
def test_stripe_webhook_checkout_completed(factory, team):
    """Test webhook for checkout completed event."""
    event_data = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test123",
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "payment_status": "paid",
                "metadata": {"team_key": team.key},
            }
        },
    }

    request = factory.post(
        reverse("billing:stripe_webhook"),
        data=json.dumps(event_data),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = MagicMock(type=event_data["type"], data=event_data["data"])
        with patch("billing.billing_processing.handle_checkout_completed") as mock_handler:
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 200
            mock_handler.assert_called_once()


@pytest.mark.django_db
def test_stripe_webhook_subscription_updated(factory, team):
    """Test webhook for subscription updated event."""
    event_data = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test123",
                "status": "trialing",
                "trial_end": 1234567890,
                "customer": "cus_test123",
            }
        },
    }

    request = factory.post(
        reverse("billing:stripe_webhook"),
        data=json.dumps(event_data),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = MagicMock(type=event_data["type"], data=event_data["data"])
        with patch("billing.billing_processing.handle_subscription_updated") as mock_handler:
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 200
            mock_handler.assert_called_once()


@pytest.mark.django_db
def test_stripe_webhook_payment_failed(factory, team):
    """Test webhook for payment failed event."""
    event_data = {
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_test123",
                "subscription": "sub_test123",
                "customer": "cus_test123",
            }
        },
    }

    request = factory.post(
        reverse("billing:stripe_webhook"),
        data=json.dumps(event_data),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = MagicMock(type=event_data["type"], data=event_data["data"])
        with patch("billing.billing_processing.handle_payment_failed") as mock_handler:
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 200
            mock_handler.assert_called_once()


@pytest.mark.django_db
def test_stripe_webhook_error_handling(factory):
    """Test webhook error handling."""
    request = factory.post(
        reverse("billing:stripe_webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = MagicMock(type="test.event", data={})
        with patch("billing.billing_processing.handle_checkout_completed", side_effect=Exception("Test error")):
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 500


@pytest.mark.django_db
def test_billing_redirect_trial(client, team, business_plan):
    """Test billing redirect with trial period."""
    client.force_login(team.members.first().user)

    # Set up session data
    session = client.session
    session["selected_plan"] = {
        "key": "business",
        "billing_period": "monthly",
        "limits": {
            "max_products": 10,
            "max_projects": 20,
            "max_components": 100,
        },
    }
    session.save()

    with patch("stripe.checkout.Session.create") as mock_create:
        mock_create.return_value = MagicMock(url="https://stripe.com/checkout")
        response = client.get(reverse("billing:billing_redirect", kwargs={"team_key": team.key}))
        assert response.status_code == 302
        assert response.url == "https://stripe.com/checkout"

        # Verify session creation parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]
        assert call_args["mode"] == "subscription"
        assert call_args["metadata"]["team_key"] == team.key
