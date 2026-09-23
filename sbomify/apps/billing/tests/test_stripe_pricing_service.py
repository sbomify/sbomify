import datetime
from contextlib import AbstractContextManager
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

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

    @staticmethod
    def _fail_with_cache_aged(mock_stripe_client: MagicMock, age: datetime.timedelta) -> None:
        """Prime every priced plan as synced ``age`` ago, then fail the Stripe call."""
        from sbomify.apps.billing.stripe_client import StripeError

        synced_at = timezone.now() - age
        for plan in BillingPlan.objects.exclude(key="community"):
            plan.monthly_price = Decimal("199.00")
            plan.last_synced_at = synced_at
            plan.save(update_fields=["monthly_price", "last_synced_at"])

        mock_stripe_client.get_all_products_with_prices.side_effect = StripeError("API Error")

    # The calls are asserted rather than captured text: the ``sbomify`` logger
    # does not propagate to root, so caplog sees nothing (see
    # ``test_stripe_timeout.py``).
    @staticmethod
    def _watch_logger() -> AbstractContextManager[MagicMock]:
        from sbomify.apps.billing import stripe_pricing_service

        return patch.object(stripe_pricing_service, "logger", MagicMock())

    @staticmethod
    def _watch_sentry() -> AbstractContextManager[MagicMock]:
        from sbomify.apps.billing import stripe_pricing_service

        return patch.object(stripe_pricing_service, "sentry_sdk", MagicMock())

    @staticmethod
    def _scope_of(sentry: MagicMock) -> MagicMock:
        """The scope the service pushed around the Stripe call."""
        return sentry.new_scope.return_value.__enter__.return_value

    def test_stripe_failure_with_fresh_cache_is_not_an_error(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """A recovered fetch must not reach Sentry.

        Sentry's logging integration is wired with ``event_level=ERROR``, so
        every error-level line here becomes an issue someone is paged for. This
        path served the caller the prices it asked for, so the outage is worth
        a line in the log and nothing louder.
        """
        self._fail_with_cache_aged(mock_stripe_client, datetime.timedelta(minutes=5))

        with self._watch_logger() as logger:
            pricing = service.get_all_plans_pricing(force_refresh=True)

        assert pricing["business"]["monthly_price"] == Decimal("199.00")
        assert logger.warning.call_count == 1
        assert logger.error.call_count == 0

    def test_the_pricing_service_writes_one_line_for_one_failure(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """The refresh helper used to log the failure and re-raise it into the
        caller, which logged it again — two Sentry issues from this module for
        one outage, on top of the one the client already raised.
        """
        self._fail_with_cache_aged(mock_stripe_client, datetime.timedelta(minutes=5))

        with self._watch_logger() as logger:
            service.get_all_plans_pricing(force_refresh=True)

        written = logger.warning.call_args_list + logger.error.call_args_list
        assert len([call for call in written if "Failed to fetch Stripe products" in call.args[0]]) == 1

    def test_a_stale_cache_does_not_add_a_second_error_record(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """The staleness rides on the Stripe error, it does not become its own.

        The client logs at error before it raises, so that failure is already
        going to Sentry. An error-level line here as well would make one failed
        request with an old cache into two issues.
        """
        self._fail_with_cache_aged(mock_stripe_client, datetime.timedelta(hours=25))

        with self._watch_logger() as logger:
            pricing = service.get_all_plans_pricing(force_refresh=True)

        assert pricing["business"]["monthly_price"] == Decimal("199.00")
        assert logger.error.call_count == 0
        assert logger.warning.call_count == 1
        assert "stale" in logger.warning.call_args.args[0]

    def test_a_stale_cache_tags_the_scope_the_stripe_call_runs_under(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """So the client's event answers "are these prices still any good"."""
        self._fail_with_cache_aged(mock_stripe_client, datetime.timedelta(hours=25))

        with self._watch_sentry() as sentry:
            service.get_all_plans_pricing(force_refresh=True)

        scope = self._scope_of(sentry)
        scope.set_tag.assert_called_once_with("pricing_cache_stale", True)
        name, context = scope.set_context.call_args.args
        assert name == "pricing_cache"
        assert context["stale_plans"] == ["business"]
        assert context["stale_after_hours"] == 24

    def test_a_fresh_cache_tags_the_scope_too(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """An explicit "not stale" is worth more than an absent tag.

        Reading the client's event, the question is whether the prices being
        served are still good. A missing tag cannot be told apart from a build
        that predates the tag.
        """
        self._fail_with_cache_aged(mock_stripe_client, datetime.timedelta(minutes=5))

        with self._watch_sentry() as sentry:
            service.get_all_plans_pricing(force_refresh=True)

        scope = self._scope_of(sentry)
        scope.set_tag.assert_called_once_with("pricing_cache_stale", False)
        scope.set_context.assert_not_called()

    def test_every_stale_plan_is_named_in_the_one_context(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """The plans go stale together — they share a sync and they share the
        outage that stopped it — so they are worth one report between them.
        """
        BillingPlan.objects.create(
            key="enterprise",
            name="Enterprise",
            description="Enterprise Plan",
            stripe_product_id="prod_enterprise",
        )
        self._fail_with_cache_aged(mock_stripe_client, datetime.timedelta(hours=25))

        with self._watch_sentry() as sentry:
            with self._watch_logger() as logger:
                service.get_all_plans_pricing(force_refresh=True)

        scope = self._scope_of(sentry)
        assert scope.set_context.call_count == 1
        assert scope.set_context.call_args.args[1]["stale_plans"] == ["business", "enterprise"]
        assert logger.error.call_count == 0

    def test_a_plan_that_never_synced_is_not_stale(
        self, service: StripePricingService, mock_stripe_client: MagicMock, mock_plans: list[BillingPlan], db: None
    ) -> None:
        """Unpopulated is not the same as no longer trustworthy."""
        from sbomify.apps.billing.stripe_client import StripeError

        plan = BillingPlan.objects.get(key="business")
        plan.monthly_price = Decimal("199.00")
        plan.last_synced_at = None
        plan.save(update_fields=["monthly_price", "last_synced_at"])
        mock_stripe_client.get_all_products_with_prices.side_effect = StripeError("API Error")

        with self._watch_sentry() as sentry:
            service.get_all_plans_pricing(force_refresh=True)

        self._scope_of(sentry).set_tag.assert_called_once_with("pricing_cache_stale", False)


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
        assert call_args["subscription_data"]["trial_period_days"] == 14
        assert call_args["payment_method_collection"] == "always"
        # A card collected at checkout can still be detached before the trial
        # ends, and Stripe's default then raises an invoice nobody can pay.
        assert call_args["subscription_data"]["trial_settings"] == {
            "end_behavior": {"missing_payment_method": "cancel"}
        }

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
