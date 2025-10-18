"""Comprehensive tests for StripeClient class."""

from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.conf import settings

from sbomify.apps.billing.stripe_client import StripeClient, StripeError


class TestStripeClient:
    """Test cases for StripeClient."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = StripeClient()

    def test_init_with_default_api_key(self):
        """Test initialization with default API key."""
        client = StripeClient()
        assert client.api_key == settings.STRIPE_SECRET_KEY
        assert client.stripe.api_key == settings.STRIPE_SECRET_KEY

    def test_init_with_custom_api_key(self):
        """Test initialization with custom API key."""
        custom_key = "sk_test_custom"
        client = StripeClient(api_key=custom_key)
        assert client.api_key == custom_key
        assert client.stripe.api_key == custom_key

    # Customer operations tests
    @patch("stripe.Customer.retrieve")
    def test_get_customer_success(self, mock_retrieve):
        """Test successful customer retrieval."""
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_retrieve.return_value = mock_customer

        result = self.client.get_customer("cus_123")

        assert result == mock_customer
        mock_retrieve.assert_called_once_with("cus_123")

    @patch("stripe.Customer.retrieve")
    def test_get_customer_card_error(self, mock_retrieve):
        """Test customer retrieval with card error."""
        mock_retrieve.side_effect = stripe.error.CardError(
            message="Your card was declined", param="card", code="card_declined"
        )

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Card error" in str(exc_info.value)

    @patch("stripe.Customer.retrieve")
    def test_get_customer_rate_limit_error(self, mock_retrieve):
        """Test customer retrieval with rate limit error."""
        mock_retrieve.side_effect = stripe.error.RateLimitError("Too many requests")

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Too many requests made to Stripe API" in str(exc_info.value)

    @patch("stripe.Customer.retrieve")
    def test_get_customer_invalid_request_error(self, mock_retrieve):
        """Test customer retrieval with invalid request error."""
        mock_retrieve.side_effect = stripe.error.InvalidRequestError(message="No such customer", param="id")

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Invalid request" in str(exc_info.value)

    @patch("stripe.Customer.retrieve")
    def test_get_customer_authentication_error(self, mock_retrieve):
        """Test customer retrieval with authentication error."""
        mock_retrieve.side_effect = stripe.error.AuthenticationError("Invalid API key")

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Authentication with Stripe failed" in str(exc_info.value)

    @patch("stripe.Customer.retrieve")
    def test_get_customer_api_connection_error(self, mock_retrieve):
        """Test customer retrieval with API connection error."""
        mock_retrieve.side_effect = stripe.error.APIConnectionError("Network error")

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Could not connect to Stripe API" in str(exc_info.value)

    @patch("stripe.Customer.retrieve")
    def test_get_customer_generic_stripe_error(self, mock_retrieve):
        """Test customer retrieval with generic Stripe error."""
        mock_retrieve.side_effect = stripe.error.StripeError("Generic error")

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Stripe error" in str(exc_info.value)

    @patch("stripe.Customer.retrieve")
    def test_get_customer_unexpected_error(self, mock_retrieve):
        """Test customer retrieval with unexpected error."""
        mock_retrieve.side_effect = ValueError("Unexpected error")

        with pytest.raises(StripeError) as exc_info:
            self.client.get_customer("cus_123")

        assert "Unexpected error" in str(exc_info.value)

    @patch("stripe.Customer.create")
    def test_create_customer_success(self, mock_create):
        """Test successful customer creation."""
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_create.return_value = mock_customer

        result = self.client.create_customer(
            email="test@example.com", name="Test User", metadata={"team_key": "team_123"}
        )

        assert result == mock_customer
        mock_create.assert_called_once_with(
            email="test@example.com", name="Test User", metadata={"team_key": "team_123"}
        )

    @patch("stripe.Customer.create")
    def test_create_customer_no_metadata(self, mock_create):
        """Test customer creation without metadata."""
        mock_customer = MagicMock()
        mock_create.return_value = mock_customer

        self.client.create_customer(email="test@example.com", name="Test User")

        mock_create.assert_called_once_with(email="test@example.com", name="Test User", metadata={})

    @patch("stripe.Customer.modify")
    def test_update_customer_success(self, mock_modify):
        """Test successful customer update."""
        mock_customer = MagicMock()
        mock_modify.return_value = mock_customer

        result = self.client.update_customer("cus_123", email="new@example.com", name="New Name")

        assert result == mock_customer
        mock_modify.assert_called_once_with("cus_123", email="new@example.com", name="New Name")

    # Subscription operations tests
    @patch("stripe.Subscription.create")
    def test_create_subscription_success(self, mock_create):
        """Test successful subscription creation."""
        mock_customer = MagicMock()
        mock_customer.metadata = {"team_key": "team_123"}

        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.metadata = {"team_key": "team_123"}

        with patch.object(self.client, "get_customer", return_value=mock_customer):
            mock_create.return_value = mock_subscription

            result = self.client.create_subscription(customer_id="cus_123", price_id="price_123")

            assert result == mock_subscription
            mock_create.assert_called_once()

    @patch("stripe.Subscription.create")
    def test_create_subscription_with_trial(self, mock_create):
        """Test subscription creation with trial period."""
        mock_customer = MagicMock()
        mock_customer.metadata = {"team_key": "team_123"}

        mock_subscription = MagicMock()
        mock_subscription.metadata = {"team_key": "team_123"}

        with patch.object(self.client, "get_customer", return_value=mock_customer):
            mock_create.return_value = mock_subscription

            self.client.create_subscription(customer_id="cus_123", price_id="price_123", trial_days=14)

            mock_create.assert_called_once()
            call_args = mock_create.call_args[1]
            assert call_args["trial_period_days"] == 14

    def test_create_subscription_no_team_key(self):
        """Test subscription creation with customer missing team_key."""
        mock_customer = MagicMock()
        mock_customer.metadata = {}

        with patch.object(self.client, "get_customer", return_value=mock_customer):
            with pytest.raises(StripeError) as exc_info:
                self.client.create_subscription(customer_id="cus_123", price_id="price_123")

            assert "Customer must have team_key in metadata" in str(exc_info.value)

    @patch("stripe.Subscription.create")
    @patch("stripe.Subscription.modify")
    def test_create_subscription_metadata_fix(self, mock_modify, mock_create):
        """Test subscription creation with metadata fix needed."""
        mock_customer = MagicMock()
        mock_customer.metadata = {"team_key": "team_123"}

        # First subscription creation returns subscription without metadata
        mock_subscription_no_meta = MagicMock()
        mock_subscription_no_meta.metadata = {}
        mock_create.return_value = mock_subscription_no_meta

        # Second modify call returns subscription with metadata
        mock_subscription_with_meta = MagicMock()
        mock_subscription_with_meta.metadata = {"team_key": "team_123"}
        mock_modify.return_value = mock_subscription_with_meta

        with patch.object(self.client, "get_customer", return_value=mock_customer):
            result = self.client.create_subscription(customer_id="cus_123", price_id="price_123")

            assert result == mock_subscription_with_meta
            mock_modify.assert_called_once()

    @patch("stripe.Subscription.modify")
    def test_update_subscription_success(self, mock_modify):
        """Test successful subscription update."""
        mock_subscription = MagicMock()
        mock_modify.return_value = mock_subscription

        result = self.client.update_subscription("sub_123", metadata={"updated": "true"})

        assert result == mock_subscription
        mock_modify.assert_called_once_with("sub_123", metadata={"updated": "true"})

    @patch("stripe.Subscription.delete")
    def test_cancel_subscription_success(self, mock_delete):
        """Test successful subscription cancellation."""
        mock_subscription = MagicMock()
        mock_delete.return_value = mock_subscription

        result = self.client.cancel_subscription("sub_123")

        assert result == mock_subscription
        mock_delete.assert_called_once_with("sub_123", prorate=True)

    @patch("stripe.Subscription.delete")
    def test_cancel_subscription_no_proration(self, mock_delete):
        """Test subscription cancellation without proration."""
        mock_subscription = MagicMock()
        mock_delete.return_value = mock_subscription

        result = self.client.cancel_subscription("sub_123", prorate=False)

        assert result == mock_subscription
        mock_delete.assert_called_once_with("sub_123", prorate=False)

    @patch("stripe.Subscription.retrieve")
    def test_get_subscription_success(self, mock_retrieve):
        """Test successful subscription retrieval."""
        mock_subscription = MagicMock()
        mock_retrieve.return_value = mock_subscription

        result = self.client.get_subscription("sub_123")

        assert result == mock_subscription
        mock_retrieve.assert_called_once_with("sub_123", expand=["latest_invoice.payment_intent"])

    # Checkout session tests
    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_success(self, mock_create):
        """Test successful checkout session creation."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"
        mock_create.return_value = mock_session

        result = self.client.create_checkout_session(
            customer_id="cus_123",
            price_id="price_123",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result == mock_session
        mock_create.assert_called_once_with(
            customer="cus_123",
            payment_method_types=["card"],
            line_items=[{"price": "price_123", "quantity": 1}],
            mode="subscription",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            metadata={},
        )

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_with_metadata(self, mock_create):
        """Test checkout session creation with metadata."""
        mock_session = MagicMock()
        mock_create.return_value = mock_session

        self.client.create_checkout_session(
            customer_id="cus_123",
            price_id="price_123",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            metadata={"team_key": "team_123"},
        )

        call_args = mock_create.call_args[1]
        assert call_args["metadata"] == {"team_key": "team_123"}

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_with_promo_code(self, mock_create):
        """Test checkout session creation with promo code."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"
        mock_create.return_value = mock_session

        result = self.client.create_checkout_session(
            customer_id="cus_123",
            price_id="price_123",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            promo_code="SAVE20",
        )

        assert result == mock_session
        call_args = mock_create.call_args[1]
        assert call_args["discounts"] == [{"coupon": "SAVE20"}]

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_with_promo_code_and_metadata(self, mock_create):
        """Test checkout session creation with both promo code and metadata."""
        mock_session = MagicMock()
        mock_create.return_value = mock_session

        self.client.create_checkout_session(
            customer_id="cus_123",
            price_id="price_123",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            metadata={"team_key": "team_123"},
            promo_code="SAVE20",
        )

        call_args = mock_create.call_args[1]
        assert call_args["metadata"] == {"team_key": "team_123"}
        assert call_args["discounts"] == [{"coupon": "SAVE20"}]

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_without_promo_code(self, mock_create):
        """Test checkout session creation without promo code (existing behavior)."""
        mock_session = MagicMock()
        mock_create.return_value = mock_session

        self.client.create_checkout_session(
            customer_id="cus_123",
            price_id="price_123",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        call_args = mock_create.call_args[1]
        assert "discounts" not in call_args

    @patch("stripe.checkout.Session.retrieve")
    def test_get_checkout_session_success(self, mock_retrieve):
        """Test successful checkout session retrieval."""
        mock_session = MagicMock()
        mock_retrieve.return_value = mock_session

        result = self.client.get_checkout_session("cs_123")

        assert result == mock_session
        mock_retrieve.assert_called_once_with("cs_123")

    # Webhook tests
    @patch("stripe.Webhook.construct_event")
    def test_construct_webhook_event_with_default_secret(self, mock_construct):
        """Test webhook event construction with default secret."""
        payload = b"test_payload"
        sig_header = "test_sig"

        mock_construct.return_value = "test_event"
        result = self.client.construct_webhook_event(payload, sig_header)

        assert result == "test_event"
        mock_construct.assert_called_once_with(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)

    @patch("stripe.Webhook.construct_event")
    def test_construct_webhook_event_with_custom_secret(self, mock_construct):
        """Test webhook event construction with custom secret."""
        payload = b"test_payload"
        sig_header = "test_sig"
        custom_secret = "custom_secret"

        mock_construct.return_value = "test_event"
        result = self.client.construct_webhook_event(payload, sig_header, custom_secret)

        assert result == "test_event"
        mock_construct.assert_called_once_with(payload, sig_header, custom_secret)


class TestStripeError:
    """Test cases for StripeError exception."""

    def test_stripe_error_creation(self):
        """Test StripeError exception creation."""
        error = StripeError("Test error message")
        assert str(error) == "Test error message"

    def test_stripe_error_inheritance(self):
        """Test StripeError inherits from Exception."""
        error = StripeError("Test error")
        assert isinstance(error, Exception)
