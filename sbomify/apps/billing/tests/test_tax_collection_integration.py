"""Integration tests for tax collection scenarios."""

from unittest.mock import MagicMock, patch
import pytest
import stripe
from django.test import TestCase

from sbomify.apps.billing.stripe_client import StripeClient, StripeError


class TestTaxCollectionIntegration(TestCase):
    """Integration tests for tax collection scenarios."""

    def setUp(self):
        """Set up test environment."""
        self.client = StripeClient()

    @patch("stripe.Customer.create")
    @patch("stripe.Subscription.create")
    def test_trial_signup_without_address_requirement(self, mock_subscription_create, mock_customer_create):
        """Test that trial signups work without requiring billing address."""
        # Mock customer creation (no address required)
        mock_customer = MagicMock()
        mock_customer.id = "cus_trial_123"
        mock_customer.metadata = {"team_key": "team_abc"}
        mock_customer_create.return_value = mock_customer

        # Mock subscription creation for trial (no tax collection)
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_trial_123"
        mock_subscription.metadata = {"team_key": "team_abc"}
        mock_subscription.status = "trialing"
        mock_subscription_create.return_value = mock_subscription

        # Create customer (should not require address)
        customer = self.client.create_customer(
            email="trial@example.com",
            name="Trial User",
            metadata={"team_key": "team_abc"}
        )

        # Create trial subscription (should not require tax collection)
        with patch.object(self.client, 'get_customer', return_value=mock_customer):
            subscription = self.client.create_subscription(
                customer_id=customer.id,
                price_id="price_business_monthly",
                trial_days=14,
                collect_tax=False  # No tax collection for trials
            )

        # Verify customer created without address requirements
        mock_customer_create.assert_called_once_with(
            email="trial@example.com",
            name="Trial User",
            metadata={"team_key": "team_abc"}
        )

        # Verify subscription created without tax collection
        mock_subscription_create.assert_called_once()
        call_args = mock_subscription_create.call_args[1]
        assert call_args["trial_period_days"] == 14
        assert "automatic_tax" not in call_args  # No tax collection for trials

        assert customer.id == "cus_trial_123"
        assert subscription.id == "sub_trial_123"

    @patch("stripe.checkout.Session.create")
    def test_trial_to_paid_conversion_with_tax_collection(self, mock_checkout_create):
        """Test that trial → paid conversion enables tax collection."""
        # Mock checkout session for paid conversion
        mock_session = MagicMock()
        mock_session.id = "cs_conversion_123"
        mock_session.url = "https://checkout.stripe.com/convert"
        mock_checkout_create.return_value = mock_session

        # Create checkout session for trial → paid conversion
        session = self.client.create_checkout_session(
            customer_id="cus_trial_123",
            price_id="price_business_monthly",
            success_url="https://app.example.com/success",
            cancel_url="https://app.example.com/cancel",
            collect_tax=True  # Enable tax collection for paid conversions
        )

        # Verify checkout session enables tax collection
        mock_checkout_create.assert_called_once()
        call_args = mock_checkout_create.call_args[1]
        assert call_args["automatic_tax"] == {"enabled": True}
        assert session.url == "https://checkout.stripe.com/convert"

    @patch("stripe.billing_portal.Session.create")
    def test_customer_portal_access(self, mock_portal_create):
        """Test that existing customers can access billing portal."""
        # Mock portal session creation
        mock_portal_session = MagicMock()
        mock_portal_session.url = "https://billing.stripe.com/portal"
        mock_portal_create.return_value = mock_portal_session

        # Create billing portal session
        portal_session = self.client.create_billing_portal_session(
            customer_id="cus_existing_123",
            return_url="https://app.example.com/dashboard"
        )

        # Verify portal session created correctly
        mock_portal_create.assert_called_once_with(
            customer="cus_existing_123",
            return_url="https://app.example.com/dashboard"
        )
        assert portal_session.url == "https://billing.stripe.com/portal"

    @patch("stripe.Customer.create")
    def test_customer_creation_failure_scenarios(self, mock_customer_create):
        """Test various customer creation failure scenarios."""
        # Test invalid request error (what we're fixing)
        mock_customer_create.side_effect = stripe.error.InvalidRequestError(
            message="Invalid address: Address is required for tax calculation",
            param="address"
        )

        with pytest.raises(StripeError) as exc_info:
            self.client.create_customer(
                email="test@example.com",
                name="Test User",
                metadata={"team_key": "team_123"}
            )

        assert "Invalid request" in str(exc_info.value)
        assert "Address is required" in str(exc_info.value)

    @patch("stripe.Subscription.create")
    def test_subscription_creation_with_tax_scenarios(self, mock_subscription_create):
        """Test subscription creation with different tax scenarios."""
        mock_customer = MagicMock()
        mock_customer.metadata = {"team_key": "team_123"}

        # Test 1: Trial subscription without tax
        mock_trial_subscription = MagicMock()
        mock_trial_subscription.metadata = {"team_key": "team_123"}
        mock_subscription_create.return_value = mock_trial_subscription

        with patch.object(self.client, 'get_customer', return_value=mock_customer):
            trial_sub = self.client.create_subscription(
                customer_id="cus_123",
                price_id="price_business",
                trial_days=14,
                collect_tax=False
            )

        # Verify no tax collection for trial
        call_args = mock_subscription_create.call_args[1]
        assert "automatic_tax" not in call_args
        assert call_args["trial_period_days"] == 14

        # Test 2: Paid subscription with tax
        mock_subscription_create.reset_mock()
        mock_paid_subscription = MagicMock()
        mock_paid_subscription.metadata = {"team_key": "team_123"}
        mock_subscription_create.return_value = mock_paid_subscription

        with patch.object(self.client, 'get_customer', return_value=mock_customer):
            paid_sub = self.client.create_subscription(
                customer_id="cus_123",
                price_id="price_business",
                collect_tax=True
            )

        # Verify tax collection enabled for paid
        call_args = mock_subscription_create.call_args[1]
        assert call_args["automatic_tax"] == {"enabled": True}
        assert "trial_period_days" not in call_args

    def test_stripe_error_handling_comprehensive(self):
        """Test comprehensive Stripe error handling."""
        # Test all major Stripe error types
        error_scenarios = [
            (stripe.error.CardError("Card declined", "card", "card_declined"), "Card error"),
            (stripe.error.RateLimitError("Too many requests"), "Too many requests"),
            (stripe.error.InvalidRequestError("Invalid request", "param"), "Invalid request"),
            (stripe.error.AuthenticationError("Invalid API key"), "Authentication with Stripe failed"),
            (stripe.error.APIConnectionError("Network error"), "Could not connect to Stripe API"),
            (stripe.error.StripeError("Generic error"), "Stripe error"),
            (ValueError("Unexpected error"), "Unexpected error"),
        ]

        for stripe_error, expected_message in error_scenarios:
            with patch("stripe.Customer.retrieve", side_effect=stripe_error):
                with pytest.raises(StripeError) as exc_info:
                    self.client.get_customer("cus_123")
                assert expected_message in str(exc_info.value)


class TestTaxCollectionEdgeCases(TestCase):
    """Test edge cases for tax collection logic."""

    def setUp(self):
        """Set up test environment."""
        self.client = StripeClient()

    @patch("stripe.Subscription.create")
    def test_subscription_metadata_handling(self, mock_create):
        """Test proper metadata handling in subscriptions."""
        # Test customer with missing team_key
        mock_customer_no_key = MagicMock()
        mock_customer_no_key.metadata = {}

        with patch.object(self.client, 'get_customer', return_value=mock_customer_no_key):
            with pytest.raises(StripeError) as exc_info:
                self.client.create_subscription(
                    customer_id="cus_123",
                    price_id="price_123"
                )
            assert "Customer must have team_key in metadata" in str(exc_info.value)

        # Test metadata merging
        mock_customer_with_key = MagicMock()
        mock_customer_with_key.metadata = {"team_key": "team_from_customer"}
        mock_subscription = MagicMock()
        mock_subscription.metadata = {"team_key": "team_from_customer", "plan_key": "business"}
        mock_create.return_value = mock_subscription

        with patch.object(self.client, 'get_customer', return_value=mock_customer_with_key):
            result = self.client.create_subscription(
                customer_id="cus_123",
                price_id="price_123",
                metadata={"plan_key": "business"}
            )

        # Verify metadata was properly merged
        call_args = mock_create.call_args[1]
        expected_metadata = {"team_key": "team_from_customer", "plan_key": "business"}
        assert call_args["metadata"] == expected_metadata

    @patch("stripe.billing_portal.Session.create")
    def test_billing_portal_error_scenarios(self, mock_create):
        """Test billing portal error scenarios."""
        # Test various portal creation errors
        error_scenarios = [
            stripe.error.InvalidRequestError("Customer not found", "customer"),
            stripe.error.AuthenticationError("Invalid API key"),
            stripe.error.StripeError("Service unavailable"),
        ]

        for error in error_scenarios:
            mock_create.side_effect = error
            with pytest.raises(StripeError):
                self.client.create_billing_portal_session(
                    customer_id="cus_invalid",
                    return_url="https://example.com/dashboard"
                )
