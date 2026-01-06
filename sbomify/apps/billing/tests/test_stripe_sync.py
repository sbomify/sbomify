"""Tests for Stripe subscription synchronization functionality."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from sbomify.apps.billing.stripe_sync import sync_subscription_from_stripe
from sbomify.apps.billing.stripe_client import StripeError
from sbomify.apps.teams.models import Team

# Import shared fixtures
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    team_with_business_plan,
    sample_user,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def team_with_subscription(team_with_business_plan):
    """Create a team with an active subscription."""
    team = team_with_business_plan
    team.billing_plan_limits = {
        "stripe_subscription_id": "sub_test_123",
        "stripe_customer_id": "cus_test_123",
        "subscription_status": "active",
        "cancel_at_period_end": False,
    }
    team.save()
    return team


@pytest.fixture
def mock_stripe_subscription():
    """Create a mock Stripe subscription."""
    subscription = MagicMock()
    subscription.id = "sub_test_123"
    subscription.status = "active"
    subscription.cancel_at_period_end = False
    subscription.current_period_end = int(
        (timezone.now() + datetime.timedelta(days=30)).timestamp()
    )
    return subscription


class TestSyncSubscriptionBasic:
    """Test basic sync subscription functionality."""

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_no_subscription_id(self, mock_client, mock_cache, team_with_business_plan):
        """Test sync returns False when no subscription ID exists."""
        team = team_with_business_plan
        team.billing_plan_limits = {}
        team.save()

        result = sync_subscription_from_stripe(team)
        assert result is False
        mock_cache.assert_not_called()
        mock_client.get_subscription.assert_not_called()

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_subscription_status_change(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync updates subscription status when it changes."""
        team = team_with_subscription
        # Change status in Stripe
        mock_stripe_subscription.status = "past_due"
        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "past_due"
        assert "last_updated" in team.billing_plan_limits

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_cancel_at_period_end_change(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync updates cancel_at_period_end when it changes."""
        team = team_with_subscription
        # Change cancel_at_period_end in Stripe
        mock_stripe_subscription.cancel_at_period_end = True
        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        team.refresh_from_db()
        assert team.billing_plan_limits["cancel_at_period_end"] is True

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_no_changes(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync returns True when no changes are needed."""
        team = team_with_subscription
        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        # Verify no unnecessary save occurred (status unchanged)
        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "active"


class TestSyncReactivation:
    """Test subscription reactivation (cancellation reversal)."""

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_clears_scheduled_downgrade_on_reactivation(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync clears scheduled_downgrade_plan when user reactivates."""
        team = team_with_subscription
        # Set up scheduled downgrade
        team.billing_plan_limits["cancel_at_period_end"] = True
        team.billing_plan_limits["scheduled_downgrade_plan"] = "community"
        team.save()

        # User reactivated - cancel_at_period_end is now False
        mock_stripe_subscription.cancel_at_period_end = False
        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        team.refresh_from_db()
        assert team.billing_plan_limits["cancel_at_period_end"] is False
        assert "scheduled_downgrade_plan" not in team.billing_plan_limits


class TestSyncNextBillingDate:
    """Test next_billing_date synchronization."""

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_adds_next_billing_date_when_missing(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync adds next_billing_date when it's missing."""
        team = team_with_subscription
        # Remove next_billing_date
        team.billing_plan_limits.pop("next_billing_date", None)
        team.save()

        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        team.refresh_from_db()
        assert "next_billing_date" in team.billing_plan_limits
        # Verify it's a valid ISO format date
        date_str = team.billing_plan_limits["next_billing_date"]
        parsed_date = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        assert parsed_date > timezone.now()

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_keeps_existing_next_billing_date(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync doesn't overwrite existing next_billing_date."""
        team = team_with_subscription
        existing_date = "2025-12-31T00:00:00+00:00"
        team.billing_plan_limits["next_billing_date"] = existing_date
        team.save()

        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        team.refresh_from_db()
        # Should keep existing date if no change needed
        assert team.billing_plan_limits.get("next_billing_date") == existing_date


class TestSyncErrorHandling:
    """Test error handling in sync functionality."""

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_handles_deleted_subscription(
        self, mock_client, mock_cache, team_with_subscription
    ):
        """Test sync handles deleted subscription gracefully."""
        team = team_with_subscription
        # Simulate subscription deleted in Stripe
        mock_cache.return_value = None
        mock_client.get_subscription.side_effect = StripeError("No such subscription")

        result = sync_subscription_from_stripe(team)
        assert result is True  # Should handle gracefully

        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "canceled"
        assert "stripe_subscription_id" not in team.billing_plan_limits
        assert "scheduled_downgrade_plan" not in team.billing_plan_limits
        assert team.billing_plan_limits["cancel_at_period_end"] is False

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_handles_stripe_error(
        self, mock_client, mock_cache, team_with_subscription
    ):
        """Test sync handles Stripe API errors gracefully."""
        team = team_with_subscription
        # Simulate Stripe API error
        mock_cache.return_value = None
        mock_client.get_subscription.side_effect = StripeError("API rate limit exceeded")

        result = sync_subscription_from_stripe(team)
        assert result is False  # Should return False on error

        # Database should remain unchanged
        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "active"

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    def test_sync_handles_unexpected_exception(
        self, mock_cache, team_with_subscription
    ):
        """Test sync handles unexpected exceptions gracefully."""
        team = team_with_subscription
        # Simulate unexpected error
        mock_cache.side_effect = Exception("Unexpected error")

        result = sync_subscription_from_stripe(team)
        assert result is False

        # Database should remain unchanged
        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "active"


class TestSyncCaching:
    """Test caching behavior in sync functionality."""

    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_uses_cache(
        self, mock_client, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync uses cached subscription when available."""
        team = team_with_subscription
        mock_cache.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team)
        assert result is True

        # Should use cache, not call Stripe directly
        mock_cache.assert_called_once()
        mock_client.get_subscription.assert_not_called()

    @patch("sbomify.apps.billing.stripe_sync.invalidate_subscription_cache")
    @patch("sbomify.apps.billing.stripe_sync.get_cached_subscription")
    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_force_refresh(
        self, mock_client, mock_invalidate, mock_cache, team_with_subscription, mock_stripe_subscription
    ):
        """Test sync bypasses cache when force_refresh=True."""
        team = team_with_subscription
        mock_client.get_subscription.return_value = mock_stripe_subscription

        result = sync_subscription_from_stripe(team, force_refresh=True)
        assert result is True

        # Should invalidate cache and fetch fresh
        mock_invalidate.assert_called_once_with("sub_test_123", team.key)
        mock_client.get_subscription.assert_called_once_with("sub_test_123")


class TestSyncIntegration:
    """Test sync integration with views and context processors."""

    @patch("sbomify.apps.core.context_processors.sync_subscription_from_stripe")
    def test_context_processor_calls_sync(self, mock_sync, sample_user, team_with_subscription):
        """Test that context processor calls sync on page load."""
        from sbomify.apps.core.context_processors import team_context
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        request.session = {"current_team": {"key": team_with_subscription.key}}

        # Mock sync to succeed
        mock_sync.return_value = True

        context = team_context(request)
        assert "team" in context
        # Sync should be called
        mock_sync.assert_called_once()

    @patch("sbomify.apps.core.context_processors.sync_subscription_from_stripe")
    def test_context_processor_handles_sync_failure(
        self, mock_sync, sample_user, team_with_subscription
    ):
        """Test that context processor handles sync failure gracefully."""
        from sbomify.apps.core.context_processors import team_context
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        request.session = {"current_team": {"key": team_with_subscription.key}}

        # Mock sync to fail
        mock_sync.side_effect = Exception("Sync failed")

        # Should not crash
        context = team_context(request)
        assert "team" in context  # Should still return team

    @patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe")
    def test_team_settings_calls_sync(
        self, mock_sync, client, sample_user, team_with_subscription
    ):
        """Test that team settings view calls sync before displaying billing info."""
        client.force_login(sample_user)
        mock_sync.return_value = True

        response = client.get(
            f"/teams/{team_with_subscription.key}/settings/?tab=billing"
        )

        assert response.status_code == 200
        # Sync should be called
        mock_sync.assert_called_once()

    @patch("sbomify.apps.billing.views.sync_subscription_from_stripe")
    def test_billing_return_calls_sync(
        self, mock_sync, client, sample_user, team_with_subscription
    ):
        """Test that billing return view calls sync after checkout."""
        from unittest.mock import patch as mock_patch

        client.force_login(sample_user)
        mock_sync.return_value = True

        # Mock checkout session
        with mock_patch("sbomify.apps.billing.views.stripe_client") as mock_client:
            mock_session = MagicMock()
            mock_session.payment_status = "paid"
            mock_session.subscription = "sub_test_123"
            mock_session.customer = "cus_test_123"
            mock_session.metadata = {"team_key": team_with_subscription.key, "plan_key": "business"}
            mock_client.get_checkout_session.return_value = mock_session

            mock_subscription = MagicMock()
            mock_subscription.id = "sub_test_123"
            mock_subscription.status = "active"
            mock_subscription.current_period_end = int(
                (timezone.now() + datetime.timedelta(days=30)).timestamp()
            )
            mock_client.get_subscription.return_value = mock_subscription

            mock_customer = MagicMock()
            mock_customer.id = "cus_test_123"
            mock_client.get_customer.return_value = mock_customer

            response = client.get("/billing/return/?session_id=cs_test_123")

            # Should call sync after processing
            mock_sync.assert_called_once()

