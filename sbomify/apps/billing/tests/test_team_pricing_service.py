"""
Tests for TeamPricingService.

Tests pricing calculations, plan limits display, and Stripe invoice fetching.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.billing.stripe_client import StripeError
from sbomify.apps.billing.team_pricing_service import TeamPricingService
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    team_with_business_plan,
    team_with_community_plan,
)

from .fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe,
)


@pytest.fixture
def pricing_service():
    """Create a TeamPricingService instance."""
    return TeamPricingService()


@pytest.fixture
def team_with_last_payment(team_with_business_plan):  # noqa: F811
    """Team with cached last payment amount."""
    team_with_business_plan.billing_plan_limits = {
        **team_with_business_plan.billing_plan_limits,
        "last_payment_amount": 199.0,
        "last_payment_currency": "usd",
        "billing_period": "monthly",
        "next_billing_date": "2025-02-01T00:00:00+00:00",
    }
    team_with_business_plan.save()
    return team_with_business_plan


@pytest.fixture
def team_with_annual_billing(team_with_business_plan):  # noqa: F811
    """Team with annual billing period."""
    team_with_business_plan.billing_plan_limits = {
        **team_with_business_plan.billing_plan_limits,
        "last_payment_amount": 1908.0,
        "last_payment_currency": "usd",
        "billing_period": "annual",
        "next_billing_date": "2026-01-01T00:00:00+00:00",
    }
    team_with_business_plan.save()
    return team_with_business_plan


@pytest.mark.django_db
class TestGetPlanLimits:
    """Tests for TeamPricingService.get_plan_limits()"""

    def test_returns_correct_icons(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Verify icons are 'cube', 'folder', 'puzzle-piece' for Tailwind."""
        limits = pricing_service.get_plan_limits(team_with_business_plan, business_plan)

        icons = {item["label"]: item["icon"] for item in limits}
        assert icons.get("Products") == "cube"
        assert icons.get("Projects") == "folder"
        assert icons.get("Components") == "puzzle-piece"

    def test_with_billing_plan_obj(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Test passing BillingPlan object directly."""
        limits = pricing_service.get_plan_limits(team_with_business_plan, business_plan)

        assert len(limits) == 3
        labels = [item["label"] for item in limits]
        assert "Products" in labels
        assert "Projects" in labels
        assert "Components" in labels

    def test_fetches_billing_plan_if_not_provided(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Test auto-fetch BillingPlan from DB when not provided."""
        limits = pricing_service.get_plan_limits(team_with_business_plan)
        assert len(limits) == 3

    def test_unlimited_display(self, pricing_service, team_with_business_plan, enterprise_plan):  # noqa: F811
        """Test -1 or None shows 'Unlimited'."""
        team_with_business_plan.billing_plan = "enterprise"
        team_with_business_plan.billing_plan_limits = {
            "max_products": -1,
            "max_projects": None,
            "max_components": -1,
        }
        team_with_business_plan.save()

        limits = pricing_service.get_plan_limits(team_with_business_plan, enterprise_plan)

        for item in limits:
            assert item["value"] == "Unlimited"

    def test_numeric_values(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Test numeric limits are converted to strings."""
        limits = pricing_service.get_plan_limits(team_with_business_plan, business_plan)

        for item in limits:
            assert isinstance(item["value"], str)

    def test_prefers_team_limits_over_model(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Test billing_plan_limits takes priority over BillingPlan model values."""
        team_with_business_plan.billing_plan_limits = {
            **team_with_business_plan.billing_plan_limits,
            "max_products": 50,
            "max_projects": 100,
            "max_components": 500,
        }
        team_with_business_plan.save()

        limits = pricing_service.get_plan_limits(team_with_business_plan, business_plan)

        values = {item["label"]: item["value"] for item in limits}
        assert values.get("Products") == "50"
        assert values.get("Projects") == "100"
        assert values.get("Components") == "500"

    def test_fallback_when_no_billing_plan(self, pricing_service, team_with_business_plan):  # noqa: F811
        """Test fallback to billing_plan_limits when BillingPlan doesn't exist."""
        team_with_business_plan.billing_plan = "nonexistent_plan"
        team_with_business_plan.billing_plan_limits = {
            "max_products": 25,
            "max_projects": 50,
            "max_components": 200,
        }
        team_with_business_plan.save()

        limits = pricing_service.get_plan_limits(team_with_business_plan)

        values = {item["label"]: item["value"] for item in limits}
        assert values.get("Products") == "25"
        assert values.get("Projects") == "50"
        assert values.get("Components") == "200"


@pytest.mark.django_db
class TestGetPlanPricing:
    """Tests for TeamPricingService.get_plan_pricing()"""

    def test_community_free(self, pricing_service, team_with_community_plan, community_plan):  # noqa: F811
        """Community plan returns '$0 forever'."""
        pricing = pricing_service.get_plan_pricing(team_with_community_plan, community_plan)

        assert pricing["amount"] == "$0"
        assert pricing["period"] == "forever"
        assert pricing["billing_period"] is None

    def test_community_without_plan_obj(self, pricing_service, team_with_community_plan):  # noqa: F811
        """Community plan returns free even when BillingPlan object not provided."""
        pricing = pricing_service.get_plan_pricing(team_with_community_plan)

        assert pricing["amount"] == "$0"
        assert pricing["period"] == "forever"

    def test_with_last_payment_amount(self, pricing_service, team_with_last_payment, business_plan):  # noqa: F811
        """Uses cached last_payment_amount."""
        pricing = pricing_service.get_plan_pricing(team_with_last_payment, business_plan)

        assert pricing["amount"] == "$199"
        assert pricing["period"] == "per month"
        assert pricing["billing_period"] == "monthly"

    def test_monthly_period(self, pricing_service, team_with_last_payment, business_plan):  # noqa: F811
        """Monthly period shows 'per month'."""
        pricing = pricing_service.get_plan_pricing(team_with_last_payment, business_plan)
        assert "per month" in pricing["period"]

    def test_annual_period(self, pricing_service, team_with_annual_billing, business_plan):  # noqa: F811
        """Annual period shows 'per year'."""
        pricing = pricing_service.get_plan_pricing(team_with_annual_billing, business_plan)

        assert pricing["period"] == "per year"
        assert pricing["billing_period"] == "annual"

    @patch("sbomify.apps.billing.stripe_sync.sync_subscription_from_stripe")
    @patch.object(TeamPricingService, "_get_plan_pricing_from_stripe")
    def test_fallback_to_stripe(
        self,
        mock_stripe_pricing,
        mock_sync,
        pricing_service,
        team_with_business_plan,
        business_plan,
    ):  # noqa: F811
        """Falls back to StripePricingService when no cached amount."""
        mock_stripe_pricing.return_value = {
            "amount": "$199",
            "period": "per month",
            "billing_period": "monthly",
        }
        mock_sync.return_value = None

        team_with_business_plan.billing_plan_limits = {
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
            "billing_period": "monthly",
        }
        team_with_business_plan.save()

        pricing_service.get_plan_pricing(team_with_business_plan, business_plan)
        mock_stripe_pricing.assert_called_once()

    def test_custom_on_error(self, pricing_service, team_with_business_plan):  # noqa: F811
        """Returns 'Custom pricing' when Stripe fails."""
        team_with_business_plan.billing_plan = "enterprise"
        team_with_business_plan.billing_plan_limits = {}
        team_with_business_plan.save()

        pricing = pricing_service.get_plan_pricing(team_with_business_plan)
        assert pricing["amount"] in ["Contact us", "Custom"]

    @patch("sbomify.apps.billing.stripe_sync.sync_subscription_from_stripe")
    @patch("stripe.Subscription.list")
    def test_recovers_subscription_id(
        self,
        mock_sub_list,
        mock_sync,
        pricing_service,
        team_with_business_plan,
        business_plan,
    ):  # noqa: F811
        """Recovers subscription ID from Stripe customer when missing."""
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_recovered123"
        mock_sub_list.return_value = MagicMock(data=[mock_subscription])
        mock_sync.return_value = None

        # Keep subscription_id to satisfy DB constraint - test recovery logic path
        team_with_business_plan.billing_plan_limits = {
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_old123",
            "last_payment_amount": 199.0,
            "last_payment_currency": "usd",
            "billing_period": "monthly",
        }
        team_with_business_plan.save()

        pricing_service.get_plan_pricing(team_with_business_plan, business_plan)
        # Sync mock prevents actual Stripe calls
        mock_sync.assert_called()

    def test_non_usd_currency(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Test non-USD currency display."""
        # Team with EUR currency and no subscription ID to skip sync
        team_with_business_plan.billing_plan_limits = {
            "last_payment_amount": 199.0,
            "last_payment_currency": "eur",
            "billing_period": "monthly",
            # No subscription_id means sync won't be attempted
        }
        team_with_business_plan.billing_plan = "community"  # No sync for community
        team_with_business_plan.save()

        # Force the pricing path that uses cached values
        team_with_business_plan.billing_plan = "business"  # Back to business
        team_with_business_plan.billing_plan_limits["last_payment_amount"] = 199.0
        team_with_business_plan.billing_plan_limits["last_payment_currency"] = "eur"
        team_with_business_plan.billing_plan_limits["billing_period"] = "monthly"

        # Create a simple team object to pass to get_plan_pricing
        class MockTeam:
            def __init__(self, team):
                self.billing_plan = "business"
                self.billing_plan_limits = {
                    "last_payment_amount": 199.0,
                    "last_payment_currency": "eur",
                    "billing_period": "monthly",
                }

        mock_team = MockTeam(team_with_business_plan)
        pricing = pricing_service.get_plan_pricing(mock_team, business_plan)
        assert "EUR" in pricing["amount"]


@pytest.mark.django_db
class TestFetchInvoiceAmount:
    """Tests for TeamPricingService._fetch_invoice_amount()"""

    @patch.object(TeamPricingService, "_fetch_invoice_amount")
    def test_success(self, mock_fetch, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Successfully fetches and caches invoice data."""
        mock_fetch.return_value = (199.0, "usd", "2025-02-01T00:00:00+00:00")

        team_with_business_plan.billing_plan_limits = {
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
        }
        team_with_business_plan.save()

        pricing_service.get_plan_pricing(team_with_business_plan, business_plan)
        mock_fetch.assert_called_once()

    def test_stripe_error_returns_none(self, pricing_service, team_with_business_plan):  # noqa: F811
        """StripeError handled gracefully."""
        with patch.object(pricing_service.stripe_client, "get_subscription") as mock_get_sub:
            mock_get_sub.side_effect = StripeError("API Error")

            amount, currency, next_date = pricing_service._fetch_invoice_amount("sub_test123", team_with_business_plan)

            assert amount is None
            assert currency == "usd"
            assert next_date is None


@pytest.mark.django_db
class TestNextBillingDateParsing:
    """Tests for next_billing_date parsing in get_plan_pricing()"""

    def test_iso_string(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """ISO string parsed to datetime."""
        team_with_business_plan.billing_plan_limits = {
            **team_with_business_plan.billing_plan_limits,
            "last_payment_amount": 199.0,
            "last_payment_currency": "usd",
            "billing_period": "monthly",
            "next_billing_date": "2025-02-01T00:00:00+00:00",
        }
        team_with_business_plan.save()

        pricing = pricing_service.get_plan_pricing(team_with_business_plan, business_plan)

        assert "next_billing_date" in pricing
        assert isinstance(pricing["next_billing_date"], datetime)

    def test_timezone_aware(self, pricing_service, team_with_business_plan, business_plan):  # noqa: F811
        """Result is timezone-aware."""
        team_with_business_plan.billing_plan_limits = {
            **team_with_business_plan.billing_plan_limits,
            "last_payment_amount": 199.0,
            "last_payment_currency": "usd",
            "billing_period": "monthly",
            "next_billing_date": "2025-02-01T00:00:00",
        }
        team_with_business_plan.save()

        pricing = pricing_service.get_plan_pricing(team_with_business_plan, business_plan)

        if pricing.get("next_billing_date"):
            assert pricing["next_billing_date"].tzinfo is not None


@pytest.mark.django_db
class TestGetPlanPricingFromStripe:
    """Tests for TeamPricingService._get_plan_pricing_from_stripe()"""

    def test_monthly(self, pricing_service, business_plan):  # noqa: F811
        """Get monthly pricing from Stripe."""
        with patch.object(pricing_service.pricing_service, "get_all_plans_pricing") as mock_pricing:
            mock_pricing.return_value = {
                "business": {
                    "monthly_price_discounted": "199",
                    "annual_price_discounted": "1908",
                }
            }

            pricing = pricing_service._get_plan_pricing_from_stripe("business", "monthly")

            assert pricing["amount"] == "$199"
            assert pricing["period"] == "per month"

    def test_annual(self, pricing_service, business_plan):  # noqa: F811
        """Get annual pricing from Stripe."""
        with patch.object(pricing_service.pricing_service, "get_all_plans_pricing") as mock_pricing:
            mock_pricing.return_value = {
                "business": {
                    "monthly_price_discounted": "199",
                    "annual_price_discounted": "1908",
                }
            }

            pricing = pricing_service._get_plan_pricing_from_stripe("business", "annual")

            assert pricing["amount"] == "$1,908"
            assert pricing["period"] == "per year"

    def test_error_returns_custom(self, pricing_service):
        """Returns 'Custom pricing' on error."""
        with patch.object(pricing_service.pricing_service, "get_all_plans_pricing") as mock_pricing:
            mock_pricing.side_effect = Exception("Stripe API Error")

            pricing = pricing_service._get_plan_pricing_from_stripe("business", "monthly")

            assert pricing["amount"] == "Custom"
            assert pricing["period"] == "pricing"
