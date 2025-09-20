"""Tests for billing views and Stripe integration."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.billing import billing_processing
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Team

from .fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe,  # Use the new comprehensive mock
)

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    """Create a test client."""
    return Client()


@pytest.fixture
def factory():
    """Create a request factory."""
    return RequestFactory()


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
    # Verify URL starts with expected Stripe checkout domain for security
    from urllib.parse import urlparse
    parsed_url = urlparse(response.url)
    assert parsed_url.netloc == "checkout.stripe.com"


@pytest.mark.django_db
def test_stripe_webhook_invalid_signature(factory):
    """Test webhook with invalid signature."""
    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "invalid_sig"}

    with patch("sbomify.apps.billing.billing_processing.verify_stripe_webhook", return_value=False):
        response = billing_processing.stripe_webhook(request)
        assert response.status_code == 403


@pytest.mark.django_db
def test_stripe_webhook_checkout_completed(factory, team_with_business_plan):
    """Test webhook for checkout completed event."""
    event_data = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test123",
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "payment_status": "paid",
                "metadata": {"team_key": team_with_business_plan.key},
            }
        },
    }

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps(event_data),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    mock_event = MagicMock()
    mock_event.type = event_data["type"]
    mock_event.data.object = event_data["data"]["object"]

    with patch("sbomify.apps.billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_checkout_completed"):
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 200


@pytest.mark.django_db
def test_stripe_webhook_subscription_updated(factory, team_with_business_plan):
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
        reverse("billing:webhook"),
        data=json.dumps(event_data),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    mock_event = MagicMock()
    mock_event.type = event_data["type"]
    mock_event.data.object = event_data["data"]["object"]

    with patch("sbomify.apps.billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_subscription_updated"):
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 200


@pytest.mark.django_db
def test_stripe_webhook_payment_failed(factory, team_with_business_plan):
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
        reverse("billing:webhook"),
        data=json.dumps(event_data),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    mock_event = MagicMock()
    mock_event.type = event_data["type"]
    mock_event.data.object = event_data["data"]["object"]

    with patch("sbomify.apps.billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_payment_failed"):
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 200


@pytest.mark.django_db
def test_stripe_webhook_error_handling(factory):
    """Test webhook error handling."""
    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    mock_event = MagicMock()
    mock_event.type = "checkout.session.completed"
    mock_event.data.object = {}

    with patch("sbomify.apps.billing.billing_processing.verify_stripe_webhook") as mock_verify:
        mock_verify.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_checkout_completed", side_effect=Exception("Test error")):
            response = billing_processing.stripe_webhook(request)
            assert response.status_code == 500


@pytest.mark.django_db
def test_billing_redirect_trial(client, team_with_business_plan):
    """Test billing redirect with trial period."""
    member = team_with_business_plan.member_set.first()
    client.force_login(member.user)

    with patch("stripe.checkout.Session.create") as mock_create:
        mock_create.return_value = MagicMock(url="https://checkout.stripe.com/test")
        response = client.get(reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key}))

        assert response.status_code == 302
        assert response.url == reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key})
