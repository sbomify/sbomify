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
    messages = list(get_messages(response.wsgi_request))
    assert "only workspace owners" in str(messages[0]).lower()


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
def test_select_community_plan_immediate(
    client: Client,
    sample_user: AbstractBaseUser,
    team_with_business_plan: Team,
    community_plan: BillingPlan,
):
    """Test switching to community plan when no active subscription exists (immediate)."""
    # clear subscription id to simulate no active sub
    team_with_business_plan.billing_plan_limits["stripe_subscription_id"] = None
    team_with_business_plan.save()
    
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
def test_select_community_plan_with_subscription_redirects_to_portal(
    client: Client,
    sample_user: AbstractBaseUser,
    team_with_business_plan: Team,
    community_plan: BillingPlan,
):
    """Test selecting community plan with active subscription redirects to Portal (cancel flow)."""
    # Ensure has sub id and active status
    team_with_business_plan.billing_plan_limits["stripe_subscription_id"] = "sub_test_123"
    team_with_business_plan.billing_plan_limits["subscription_status"] = "active"
    team_with_business_plan.save()

    client.force_login(sample_user)
    
    # Mock create_billing_portal_session on the CLASS
    with patch("sbomify.apps.billing.stripe_client.StripeClient.create_billing_portal_session") as mock_create_portal:
        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/p/session/test_portal_123"
        mock_create_portal.return_value = mock_session

        response = client.post(
            reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}), 
            {"plan": community_plan.key}
        )

        assert response.status_code == 302
        # Verify redirect to create_portal_session
        assert "/billing/portal/" in response.url
        assert "subscription_cancel" in response.url
        
        # Follow the redirect manually
        response = client.get(response.url)
        
        assert response.status_code == 302
        assert response.url == "https://billing.stripe.com/p/session/test_portal_123"

        # Verify called with subscription_cancel flow
        mock_create_portal.assert_called_once()
        args, kwargs = mock_create_portal.call_args
        assert kwargs["flow_data"]["type"] == "subscription_cancel"
        assert kwargs["flow_data"]["subscription_cancel"]["subscription"] == "sub_test_123"


@pytest.mark.django_db
def test_select_business_plan_new_checkout(
    client: Client,
    sample_user: AbstractBaseUser,
    team_with_business_plan: Team,
    business_plan: BillingPlan,
):
    """Test initiating business plan subscription (new)."""
    # Simulate being on community so we need checkout
    team_with_business_plan.billing_plan = "community"
    team_with_business_plan.billing_plan_limits["stripe_subscription_id"] = None
    team_with_business_plan.save()
    
    client.force_login(sample_user)

    # Mock the checkout session creation
    with patch("sbomify.apps.billing.views.pricing_service.create_checkout_session") as mock_create_session:
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test-session"
        mock_create_session.return_value = mock_session

        # Request to select_plan endpoint
        response = client.post(
            reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}),
            {"plan": business_plan.key, "billing_period": "monthly"},
        )

        # Should redirect directly to Stripe
        assert response.status_code == 302
        assert response.url == "https://checkout.stripe.com/test-session"
        
        # Verify the service was called correctly
        mock_create_session.assert_called_once()


@pytest.mark.django_db
def test_switch_business_plan_with_subscription_redirects_to_portal(
    client: Client,
    sample_user: AbstractBaseUser,
    team_with_business_plan: Team,
    business_plan: BillingPlan,
):
    """Test switching business plan period with active subscription redirects to Portal (update flow)."""
    # Simulate already on business with sub
    team_with_business_plan.billing_plan_limits["stripe_subscription_id"] = "sub_test_456"
    team_with_business_plan.billing_plan_limits["subscription_status"] = "active"
    team_with_business_plan.save()
    
    client.force_login(sample_user)
    
    # Expect create_billing_portal_session to be called instead of checkout
    with patch("sbomify.apps.billing.stripe_client.StripeClient.create_billing_portal_session") as mock_create_portal:
        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/p/session/test_portal_456"
        mock_create_portal.return_value = mock_session
        
        # Switch to annual
        response = client.post(
             reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}),
             {"plan": business_plan.key, "billing_period": "annual"},
        )
        
        assert response.status_code == 302
        # Verify redirect to create_portal_session
        assert "/billing/portal/" in response.url
        assert "subscription_update" in response.url
        
        # Follow manually
        response = client.get(response.url)
        
        assert response.status_code == 302
        assert response.url == "https://billing.stripe.com/p/session/test_portal_456"
        
        mock_create_portal.assert_called_once()
        args, kwargs = mock_create_portal.call_args
        assert kwargs["flow_data"]["type"] == "subscription_update"
        assert kwargs["flow_data"]["subscription_update"]["subscription"] == "sub_test_456"


@pytest.mark.django_db
def test_stripe_webhook_missing_signature(factory):
    """Test webhook with missing signature returns 403."""
    from sbomify.apps.billing.views import StripeWebhookView

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {}

    response = StripeWebhookView.as_view()(request)
    assert response.status_code == 403


@pytest.mark.django_db
def test_stripe_webhook_invalid_signature(factory):
    """Test webhook with invalid signature returns 403."""
    from sbomify.apps.billing.views import StripeWebhookView
    from sbomify.apps.billing.stripe_client import StripeError

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "invalid_sig"}

    with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe_client:
        mock_stripe_client.construct_webhook_event.side_effect = StripeError("Invalid signature")
        response = StripeWebhookView.as_view()(request)
        assert response.status_code == 403


@pytest.mark.django_db
def test_stripe_webhook_checkout_completed(factory, team_with_business_plan):
    """Test webhook for checkout completed event."""
    from sbomify.apps.billing.views import StripeWebhookView

    mock_event = MagicMock()
    mock_event.type = "checkout.session.completed"
    mock_event.data.object = {
        "id": "cs_test123",
        "customer": "cus_test123",
        "subscription": "sub_test123",
        "payment_status": "paid",
        "metadata": {"team_key": team_with_business_plan.key},
    }

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "checkout.session.completed"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe_client:
        mock_stripe_client.construct_webhook_event.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_checkout_completed"):
            response = StripeWebhookView.as_view()(request)
            assert response.status_code == 200


@pytest.mark.django_db
def test_stripe_webhook_subscription_updated(factory, team_with_business_plan):
    """Test webhook for subscription updated event passes event to handler."""
    from sbomify.apps.billing.views import StripeWebhookView

    mock_event = MagicMock()
    mock_event.type = "customer.subscription.updated"
    mock_event.id = "evt_test12345"
    mock_event.data.object = {
        "id": "sub_test123",
        "status": "trialing",
        "trial_end": 1234567890,
        "customer": "cus_test123",
    }

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "customer.subscription.updated"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe_client:
        mock_stripe_client.construct_webhook_event.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_subscription_updated") as mock_handler:
            response = StripeWebhookView.as_view()(request)
            assert response.status_code == 200
            mock_handler.assert_called_once()
            call_args = mock_handler.call_args
            assert call_args.kwargs.get("event") == mock_event


@pytest.mark.django_db
def test_stripe_webhook_payment_failed(factory, team_with_business_plan):
    """Test webhook for payment failed event."""
    from sbomify.apps.billing.views import StripeWebhookView

    mock_event = MagicMock()
    mock_event.type = "invoice.payment_failed"
    mock_event.data.object = {
        "id": "in_test123",
        "subscription": "sub_test123",
        "customer": "cus_test123",
    }

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "invoice.payment_failed"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe_client:
        mock_stripe_client.construct_webhook_event.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_payment_failed"):
            response = StripeWebhookView.as_view()(request)
            assert response.status_code == 200


@pytest.mark.django_db
def test_stripe_webhook_error_handling(factory):
    """Test webhook error handling when handler raises unexpected error returns 500."""
    from sbomify.apps.billing.views import StripeWebhookView

    mock_event = MagicMock()
    mock_event.type = "checkout.session.completed"
    mock_event.data.object = {}

    request = factory.post(
        reverse("billing:webhook"),
        data=json.dumps({"type": "test.event"}),
        content_type="application/json",
    )
    request.headers = {"Stripe-Signature": "test_sig"}

    with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe_client:
        mock_stripe_client.construct_webhook_event.return_value = mock_event
        with patch("sbomify.apps.billing.billing_processing.handle_checkout_completed", side_effect=Exception("Test error")):
            response = StripeWebhookView.as_view()(request)
            assert response.status_code == 500



