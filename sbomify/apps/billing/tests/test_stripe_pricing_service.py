from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_pricing_service import StripePricingService


class TestStripePricingService:
    @pytest.fixture
    def mock_stripe_client(self):
        mock_client = MagicMock()
        with patch("sbomify.apps.billing.stripe_pricing_service.get_stripe_client", return_value=mock_client):
            yield mock_client

    @pytest.fixture
    def service(self, mock_stripe_client):
        return StripePricingService()

    @pytest.fixture
    def mock_plans(self, db):
        BillingPlan.objects.create(key="community", name="Community", description="Community Plan")
        p1 = BillingPlan.objects.create(
            key="business",
            name="Business",
            description="Business Plan",
            stripe_product_id="prod_business",
        )
        return [p1]

    def test_get_all_plans_pricing_success(self, service, mock_stripe_client, mock_plans):
        mock_product = MagicMock()
        mock_product.id = "prod_business"
        mock_product.metadata = {}

        mock_price_monthly = MagicMock()
        mock_price_monthly.id = "price_biz_mo"
        mock_price_monthly.recurring.interval = "month"
        mock_price_monthly.unit_amount = 2000  # $20.00

        mock_price_annual = MagicMock()
        mock_price_annual.id = "price_biz_yr"
        mock_price_annual.recurring.interval = "year"
        mock_price_annual.unit_amount = 20000  # $200.00

        mock_stripe_client.get_all_products_with_prices.return_value = [
            {"product": mock_product, "prices": [mock_price_monthly, mock_price_annual]}
        ]

        pricing = service.get_all_plans_pricing(force_refresh=True)

        assert "business" in pricing
        biz_pricing = pricing["business"]

        assert biz_pricing["monthly_price"] == Decimal("20.00")
        assert biz_pricing["annual_price"] == Decimal("200.00")
        assert biz_pricing["monthly_price_annualized"] == Decimal("240.00")
        assert biz_pricing["monthly_id"] == "price_biz_mo"
        assert biz_pricing["annual_id"] == "price_biz_yr"

        # Savings: 20*12 = 240. Annual = 200. Savings = 40.
        assert biz_pricing["savings"] == Decimal("40.00")
        # Discount %: 40/240 = 16.66% -> 16.7%
        assert biz_pricing["annual_savings_percent"] == 16.7

    def test_get_all_plans_pricing_returns_cached_on_stripe_failure(self, service, mock_stripe_client, mock_plans, db):
        from sbomify.apps.billing.stripe_client import StripeError

        # First, setup the plan with cached data
        plan = BillingPlan.objects.get(key="business")
        plan.monthly_price = Decimal("199.00")
        plan.annual_price = Decimal("1908.00")
        plan.stripe_price_monthly_id = "price_cached_mo"
        plan.stripe_price_annual_id = "price_cached_yr"
        plan.save(update_fields=["monthly_price", "annual_price", "stripe_price_monthly_id", "stripe_price_annual_id"])

        # Make Stripe API fail
        mock_stripe_client.get_all_products_with_prices.side_effect = StripeError("API Error")

        pricing = service.get_all_plans_pricing(force_refresh=True)

        # Should return cached data instead of empty dict
        assert "business" in pricing
        assert pricing["business"]["monthly_price"] == Decimal("199.00")
        assert pricing["business"]["annual_price"] == Decimal("1908.00")


class TestCreateCheckoutSession:
    @pytest.fixture
    def mock_stripe_client(self):
        mock_client = MagicMock()
        with patch("sbomify.apps.billing.stripe_pricing_service.get_stripe_client", return_value=mock_client):
            yield mock_client

    @pytest.fixture
    def service(self, mock_stripe_client):
        return StripePricingService()

    @pytest.fixture
    def mock_team(self):
        team = MagicMock()
        team.key = "test_key"
        team.name = "Test Team"
        team.billing_plan_limits = {}
        return team

    @pytest.fixture
    def mock_plan(self):
        plan = MagicMock(spec=BillingPlan)
        plan.key = "business"
        plan.stripe_price_monthly_id = "price_mo_123"
        plan.stripe_price_annual_id = "price_yr_123"
        return plan

    def test_trial_period_included_in_session_data(self, service, mock_stripe_client, mock_team, mock_plan):
        mock_customer = MagicMock()
        mock_customer.id = "cus_test"
        mock_stripe_client.create_customer.return_value = mock_customer
        mock_stripe_client.create_checkout_session_raw.return_value = MagicMock(url="https://checkout.stripe.com/test")

        service.create_checkout_session(
            team=mock_team,
            user_email="test@example.com",
            plan=mock_plan,
            billing_period="monthly",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            trial_period_days=14,
        )

        call_args = mock_stripe_client.create_checkout_session_raw.call_args[0][0]
        assert call_args["subscription_data"] == {"trial_period_days": 14}
        assert call_args["payment_method_collection"] == "always"

    def test_trial_period_omitted_when_none(self, service, mock_stripe_client, mock_team, mock_plan):
        mock_customer = MagicMock()
        mock_customer.id = "cus_test"
        mock_stripe_client.create_customer.return_value = mock_customer
        mock_stripe_client.create_checkout_session_raw.return_value = MagicMock(url="https://checkout.stripe.com/test")

        service.create_checkout_session(
            team=mock_team,
            user_email="test@example.com",
            plan=mock_plan,
            billing_period="monthly",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        call_args = mock_stripe_client.create_checkout_session_raw.call_args[0][0]
        assert "subscription_data" not in call_args
        assert "payment_method_collection" not in call_args

    def test_trial_period_exceeding_max_raises_error(self, service, mock_stripe_client, mock_team, mock_plan):
        from sbomify.apps.billing.stripe_client import StripeError

        mock_customer = MagicMock()
        mock_customer.id = "cus_test"
        mock_stripe_client.create_customer.return_value = mock_customer

        with pytest.raises(StripeError, match="exceeds maximum"):
            service.create_checkout_session(
                team=mock_team,
                user_email="test@example.com",
                plan=mock_plan,
                billing_period="monthly",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                trial_period_days=100,
            )

    def test_coupon_and_trial_raises_error(self, service, mock_stripe_client, mock_team, mock_plan):
        from sbomify.apps.billing.stripe_client import StripeError

        mock_customer = MagicMock()
        mock_customer.id = "cus_test"
        mock_stripe_client.create_customer.return_value = mock_customer

        with pytest.raises(StripeError, match="Cannot combine"):
            service.create_checkout_session(
                team=mock_team,
                user_email="test@example.com",
                plan=mock_plan,
                billing_period="monthly",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                coupon_id="coupon_123",
                trial_period_days=14,
            )
