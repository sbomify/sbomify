"""Tests for billing processing functionality."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.utils import timezone

from billing import billing_processing
from billing.models import BillingPlan
from teams.models import Member, Team

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    """Create a test team."""
    user = User.objects.create_user(
        username="testuser",
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
            "last_updated": timezone.now().isoformat(),
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


@pytest.fixture
def mock_stripe_subscription():
    """Create a mock Stripe subscription."""
    subscription = MagicMock()
    subscription.id = "sub_test123"
    subscription.status = "trialing"
    subscription.trial_end = int((timezone.now() + datetime.timedelta(days=14)).timestamp())
    subscription.customer = "cus_test123"
    return subscription


def test_handle_subscription_updated_trial(team, mock_stripe_subscription):
    """Test handling subscription update with trial status."""
    billing_processing.handle_subscription_updated(mock_stripe_subscription)

    # Refresh team from database
    team.refresh_from_db()

    # Check trial status
    assert team.billing_plan_limits["is_trial"] is True
    assert team.billing_plan_limits["trial_end"] == mock_stripe_subscription.trial_end
    assert team.billing_plan_limits["subscription_status"] == "trialing"


def test_handle_subscription_updated_trial_ending(team, mock_stripe_subscription):
    """Test handling subscription update when trial is ending soon."""
    # Set trial end to 2 days from now
    mock_stripe_subscription.trial_end = int((timezone.now() + datetime.timedelta(days=2)).timestamp())

    with patch("billing.email_notifications.notify_trial_ending") as mock_notify:
        billing_processing.handle_subscription_updated(mock_stripe_subscription)
        mock_notify.assert_called_once()


def test_handle_subscription_updated_incomplete(team, mock_stripe_subscription):
    """Test handling subscription update with incomplete status."""
    mock_stripe_subscription.status = "incomplete"

    with patch("billing.email_notifications.notify_payment_failed") as mock_notify:
        billing_processing.handle_subscription_updated(mock_stripe_subscription)
        mock_notify.assert_called_once()


def test_handle_checkout_completed_trial(team, business_plan):
    """Test handling checkout completion with trial."""
    session = MagicMock()
    session.payment_status = "paid"
    session.customer = "cus_test123"
    session.subscription = "sub_test123"
    session.metadata = {"team_key": team.key}

    subscription = MagicMock()
    subscription.status = "trialing"
    subscription.trial_end = int((timezone.now() + datetime.timedelta(days=14)).timestamp())

    with patch("stripe.Subscription.retrieve", return_value=subscription):
        billing_processing.handle_checkout_completed(session)

    team.refresh_from_db()
    assert team.billing_plan_limits["is_trial"] is True
    assert team.billing_plan_limits["trial_end"] == subscription.trial_end


def test_handle_stripe_error():
    """Test Stripe error handling decorator."""
    @billing_processing.handle_stripe_error
    def test_func():
        raise stripe.error.CardError("Your card was declined", "card_declined", "decline_code")

    with pytest.raises(billing_processing.StripeError) as exc_info:
        test_func()
    assert "Card error" in str(exc_info.value)


def test_verify_stripe_webhook():
    """Test webhook signature verification."""
    request = MagicMock()
    request.headers = {"Stripe-Signature": "test_sig"}
    request.body = b"test_payload"

    with patch("stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = "test_event"
        result = billing_processing.verify_stripe_webhook(request)
        assert result == "test_event"
        mock_construct.assert_called_once_with(
            request.body,
            request.headers["Stripe-Signature"],
            "test_webhook_secret",
        )


def test_verify_stripe_webhook_invalid():
    """Test webhook signature verification with invalid signature."""
    request = MagicMock()
    request.headers = {"Stripe-Signature": "invalid_sig"}
    request.body = b"test_payload"

    with patch("stripe.Webhook.construct_event", side_effect=stripe.error.SignatureVerificationError):
        result = billing_processing.verify_stripe_webhook(request)
        assert result is False


def test_handle_subscription_updated_error(team, mock_stripe_subscription):
    """Test error handling in subscription update."""
    mock_stripe_subscription.status = "invalid_status"

    with pytest.raises(billing_processing.StripeSubscriptionError):
        billing_processing.handle_subscription_updated(mock_stripe_subscription)


def test_handle_checkout_completed_error(team):
    """Test error handling in checkout completion."""
    session = MagicMock()
    session.payment_status = "paid"
    session.metadata = {"team_key": "invalid_key"}

    with pytest.raises(billing_processing.StripeError):
        billing_processing.handle_checkout_completed(session)