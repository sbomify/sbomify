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
def stripe_client():
    """Create a StripeClient instance."""
    return StripeClient()


@pytest.mark.django_db
class TestMetadataPropagation:
    """Test suite for metadata propagation in Stripe billing."""

    @patch("stripe.Subscription.modify")
    @patch("stripe.Subscription.create")
    def test_create_subscription_copies_customer_metadata(
        self, mock_sub_create, mock_sub_modify, stripe_client, mock_stripe_customer, mock_stripe_subscription
    ):
        """Test that customer metadata is copied to subscription."""
        with patch.object(stripe_client, "get_customer", return_value=mock_stripe_customer):
            mock_sub_create.return_value = mock_stripe_subscription

            def modify(id, **kwargs):
                if 'metadata' in kwargs:
                    mock_stripe_subscription.metadata = kwargs['metadata']
                return mock_stripe_subscription
            mock_sub_modify.side_effect = modify

            subscription = stripe_client.create_subscription(
                customer_id="cus_123",
                price_id="price_123",
            )

            assert subscription.metadata == {"team_key": "test_team"}
            mock_sub_create.assert_called_once()
            mock_sub_modify.assert_called_once_with(
                subscription.id,
                metadata={"team_key": "test_team"},
                api_key=stripe_client._api_key,
            )

    @patch("stripe.Subscription.modify")
    @patch("stripe.Subscription.create")
    def test_create_subscription_with_existing_metadata(
        self, mock_sub_create, mock_sub_modify, stripe_client, mock_stripe_customer, mock_stripe_subscription
    ):
        """Test that existing subscription metadata is preserved."""
        mock_stripe_subscription.metadata = {"existing_key": "value"}
        with patch.object(stripe_client, "get_customer", return_value=mock_stripe_customer):
            mock_sub_create.return_value = mock_stripe_subscription

            def modify(id, **kwargs):
                if 'metadata' in kwargs:
                    mock_stripe_subscription.metadata.update(kwargs['metadata'])
                return mock_stripe_subscription
            mock_sub_modify.side_effect = modify

            subscription = stripe_client.create_subscription(
                customer_id="cus_123",
                price_id="price_123",
            )

            assert subscription.metadata == {"existing_key": "value", "team_key": "test_team"}
            mock_sub_create.assert_called_once()
            mock_sub_modify.assert_called_once_with(
                subscription.id,
                metadata={"team_key": "test_team"},
                api_key=stripe_client._api_key,
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
            with pytest.raises(StripeError, match="An unexpected error occurred."):
                stripe_client.create_subscription(
                    customer_id="cus_123",
                    price_id="price_123",
                )