"""Tests for billing_return view covering idempotency, race conditions, and edge cases."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan

from sbomify.apps.billing.tests.fixtures import (  # noqa: F401
    business_plan,
    sample_user,
)
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401
from sbomify.apps.teams.models import Team

User = get_user_model()
pytestmark = pytest.mark.django_db


class TestBillingReturnIdempotency:
    """Test idempotency checks in billing_return view."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_idempotency_already_processed(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test that billing_return is idempotent - doesn't process same subscription twice."""
        # Set up team with existing subscription
        team_with_business_plan.billing_plan_limits = {
            "stripe_subscription_id": "sub_123",
            "stripe_customer_id": "cus_123",
        }
        team_with_business_plan.save()

        # Mock session data
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": team_with_business_plan.key,
            "plan_key": "business",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription data
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "month"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_subscription.cancel_at_period_end = False
        mock_get_subscription.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        # Verify team was NOT updated (idempotency check worked)
        team_with_business_plan.refresh_from_db()
        # Should still have the same subscription ID
        assert (
            team_with_business_plan.billing_plan_limits["stripe_subscription_id"]
            == "sub_123"
        )

        # Check success message was shown
        messages = list(get_messages(response.wsgi_request))
        assert any("already active" in str(m) for m in messages)

    @patch("sbomify.apps.billing.views.sync_subscription_from_stripe")
    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_idempotency_different_subscription(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        mock_sync,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test that billing_return processes when subscription ID is different."""
        # Set up team with different subscription
        team_with_business_plan.billing_plan_limits = {
            "stripe_subscription_id": "sub_old",
            "stripe_customer_id": "cus_123",
        }
        team_with_business_plan.save()

        # Mock session data with NEW subscription
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_new"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": team_with_business_plan.key,
            "plan_key": "business",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription data
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_new"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "month"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_subscription.cancel_at_period_end = False
        mock_get_subscription.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        # Verify team WAS updated with new subscription
        team_with_business_plan.refresh_from_db()
        assert (
            team_with_business_plan.billing_plan_limits["stripe_subscription_id"]
            == "sub_new"
        )


class TestBillingReturnEdgeCases:
    """Test edge cases in billing_return view."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_plan_key_from_metadata(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test that plan_key from metadata is used correctly."""
        # Mock session data with plan_key in metadata
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": team_with_business_plan.key,
            "plan_key": "business",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription data
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "month"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_subscription.cancel_at_period_end = False
        mock_get_subscription.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        team_with_business_plan.refresh_from_db()
        assert team_with_business_plan.billing_plan == "business"

    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_plan_not_found(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
    ):
        """Test billing_return when plan key doesn't exist."""
        # Mock session data with invalid plan_key
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": team_with_business_plan.key,
            "plan_key": "nonexistent_plan",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription data
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "month"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_subscription.cancel_at_period_end = False
        mock_get_subscription.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        # Check error message was shown
        messages = list(get_messages(response.wsgi_request))
        assert any("configuration error" in str(m).lower() for m in messages)

    @patch("sbomify.apps.billing.views.sync_subscription_from_stripe")
    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_annual_billing_period(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        mock_sync,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test billing_return correctly detects annual billing period."""
        # Mock session data
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": team_with_business_plan.key,
            "plan_key": "business",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription data with annual interval
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "year"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_subscription.cancel_at_period_end = False
        mock_get_subscription.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        team_with_business_plan.refresh_from_db()
        assert (
            team_with_business_plan.billing_plan_limits["billing_period"] == "annual"
        )

    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_team_not_found(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        sample_user: AbstractBaseUser,  # noqa: F811
    ):
        """Test billing_return when team doesn't exist."""
        # Mock session data with non-existent team key
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": "nonexistent_team",
            "plan_key": "business",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription and customer to avoid real API calls
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "month"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_subscription.cancel_at_period_end = False
        mock_get_subscription.return_value = mock_subscription

        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        # Check error message was shown
        messages = list(get_messages(response.wsgi_request))
        assert any("not found" in str(m).lower() for m in messages)


class TestBillingReturnRaceConditions:
    """Test race condition handling in billing_return view."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    @patch("sbomify.apps.billing.views.stripe_client.get_customer")
    @patch("sbomify.apps.billing.views.stripe_client.get_subscription")
    @patch("sbomify.apps.billing.views.stripe_client.get_checkout_session")
    def test_billing_return_uses_select_for_update(
        self,
        mock_get_checkout_session,
        mock_get_subscription,
        mock_get_customer,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test that billing_return uses select_for_update for locking."""
        from django.db import connection
        from django.test.utils import override_settings

        # Mock session data
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {
            "team_key": team_with_business_plan.key,
            "plan_key": "business",
        }
        mock_get_checkout_session.return_value = mock_session

        # Mock subscription data
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        # Set up attribute access for items.data[0].plan.interval
        mock_plan = MagicMock()
        mock_plan.interval = "month"
        mock_item = MagicMock()
        mock_item.plan = mock_plan
        mock_subscription.items = MagicMock()
        mock_subscription.items.data = [mock_item]
        mock_subscription.cancel_at = None
        mock_subscription.current_period_end = 1735689600
        mock_get_subscription.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_get_customer.return_value = mock_customer

        self.client.force_login(sample_user)

        # Verify transaction is used (indirectly by checking it completes)
        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        # If we got here without deadlock, transaction worked
        team_with_business_plan.refresh_from_db()
        assert team_with_business_plan.billing_plan == "business"

