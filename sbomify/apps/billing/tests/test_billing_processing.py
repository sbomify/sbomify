"""Tests for billing processing functionality."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
from django.test import TestCase, override_settings
from django.http import HttpResponseForbidden

from sbomify.apps.billing import billing_processing
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan, sample_user
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.sboms.models import Product, Project, Component
from sbomify.logging import getLogger
from ..stripe_client import StripeClient, StripeError
from sbomify.apps.core.utils import number_to_random_token

User = get_user_model()
pytestmark = pytest.mark.django_db

logger = getLogger(__name__)


@pytest.fixture
def mock_stripe_subscription():
    """Create a mock Stripe subscription for testing."""
    subscription = MagicMock()
    subscription.id = "sub_test123"  # Match the team's subscription ID
    subscription.status = "active"
    subscription.customer = "cus_test123"  # Match the team's customer ID
    subscription.trial_end = None
    subscription.items.data = [MagicMock(price=MagicMock(product="prod_123", metadata={"plan_key": "business"}))]
    subscription.metadata = {"plan_key": "business"}
    subscription.cancel_at_period_end = False
    return subscription


@pytest.fixture
def mock_stripe_checkout_session(team_with_business_plan):
    """Create a mock Stripe checkout session for testing."""
    session = MagicMock()
    session.id = "cs_123"
    session.customer = "cus_test123"  # Match the team's customer ID
    session.subscription = "sub_test123"  # Match the team's subscription ID
    session.payment_status = "paid"
    session.amount_total = 1000  # $10.00
    session.currency = "usd"
    session.metadata = {
        "team_key": team_with_business_plan.key,  # Use the actual team key
        "plan_key": "business",
    }
    return session


@pytest.fixture
def mock_stripe_invoice():
    """Create a mock Stripe invoice for testing."""
    invoice = MagicMock()
    invoice.id = "in_123"
    invoice.subscription = "sub_test123"  # Match the team's subscription ID
    invoice.customer = "cus_test123"  # Match the team's customer ID
    invoice.status = "paid"
    invoice.amount_paid = 1000
    invoice.currency = "usd"
    return invoice


@pytest.fixture
def mock_stripe_client():
    """Create a mock Stripe client for testing."""
    with patch("sbomify.apps.billing.billing_processing.stripe_client") as mock_client:
        mock_client.get_subscription.return_value = MagicMock(
            id="sub_test123",
            status="active",
            trial_end=None,
            items=MagicMock(data=[MagicMock(price=MagicMock(product="prod_123", metadata={"plan_key": "business"}))]),
            metadata={"plan_key": "business"},
        )
        yield mock_client


@pytest.fixture
def business_plan(db):
    """Create a business plan."""
    plan, _ = BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business",
            "max_products": 10,
            "max_projects": 20,
            "max_components": 100,
            "stripe_price_monthly_id": "price_monthly",
            "stripe_price_annual_id": "price_annual",
        },
    )
    return plan


class TestBillingProcessing:
    """Test cases for billing processing functionality."""

    @pytest.fixture(autouse=True)
    def setup(
        self,
        team_with_business_plan,
        business_plan,
        mock_stripe_subscription,
        mock_stripe_checkout_session,
        mock_stripe_invoice,
        mock_stripe_client,
    ):
        """Set up test environment."""
        self.team = team_with_business_plan
        self.plan = business_plan
        self.subscription = mock_stripe_subscription
        self.session = mock_stripe_checkout_session
        self.invoice = mock_stripe_invoice
        self.stripe_client = mock_stripe_client

    @patch("sbomify.apps.billing.billing_processing.email_notifications")
    def test_handle_subscription_updated_trial(self, mock_email):
        """Test handling subscription update with trial status."""
        self.subscription.status = "trialing"
        # Set trial end to be within notification period
        self.subscription.trial_end = int(
            (timezone.now() + datetime.timedelta(days=settings.TRIAL_ENDING_NOTIFICATION_DAYS)).timestamp()
        )

        billing_processing.handle_subscription_updated(self.subscription)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "trialing"
        assert self.team.billing_plan_limits["is_trial"] is True
        assert self.team.billing_plan_limits["trial_end"] == self.subscription.trial_end
        mock_email.notify_trial_ending.assert_called_once()

    @patch("sbomify.apps.billing.billing_processing.email_notifications")
    def test_handle_subscription_updated_trial_expired(self, mock_email):
        """Test handling subscription update with expired trial."""
        self.subscription.status = "trialing"
        self.subscription.trial_end = int((timezone.now() - datetime.timedelta(days=1)).timestamp())

        billing_processing.handle_subscription_updated(self.subscription)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "canceled"
        assert self.team.billing_plan_limits["is_trial"] is False
        mock_email.notify_trial_expired.assert_called_once()

    @patch("sbomify.apps.billing.billing_processing.email_notifications")
    def test_handle_checkout_completed_trial(self, mock_email):
        """Test handling checkout completion with trial period."""
        self.subscription.status = "trialing"
        # Set trial end to be within notification period
        self.subscription.trial_end = int(
            (timezone.now() + datetime.timedelta(days=settings.TRIAL_ENDING_NOTIFICATION_DAYS)).timestamp()
        )
        self.stripe_client.get_subscription.return_value = self.subscription

        billing_processing.handle_checkout_completed(self.session)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "trialing"
        assert self.team.billing_plan_limits["is_trial"] is True
        assert self.team.billing_plan_limits["trial_end"] == self.subscription.trial_end
        mock_email.notify_trial_ending.assert_called_once()

    @patch("sbomify.apps.billing.billing_processing.email_notifications")
    def test_handle_checkout_completed_cancels_old_subscription(self, mock_email):
        """Test that old subscription is cancelled when a new one is created via checkout."""
        # Setup: Team has an EXISTING subscription
        old_sub_id = "sub_old_999"
        self.team.billing_plan_limits["stripe_subscription_id"] = old_sub_id
        self.team.save()

        # Webhook brings a NEW subscription
        new_sub_id = "sub_new_111"
        self.session.subscription = new_sub_id
        
        # Mock Stripe client to return valid new subscription
        mock_new_sub = MagicMock(
            id=new_sub_id, 
            status="active", 
            trial_end=None,
            items=MagicMock(data=[MagicMock(price=MagicMock(product="prod_123", metadata={"plan_key": "business"}))]),
            metadata={"plan_key": "business"}
        )
        self.stripe_client.get_subscription.return_value = mock_new_sub

        # Call the handler
        billing_processing.handle_checkout_completed(self.session)

        # Verify old subscription was cancelled
        self.stripe_client.cancel_subscription.assert_called_once_with(old_sub_id)
        
        # Verify team updated with new subscription
        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["stripe_subscription_id"] == new_sub_id
        assert self.team.billing_plan_limits["subscription_status"] == "active"


    @patch("sbomify.apps.billing.billing_processing.email_notifications")
    def test_handle_payment_succeeded(self, mock_email):
        """Test handling successful payment."""
        billing_processing.handle_payment_succeeded(self.invoice)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "active"
        mock_email.notify_payment_succeeded.assert_called_once()

    @patch("sbomify.apps.billing.billing_processing.email_notifications")
    def test_handle_payment_failed(self, mock_email):
        """Test handling failed payment."""
        billing_processing.handle_payment_failed(self.invoice)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "past_due"
        mock_email.notify_payment_failed.assert_called_once()



    def test_handle_subscription_deleted(self):
        """Test handling subscription deletion."""
        billing_processing.handle_subscription_deleted(self.subscription)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "canceled"

    def test_handle_invalid_subscription_status(self):
        """Test handling invalid subscription status."""
        self.subscription.status = "invalid_status"
        with pytest.raises(StripeError):
            billing_processing.handle_subscription_updated(self.subscription)

    def test_handle_missing_team(self):
        """Test handling missing team."""
        self.team.delete()
        with pytest.raises(StripeError):
            billing_processing.handle_subscription_updated(self.subscription)




def test_handle_stripe_error():
    """Test Stripe error handling decorator."""

    # Create a proper exception that inherits from BaseException
    class TestCardError(Exception):
        def __init__(self, message):
            self.user_message = message
            super().__init__(message)

    mock_error = TestCardError("Your card was declined")

    @billing_processing._handle_stripe_error
    def test_func():
        raise mock_error

    with pytest.raises(StripeError) as exc_info:
        test_func()
    assert "Unexpected error" in str(exc_info.value)


@patch("stripe.Webhook.construct_event")
def test_verify_stripe_webhook(mock_construct):
    """Test webhook signature verification."""
    request = MagicMock()
    request.headers = {"Stripe-Signature": "test_sig"}
    request.body = b"test_payload"

    mock_construct.return_value = "test_event"
    result = billing_processing.verify_stripe_webhook(request)
    assert result == "test_event"
    mock_construct.assert_called_once_with(
        request.body, request.headers["Stripe-Signature"], settings.STRIPE_WEBHOOK_SECRET
    )


@patch("stripe.Webhook.construct_event")
def test_verify_stripe_webhook_invalid(mock_construct):
    """Test webhook signature verification with invalid signature."""
    request = MagicMock()
    request.headers = {"Stripe-Signature": "invalid_sig"}
    request.body = b"test_payload"

    mock_construct.side_effect = stripe.error.SignatureVerificationError("", "")
    result = billing_processing.verify_stripe_webhook(request)
    assert result is False


def test_handle_subscription_updated_error(team_with_business_plan, mock_stripe_subscription):
    """Test error handling in subscription update."""
    mock_stripe_subscription.status = "invalid_status"
    mock_stripe_subscription.items.data = []
    mock_stripe_subscription.id = "sub_test123"
    mock_stripe_subscription.customer = "cus_test123"

    with pytest.raises(StripeError) as excinfo:
        billing_processing.handle_subscription_updated(mock_stripe_subscription)
    assert "Invalid subscription status: invalid_status" in str(excinfo.value)


def test_handle_checkout_completed_error(team_with_business_plan):
    """Test error handling in checkout completion."""
    session = MagicMock()
    session.payment_status = "paid"
    session.metadata = {"team_key": "invalid_key"}

    with pytest.raises(StripeError):
        billing_processing.handle_checkout_completed(session)


def test_handle_payment_succeeded(team_with_business_plan, mock_stripe_subscription):
    """Test handling successful payment."""
    invoice = MagicMock()
    invoice.subscription = "sub_test123"
    invoice.customer = "cus_test123"
    invoice.amount_paid = 1000
    invoice.currency = "usd"

    billing_processing.handle_payment_succeeded(invoice)

    # Refresh team from database
    team_with_business_plan.refresh_from_db()

    # Check subscription status
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"





@override_settings(BILLING=False)
def test_billing_disabled_bypass():
    """Test that billing checks are bypassed when billing is disabled."""
    # Create a test team with no billing plan
    team = Team.objects.create(name="Test Team", key="test-team", billing_plan=None, billing_plan_limits={})

    # Create a test user and member
    user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    Member.objects.create(team=team, user=user, role="owner")

    # Create a test request
    request = MagicMock()
    request.method = "POST"
    request.session = {"current_team": {"key": "test-team"}}

    # Create a test view function
    @billing_processing.check_billing_limits("product")
    def test_view(request):
        return "success"

    # Test that the view is called without any billing checks
    result = test_view(request)
    assert result == "success"


@override_settings(BILLING=False)
def test_billing_disabled_unlimited_limits():
    """Test that billing disabled returns unlimited limits."""
    # Create a team
    team = Team.objects.create(name="Test Team", key="test-team", billing_plan=None, billing_plan_limits={})

    # Get current limits (should be unlimited when billing is disabled)
    limits = billing_processing.get_current_limits(team)

    # With billing disabled, all limits should be None (unlimited)
    assert limits.get("max_products") is None
    assert limits.get("max_projects") is None
    assert limits.get("max_components") is None


@override_settings(BILLING=True)
def test_billing_enabled_checks():
    """Test that billing checks are enforced when billing is enabled."""
    # Create a billing plan with realistic limits (matching original test)
    business_plan = BillingPlan.objects.create(
        key="business",
        name="Business",
        max_products=5,
        max_projects=10,
        max_components=50,
        stripe_price_monthly_id="price_business_monthly",
        stripe_price_annual_id="price_business_annual",
    )

    # Create a team with the billing plan
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        billing_plan="business",
        billing_plan_limits={
            "max_products": business_plan.max_products,
            "max_projects": business_plan.max_projects,
            "max_components": business_plan.max_components,
            "subscription_status": "active",
        },
    )

    # Create a test user and member
    user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    Member.objects.create(team=team, user=user, role="owner")

    # Create a test request
    request = MagicMock()
    request.method = "POST"
    request.session = {"current_team": {"key": "test-team"}}

    # Create a test view function decorated with billing limits
    @billing_processing.check_billing_limits("product")
    def test_view(request):
        return "success"

    # Test 1: View should work when under the limit
    for i in range(4):  # Create 4 products (under limit of 5)
        Product.objects.create(team=team, name=f"Product {i}")

    result = test_view(request)
    assert result == "success"

    # Test 2: Create products exceeding the limit (original test logic)
    for i in range(4, 7):  # Create 3 more products (total 7, exceeds limit of 5)
        Product.objects.create(team=team, name=f"Product {i}")

    # Test that the view is blocked by billing checks
    result = test_view(request)
    assert isinstance(result, HttpResponseForbidden)
    assert result.content.decode() == "You have reached the maximum 5 products allowed by your plan"


@override_settings(BILLING=True)
def test_payment_failure_grace_period():
    """Test grace period logic for payment failures."""
    # Create test plan
    BillingPlan.objects.create(key="business", name="Business", max_products=10)
    
    # Create team with past_due status
    team = Team.objects.create(
        name="Test Team", 
        key="test-team-grace", 
        billing_plan="business",
        billing_plan_limits={"subscription_status": "past_due"}
    )
    
    # Setup user/member
    user = User.objects.create_user(username="grace_user", email="grace@example.com")
    Member.objects.create(team=team, user=user, role="owner")
    
    # Setup request
    request = MagicMock()
    request.method = "POST"
    request.session = {"current_team": {"key": "test-team-grace"}}
    request.headers = {}
    request.META = {}

    @billing_processing.check_billing_limits("product")
    def test_view(request):
        return "success"

    # 1. Test: Within Grace Period (1 day ago failure)
    team.billing_plan_limits["payment_failed_at"] = (timezone.now() - datetime.timedelta(days=1)).isoformat()
    team.save()
    
    result = test_view(request)
    assert result == "success"

    # 2. Test: Grace Period Expired (4 days ago failure)
    team.billing_plan_limits["payment_failed_at"] = (timezone.now() - datetime.timedelta(days=4)).isoformat()
    team.save()
    
    result = test_view(request)
    assert isinstance(result, HttpResponseForbidden)
    assert "Grace period expired" in result.content.decode()

    # 3. Test: Test handle_payment_failed sets the timestamp
    # Reset team
    team.billing_plan_limits = {"subscription_status": "active"}
    team.save()
    
    invoice = MagicMock()
    invoice.subscription = "sub_test_grace"
    invoice.id = "in_grace_123"
    
    # We need to link team to this subscription AND customer locally to satisfy constraint
    team.billing_plan_limits["stripe_subscription_id"] = "sub_test_grace"
    team.billing_plan_limits["stripe_customer_id"] = "cus_test_grace"
    team.save()
    
    with patch("sbomify.apps.billing.billing_processing.email_notifications"):
        billing_processing.handle_payment_failed(invoice)
    
    team.refresh_from_db()
    assert team.billing_plan_limits["subscription_status"] == "past_due"
    assert "payment_failed_at" in team.billing_plan_limits
    # Verify timestamp is recent
    failed_at = datetime.datetime.fromisoformat(team.billing_plan_limits["payment_failed_at"])
    assert (timezone.now() - failed_at).total_seconds() < 10


@patch("sbomify.apps.billing.billing_processing.stripe_client")
@patch("sbomify.apps.billing.billing_processing.email_notifications")
def test_handle_subscription_updated_cancel_at_period_end(
    mock_email, mock_client, team_with_business_plan, mock_stripe_subscription, business_plan
):
    """Test that cancel_at_period_end is correctly saved when subscription is updated."""
    mock_stripe_subscription.cancel_at_period_end = True
    mock_stripe_subscription.current_period_end = int(
        (timezone.now() + datetime.timedelta(days=30)).timestamp()
    )
    # Patch items.data to return a price that matches our plan
    mock_stripe_subscription.items.data = [
        MagicMock(price=MagicMock(id="price_monthly"))
    ]

    billing_processing.handle_subscription_updated(mock_stripe_subscription)

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits.get("cancel_at_period_end") is True
    assert "next_billing_date" in team_with_business_plan.billing_plan_limits


@patch("sbomify.apps.billing.billing_processing.stripe_client")
@patch("sbomify.apps.billing.billing_processing.email_notifications")
@patch("sbomify.apps.billing.billing_processing.invalidate_subscription_cache")
def test_handle_subscription_updated_with_mock_and_no_event(
    mock_invalidate, mock_email, mock_client, team_with_business_plan, business_plan
):
    """Test that handle_subscription_updated works when subscription is a MagicMock and event is None.
    
    This tests the fix for the bug where accessing subscription.updated on a mock object would fail.
    Note: The implementation handles both dict and object-like subscriptions via getattr/get.
    """
    # Create subscription as MagicMock (simulating Stripe webhook object)
    # Use MagicMock for items.data to match how the code accesses it
    subscription_dict = MagicMock()
    subscription_dict.id = "sub_test123"
    subscription_dict.status = "active"
    subscription_dict.customer = "cus_test123"
    subscription_dict.updated = 1234567890  # Unix timestamp
    subscription_dict.cancel_at_period_end = False
    subscription_dict.cancel_at = None
    subscription_dict.metadata = {"plan_key": "business"}
    subscription_dict.items.data = [
        MagicMock(price=MagicMock(id="price_monthly"))
    ]
    # Make it behave like a dict for getattr checks
    subscription_dict.get = lambda key, default=None: getattr(subscription_dict, key, default)
    subscription_dict.__getitem__ = lambda key: getattr(subscription_dict, key)
    
    # Call without event parameter (simulating the bug in views.py)
    # This should not raise an AttributeError
    billing_processing.handle_subscription_updated(subscription_dict, event=None)
    
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits.get("subscription_status") == "active"
    assert team_with_business_plan.billing_plan_limits.get("stripe_subscription_id") == "sub_test123"


@patch("sbomify.apps.billing.billing_processing.stripe_client")
@patch("sbomify.apps.billing.billing_processing.email_notifications")
@patch("sbomify.apps.billing.billing_processing.invalidate_subscription_cache")
def test_handle_subscription_updated_with_mock_no_updated_field(
    mock_invalidate, mock_email, mock_client, team_with_business_plan, business_plan
):
    """Test that handle_subscription_updated works when subscription MagicMock lacks 'updated' field.
    
    This tests the fallback to using current timestamp when 'updated' is missing.
    """
    # Create subscription as MagicMock without 'updated' attribute
    subscription_dict = MagicMock()
    subscription_dict.id = "sub_test123"
    subscription_dict.status = "active"
    subscription_dict.customer = "cus_test123"
    subscription_dict.cancel_at_period_end = False
    subscription_dict.cancel_at = None
    subscription_dict.metadata = {"plan_key": "business"}
    subscription_dict.items.data = [
        MagicMock(price=MagicMock(id="price_monthly"))
    ]
    # Remove updated attribute to test fallback
    del subscription_dict.updated
    subscription_dict.get = lambda key, default=None: getattr(subscription_dict, key, default) if hasattr(subscription_dict, key) else default
    
    # Call without event parameter - should use timestamp fallback
    billing_processing.handle_subscription_updated(subscription_dict, event=None)
    
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits.get("subscription_status") == "active"
    # Should have a webhook_id generated with timestamp
    assert "last_processed_webhook_id" in team_with_business_plan.billing_plan_limits


@patch("sbomify.apps.billing.billing_processing.stripe_client")
@patch("sbomify.apps.billing.billing_processing.email_notifications")
@patch("sbomify.apps.billing.billing_processing.invalidate_subscription_cache")
def test_handle_subscription_updated_with_event_id(
    mock_invalidate, mock_email, mock_client, team_with_business_plan, business_plan
):
    """Test that handle_subscription_updated uses event.id when event is provided."""
    subscription_dict = MagicMock()
    subscription_dict.id = "sub_test123"
    subscription_dict.status = "active"
    subscription_dict.customer = "cus_test123"
    subscription_dict.cancel_at_period_end = False
    subscription_dict.cancel_at = None
    subscription_dict.metadata = {"plan_key": "business"}
    subscription_dict.items.data = [
        MagicMock(price=MagicMock(id="price_monthly"))
    ]
    
    # Create mock event with id
    mock_event = MagicMock()
    mock_event.id = "evt_test12345"
    
    billing_processing.handle_subscription_updated(subscription_dict, event=mock_event)
    
    team_with_business_plan.refresh_from_db()
    # Should use event.id for webhook_id instead of subscription.updated
    assert team_with_business_plan.billing_plan_limits.get("last_processed_webhook_id") == "evt_test12345"


