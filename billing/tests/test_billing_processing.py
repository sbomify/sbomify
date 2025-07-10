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

from billing import billing_processing
from billing.models import BillingPlan
from core.tests.shared_fixtures import team_with_business_plan, sample_user
from teams.models import Member, Team
from sboms.models import Product, Project, Component
from sbomify.logging import getLogger
from ..stripe_client import StripeClient, StripeError
from core.utils import number_to_random_token

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
    subscription.items.data = [
        MagicMock(
            price=MagicMock(
                product="prod_123",
                metadata={"plan_key": "business"}
            )
        )
    ]
    subscription.metadata = {"plan_key": "business"}
    return subscription


@pytest.fixture
def mock_stripe_checkout_session(team_with_business_plan):
    """Create a mock Stripe checkout session for testing."""
    session = MagicMock()
    session.id = "cs_123"
    session.customer = "cus_test123"  # Match the team's customer ID
    session.subscription = "sub_test123"  # Match the team's subscription ID
    session.payment_status = "paid"
    session.metadata = {
        "team_key": team_with_business_plan.key,  # Use the actual team key
        "plan_key": "business"
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
    return invoice


@pytest.fixture
def mock_stripe_client():
    """Create a mock Stripe client for testing."""
    with patch('billing.billing_processing.stripe_client') as mock_client:
        mock_client.get_subscription.return_value = MagicMock(
            id="sub_test123",
            status="active",
            trial_end=None,
            items=MagicMock(
                data=[
                    MagicMock(
                        price=MagicMock(
                            product="prod_123",
                            metadata={"plan_key": "business"}
                        )
                    )
                ]
            ),
            metadata={"plan_key": "business"}
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
        }
    )
    return plan


class TestBillingProcessing:
    """Test cases for billing processing functionality."""

    @pytest.fixture(autouse=True)
    def setup(self, team_with_business_plan, business_plan, mock_stripe_subscription, mock_stripe_checkout_session, mock_stripe_invoice, mock_stripe_client):
        """Set up test environment."""
        self.team = team_with_business_plan
        self.plan = business_plan
        self.subscription = mock_stripe_subscription
        self.session = mock_stripe_checkout_session
        self.invoice = mock_stripe_invoice
        self.stripe_client = mock_stripe_client

    @patch("billing.billing_processing.email_notifications")
    def test_handle_subscription_updated_trial(self, mock_email):
        """Test handling subscription update with trial status."""
        self.subscription.status = "trialing"
        # Set trial end to be within notification period
        self.subscription.trial_end = int((timezone.now() + datetime.timedelta(days=settings.TRIAL_ENDING_NOTIFICATION_DAYS)).timestamp())

        billing_processing.handle_subscription_updated(self.subscription)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "trialing"
        assert self.team.billing_plan_limits["is_trial"] is True
        assert self.team.billing_plan_limits["trial_end"] == self.subscription.trial_end
        mock_email.notify_trial_ending.assert_called_once()

    @patch("billing.billing_processing.email_notifications")
    def test_handle_subscription_updated_trial_expired(self, mock_email):
        """Test handling subscription update with expired trial."""
        self.subscription.status = "trialing"
        self.subscription.trial_end = int((timezone.now() - datetime.timedelta(days=1)).timestamp())

        billing_processing.handle_subscription_updated(self.subscription)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "canceled"
        assert self.team.billing_plan_limits["is_trial"] is False
        mock_email.notify_trial_expired.assert_called_once()

    @patch("billing.billing_processing.email_notifications")
    def test_handle_checkout_completed_trial(self, mock_email):
        """Test handling checkout completion with trial period."""
        self.subscription.status = "trialing"
        # Set trial end to be within notification period
        self.subscription.trial_end = int((timezone.now() + datetime.timedelta(days=settings.TRIAL_ENDING_NOTIFICATION_DAYS)).timestamp())
        self.stripe_client.get_subscription.return_value = self.subscription

        billing_processing.handle_checkout_completed(self.session)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "trialing"
        assert self.team.billing_plan_limits["is_trial"] is True
        assert self.team.billing_plan_limits["trial_end"] == self.subscription.trial_end
        mock_email.notify_trial_ending.assert_called_once()

    @patch("billing.billing_processing.email_notifications")
    def test_handle_payment_succeeded(self, mock_email):
        """Test handling successful payment."""
        billing_processing.handle_payment_succeeded(self.invoice)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "active"
        mock_email.notify_payment_succeeded.assert_called_once()

    @patch("billing.billing_processing.email_notifications")
    def test_handle_payment_failed(self, mock_email):
        """Test handling failed payment."""
        billing_processing.handle_payment_failed(self.invoice)

        self.team.refresh_from_db()
        assert self.team.billing_plan_limits["subscription_status"] == "past_due"
        mock_email.notify_payment_failed.assert_called_once()

    def test_can_downgrade_to_plan(self):
        """Test checking if team can downgrade to a plan."""
        # Create some test data exceeding limits
        for i in range(15):  # More than max_products (10)
            Product.objects.create(team=self.team, name=f"Product {i}")

        for i in range(25):  # More than max_projects (20)
            Project.objects.create(team=self.team, name=f"Project {i}")

        for i in range(150):  # More than max_components (100)
            Component.objects.create(team=self.team, name=f"Component {i}")

        # Test with no limits
        plan = BillingPlan.objects.create(
            key="enterprise",
            name="Enterprise",
            stripe_price_monthly_id="price_456"
        )
        can_downgrade, message = billing_processing.can_downgrade_to_plan(self.team, plan)
        assert can_downgrade is True
        assert message == ""

        # Test with limits exceeded
        plan = BillingPlan.objects.create(
            key="starter",
            name="Starter",
            stripe_price_monthly_id="price_789",
            max_products=1,
            max_projects=1,
            max_components=1
        )
        can_downgrade, message = billing_processing.can_downgrade_to_plan(self.team, plan)
        assert can_downgrade is False
        assert "Current usage exceeds plan limits" in message

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

    def test_handle_missing_plan(self):
        """Test handling missing billing plan."""
        self.plan.delete()
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
        request.body,
        request.headers["Stripe-Signature"],
        settings.STRIPE_WEBHOOK_SECRET
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

    billing_processing.handle_payment_succeeded(invoice)

    # Refresh team from database
    team_with_business_plan.refresh_from_db()

    # Check subscription status
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"


def test_can_downgrade_to_plan_within_limits(team_with_business_plan, business_plan):
    """Test downgrade check when usage is within plan limits."""
    # Create some test data within limits
    for i in range(5):  # Less than max_products (10)
        Product.objects.create(team=team_with_business_plan, name=f"Product {i}")

    for i in range(10):  # Less than max_projects (20)
        Project.objects.create(team=team_with_business_plan, name=f"Project {i}")

    for i in range(50):  # Less than max_components (100)
        Component.objects.create(team=team_with_business_plan, name=f"Component {i}")

    can_downgrade, message = billing_processing.can_downgrade_to_plan(team_with_business_plan, business_plan)
    assert can_downgrade is True
    assert message == ""


def test_can_downgrade_to_plan_exceeds_limits(team_with_business_plan, business_plan):
    """Test downgrade check when usage exceeds plan limits."""
    # Create test data exceeding limits
    for i in range(15):  # More than max_products (10)
        Product.objects.create(team=team_with_business_plan, name=f"Product {i}")

    for i in range(25):  # More than max_projects (20)
        Project.objects.create(team=team_with_business_plan, name=f"Project {i}")

    for i in range(150):  # More than max_components (100)
        Component.objects.create(team=team_with_business_plan, name=f"Component {i}")

    can_downgrade, message = billing_processing.can_downgrade_to_plan(team_with_business_plan, business_plan)
    assert can_downgrade is False
    assert "Current usage exceeds plan limits" in message


def test_can_downgrade_to_plan_no_limits(team_with_business_plan):
    """Test downgrade check for plan with no limits."""
    # Create enterprise plan with no limits
    enterprise_plan = BillingPlan.objects.create(
        key="enterprise",
        name="Enterprise",
        max_products=None,
        max_projects=None,
        max_components=None,
    )

    # Create test data exceeding normal limits
    for i in range(100):
        Product.objects.create(team=team_with_business_plan, name=f"Product {i}")
        Project.objects.create(team=team_with_business_plan, name=f"Project {i}")
        Component.objects.create(team=team_with_business_plan, name=f"Component {i}")

    can_downgrade, message = billing_processing.can_downgrade_to_plan(team_with_business_plan, enterprise_plan)
    assert can_downgrade is True
    assert message == ""


@override_settings(BILLING=False)
def test_billing_disabled_bypass():
    """Test that billing checks are bypassed when billing is disabled."""
    # Create a test team with no billing plan
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        billing_plan=None,
        billing_plan_limits={}
    )

    # Create a test user and member
    user = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123"
    )
    Member.objects.create(
        team=team,
        user=user,
        role="owner"
    )

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
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        billing_plan=None,
        billing_plan_limits={}
    )

    # Get current limits (should be unlimited when billing is disabled)
    limits = billing_processing.get_current_limits(team)

    # With billing disabled, all limits should be None (unlimited)
    assert limits.get("max_products") is None
    assert limits.get("max_projects") is None
    assert limits.get("max_components") is None


@override_settings(BILLING=True)
def test_billing_enabled_checks():
    """Test that billing checks are enforced when billing is enabled."""
    # Create a billing plan first
    business_plan = BillingPlan.objects.create(
        key="business",
        name="Business",
        max_products=1,
        max_projects=1,
        max_components=1,
    )

    # Create a team with a billing plan
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        billing_plan="business",
        billing_plan_limits={
            "max_products": business_plan.max_products,
            "max_projects": business_plan.max_projects,
            "max_components": business_plan.max_components,
        }
    )

    # Create a test user and member
    user = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123"
    )
    Member.objects.create(
        team=team,
        user=user,
        role="owner"
    )

    # Create a test request
    request = MagicMock()
    request.method = "POST"
    request.session = {"current_team": {"key": "test-team"}}

    # Create a test view function
    @billing_processing.check_billing_limits("product")
    def test_view(request):
        return "success"

    # Test that the view is called normally with no existing products
    result = test_view(request)
    assert result == "success"

    # Now create a product to exceed the limit
    Product.objects.create(team=team, name="Test Product")

    # Test that the view returns a billing error when limit is exceeded
    result = test_view(request)
    assert isinstance(result, HttpResponseForbidden)