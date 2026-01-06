"""
Tests for the sync_stripe_subscriptions management command.
"""

from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from sbomify.apps.billing.stripe_client import StripeError
from sbomify.apps.teams.models import Team


@pytest.fixture
def team_with_active_subscription(db, django_user_model):
    """Create a team with an active subscription."""
    user = django_user_model.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )
    team = Team.objects.create(
        name="Test Team",
        billing_plan="business",
        billing_plan_limits={
            "stripe_subscription_id": "sub_active123",
            "stripe_customer_id": "cus_test123",
            "subscription_status": "active",
            "is_trial": False,
            "max_products": 5,
            "max_projects": 10,
            "max_components": 200,
        },
    )
    team.add_member(user, role="owner")
    return team


@pytest.fixture
def team_with_stale_trial(db, django_user_model):
    """Create a team with a stale trial (trial ended but status not updated)."""
    user = django_user_model.objects.create_user(
        username="trialuser",
        email="trial@example.com",
        password="testpass123",
    )
    # Trial ended a week ago
    trial_end = int((timezone.now() - timedelta(days=7)).timestamp())
    team = Team.objects.create(
        name="Stale Trial Team",
        billing_plan="business",
        billing_plan_limits={
            "stripe_subscription_id": "sub_stale123",
            "stripe_customer_id": "cus_trial123",
            "subscription_status": "trialing",
            "is_trial": True,
            "trial_end": trial_end,
            "max_products": 5,
            "max_projects": 10,
            "max_components": 200,
        },
    )
    team.add_member(user, role="owner")
    return team


@pytest.fixture
def mock_stripe_client():
    """Mock the StripeClient."""
    with patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient") as mock:
        yield mock.return_value


class TestSyncStripeSubscriptions:
    """Test cases for sync_stripe_subscriptions command."""

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    def test_billing_disabled_exits_early(self, mock_billing_enabled):
        """Test that command exits early when billing is disabled."""
        mock_billing_enabled.return_value = False

        out = StringIO()
        call_command("sync_stripe_subscriptions", stdout=out)

        assert "Billing is not enabled" in out.getvalue()

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_no_teams_to_sync(self, mock_stripe_client_class, mock_billing_enabled, db):
        """Test command with no teams having subscriptions."""
        mock_billing_enabled.return_value = True

        out = StringIO()
        call_command("sync_stripe_subscriptions", stdout=out)

        assert "No teams to sync" in out.getvalue()

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_team_already_in_sync(self, mock_stripe_client_class, mock_billing_enabled, team_with_active_subscription):
        """Test that teams already in sync are not updated."""
        mock_billing_enabled.return_value = True

        # Mock Stripe returning same status as local
        mock_subscription = MagicMock()
        mock_subscription.status = "active"
        mock_subscription.trial_end = None
        mock_stripe_client_class.return_value.get_subscription.return_value = mock_subscription

        out = StringIO()
        call_command("sync_stripe_subscriptions", "--verbose", stdout=out)

        assert "Already in sync" in out.getvalue()

        # Verify team was not updated
        team_with_active_subscription.refresh_from_db()
        assert team_with_active_subscription.billing_plan_limits["subscription_status"] == "active"

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_sync_stale_trial_to_canceled(self, mock_stripe_client_class, mock_billing_enabled, team_with_stale_trial):
        """Test syncing a stale trial that was canceled in Stripe."""
        mock_billing_enabled.return_value = True

        # Mock Stripe returning canceled status
        mock_subscription = MagicMock()
        mock_subscription.status = "canceled"
        mock_subscription.trial_end = team_with_stale_trial.billing_plan_limits["trial_end"]
        mock_stripe_client_class.return_value.get_subscription.return_value = mock_subscription

        out = StringIO()
        call_command("sync_stripe_subscriptions", stdout=out)

        # Verify team was updated
        team_with_stale_trial.refresh_from_db()
        assert team_with_stale_trial.billing_plan_limits["subscription_status"] == "canceled"
        assert team_with_stale_trial.billing_plan_limits["is_trial"] is False
        assert "Teams synced: 1" in out.getvalue()

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_dry_run_does_not_modify(self, mock_stripe_client_class, mock_billing_enabled, team_with_stale_trial):
        """Test that dry run does not modify the database."""
        mock_billing_enabled.return_value = True

        # Mock Stripe returning canceled status
        mock_subscription = MagicMock()
        mock_subscription.status = "canceled"
        mock_subscription.trial_end = team_with_stale_trial.billing_plan_limits["trial_end"]
        mock_stripe_client_class.return_value.get_subscription.return_value = mock_subscription

        original_status = team_with_stale_trial.billing_plan_limits["subscription_status"]

        out = StringIO()
        call_command("sync_stripe_subscriptions", "--dry-run", stdout=out)

        # Verify team was NOT updated
        team_with_stale_trial.refresh_from_db()
        assert team_with_stale_trial.billing_plan_limits["subscription_status"] == original_status
        assert "DRY RUN" in out.getvalue()

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_sync_specific_team(self, mock_stripe_client_class, mock_billing_enabled, team_with_stale_trial):
        """Test syncing a specific team by key."""
        mock_billing_enabled.return_value = True

        mock_subscription = MagicMock()
        mock_subscription.status = "canceled"
        mock_subscription.trial_end = team_with_stale_trial.billing_plan_limits["trial_end"]
        mock_stripe_client_class.return_value.get_subscription.return_value = mock_subscription

        out = StringIO()
        call_command("sync_stripe_subscriptions", f"--team-key={team_with_stale_trial.key}", stdout=out)

        team_with_stale_trial.refresh_from_db()
        assert team_with_stale_trial.billing_plan_limits["subscription_status"] == "canceled"

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_stale_trials_only_filter(
        self,
        mock_stripe_client_class,
        mock_billing_enabled,
        team_with_stale_trial,
        team_with_active_subscription,
    ):
        """Test that --stale-trials-only only processes stale trials."""
        mock_billing_enabled.return_value = True

        mock_subscription = MagicMock()
        mock_subscription.status = "canceled"
        mock_subscription.trial_end = team_with_stale_trial.billing_plan_limits["trial_end"]
        mock_stripe_client_class.return_value.get_subscription.return_value = mock_subscription

        out = StringIO()
        call_command("sync_stripe_subscriptions", "--stale-trials-only", stdout=out)

        # Should only find the stale trial team
        assert "Found 1 teams with potentially stale trials" in out.getvalue()

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_stripe_error_handling(self, mock_stripe_client_class, mock_billing_enabled, team_with_stale_trial):
        """Test that Stripe errors are handled gracefully."""
        mock_billing_enabled.return_value = True

        # Mock Stripe raising an error
        mock_stripe_client_class.return_value.get_subscription.side_effect = StripeError("Subscription not found")

        out = StringIO()
        call_command("sync_stripe_subscriptions", stdout=out)

        assert "Errors: 1" in out.getvalue()
        assert "Stripe error" in out.getvalue()

    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.is_billing_enabled")
    @patch("sbomify.apps.billing.management.commands.sync_stripe_subscriptions.StripeClient")
    def test_team_not_found(self, mock_stripe_client_class, mock_billing_enabled, db):
        """Test with non-existent team key."""
        mock_billing_enabled.return_value = True

        out = StringIO()
        call_command("sync_stripe_subscriptions", "--team-key=nonexistent", stdout=out)

        assert "Team with key 'nonexistent' not found" in out.getvalue()
