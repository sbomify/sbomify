"""Tests for metadata propagation in Stripe billing."""

import pytest
from django.utils import timezone
from unittest.mock import MagicMock, patch

from sbomify.apps.billing.stripe_client import StripeClient, StripeError
from sbomify.apps.teams.models import Team
from sbomify.apps.billing.models import BillingPlan


@pytest.fixture
def mock_stripe_customer():
    """Mock Stripe customer with metadata."""
    customer = MagicMock()
    customer.metadata = {"team_key": "test_team"}
    return customer


@pytest.fixture
def mock_stripe_subscription():
    """Mock Stripe subscription."""
    subscription = MagicMock()
    subscription.id = "sub_123"
    subscription.status = "active"
    subscription.metadata = {}
    return subscription


@pytest.fixture
def mock_stripe():
    """Mock the Stripe module."""
    mock = MagicMock()
    mock.Subscription = MagicMock()
    return mock


@pytest.fixture
def stripe_client(mock_stripe):
    """Create a StripeClient instance with mocked Stripe."""
    client = StripeClient()
    client.stripe = mock_stripe
    return client


@pytest.mark.django_db
class TestMetadataPropagation:
    """Test suite for metadata propagation in Stripe billing."""

    def test_create_subscription_copies_customer_metadata(
        self, stripe_client, mock_stripe_customer, mock_stripe_subscription
    ):
        """Test that customer metadata is copied to subscription."""
        # Setup
        with patch.object(stripe_client, "get_customer", return_value=mock_stripe_customer):
            # Mock the create method to return our subscription
            stripe_client.stripe.Subscription.create.return_value = mock_stripe_subscription

            # Mock the modify method to update metadata on the subscription
            def modify(id, **kwargs):
                if 'metadata' in kwargs:
                    mock_stripe_subscription.metadata = kwargs['metadata']
                return mock_stripe_subscription
            modify_mock = MagicMock(side_effect=modify)
            stripe_client.stripe.Subscription.modify = modify_mock

            # Execute
            subscription = stripe_client.create_subscription(
                customer_id="cus_123",
                price_id="price_123",
            )

            # Verify
            assert subscription.metadata == {"team_key": "test_team"}
            stripe_client.stripe.Subscription.create.assert_called_once()
            modify_mock.assert_called_once_with(
                subscription.id,
                metadata={"team_key": "test_team"},
            )

    def test_create_subscription_with_existing_metadata(
        self, stripe_client, mock_stripe_customer, mock_stripe_subscription
    ):
        """Test that existing subscription metadata is preserved."""
        # Setup
        mock_stripe_subscription.metadata = {"existing_key": "value"}
        with patch.object(stripe_client, "get_customer", return_value=mock_stripe_customer):
            # Mock the create method to return our subscription
            stripe_client.stripe.Subscription.create.return_value = mock_stripe_subscription

            # Mock the modify method to preserve existing metadata
            def modify(id, **kwargs):
                if 'metadata' in kwargs:
                    mock_stripe_subscription.metadata.update(kwargs['metadata'])
                return mock_stripe_subscription
            modify_mock = MagicMock(side_effect=modify)
            stripe_client.stripe.Subscription.modify = modify_mock

            # Execute
            subscription = stripe_client.create_subscription(
                customer_id="cus_123",
                price_id="price_123",
            )

            # Verify
            assert subscription.metadata == {"existing_key": "value", "team_key": "test_team"}
            stripe_client.stripe.Subscription.create.assert_called_once()
            modify_mock.assert_called_once_with(
                subscription.id,
                metadata={"team_key": "test_team"},
            )

    @pytest.mark.django_db
    def test_team_subscription_relationship(self):
        """Test that team and subscription relationship is maintained."""
        # Create test data
        team = Team.objects.create(
            key="test_team",
            name="Test Team",
            billing_plan="business",
            billing_plan_limits={
                "stripe_customer_id": "cus_123",
                "stripe_subscription_id": "sub_123",
                "subscription_status": "active",
                "last_updated": timezone.now().isoformat(),
            },
        )

        # Verify team can be found by subscription ID
        found_team = Team.objects.get(
            billing_plan_limits__stripe_subscription_id="sub_123"
        )
        assert found_team.id == team.id

        # Verify team can be found by customer ID
        found_team = Team.objects.get(
            billing_plan_limits__stripe_customer_id="cus_123"
        )
        assert found_team.id == team.id

    def test_subscription_creation_validation(self, stripe_client, mock_stripe_customer):
        """Test that subscription creation validates required metadata."""
        # Setup
        mock_stripe_customer.metadata = {}  # No team_key in metadata
        with patch.object(stripe_client, "get_customer", return_value=mock_stripe_customer):
            # Execute and verify
            with pytest.raises(StripeError, match="Customer must have team_key in metadata"):
                stripe_client.create_subscription(
                    customer_id="cus_123",
                    price_id="price_123",
                )