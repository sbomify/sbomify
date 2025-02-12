"""Tests for billing views and Stripe integration."""

import json
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from billing.models import BillingPlan
from teams.models import Team

from .fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe,  # Use the new comprehensive mock
    sample_user,
    team_with_business_plan,
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
def test_stripe_webhook_invalid_signature(client: Client):
    """Test webhook endpoint with invalid signature."""
    with patch("stripe.Webhook.construct_event") as mock_construct_event:
        mock_construct_event.side_effect = stripe.error.SignatureVerificationError("Invalid", "sig")

        response = client.post(
            reverse("billing:webhook"),
            data=json.dumps({"type": "checkout.session.completed"}),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="invalid_signature",
        )

        assert response.status_code == 400


@pytest.mark.django_db
def test_stripe_webhook_subscription_success(
    client: Client,
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
):
    """Test successful subscription webhook processing."""
    webhook_data = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": team_with_business_plan.billing_plan_limits["stripe_subscription_id"],
                "object": "subscription",
                "customer": team_with_business_plan.billing_plan_limits["stripe_customer_id"],
                "status": "active",
                "items": {
                    "data": [{
                        "price": business_plan.stripe_price_monthly_id,
                        "plan": {
                            "product": business_plan.stripe_product_id
                        }
                    }]
                },
                "metadata": {
                    "team_key": team_with_business_plan.key
                }
            }
        }
    }

    # Store original plan to verify change
    original_plan = team_with_business_plan.billing_plan
    team_with_business_plan.billing_plan = "community"  # Set to different plan to verify change
    team_with_business_plan.save()

    # Create a valid signature using the test webhook secret
    response = client.post(
        reverse("billing:webhook"),
        data=json.dumps(webhook_data),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="whsec_test_webhook_secret_key",  # Use the same secret we mocked
    )

    assert response.status_code == 200

    # Verify team was updated
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == business_plan.key
    assert team_with_business_plan.billing_plan_limits["stripe_customer_id"] == webhook_data["data"]["object"]["customer"]
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == webhook_data["data"]["object"]["id"]
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"
