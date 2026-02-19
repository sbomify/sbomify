from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_sync import sync_plan_prices_from_stripe

pytestmark = pytest.mark.django_db


class TestSyncPricePersistence:
    @pytest.fixture
    def plan_with_prices(self):
        """Create a plan with local prices but no Stripe IDs."""
        return BillingPlan.objects.create(
            key="pro",
            name="Pro",
            description="Pro Plan",
            monthly_price=Decimal("29.00"),
            annual_price=Decimal("290.00"),
            stripe_product_id=None,
            stripe_price_monthly_id=None,
            stripe_price_annual_id=None,
        )

    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_local_prices_preserved_when_stripe_has_no_prices(self, mock_client, plan_with_prices):
        """
        Scenario: Local has prices. Stripe has NO prices for this product.
        Expectation: Sync is read-only - local prices preserved, IDs remain None.
        """
        # Mock Product list to return matching product
        mock_product = MagicMock()
        mock_product.id = "prod_pro"
        mock_product.name = "Pro"
        mock_client.list_products.return_value.data = [mock_product]

        # Mock Price list (empty - no prices in Stripe)
        mock_client.list_prices.return_value.data = []

        # Run sync
        sync_plan_prices_from_stripe(plan_key="pro")

        plan_with_prices.refresh_from_db()

        # Sync is read-only: no IDs linked (Stripe has no prices)
        assert plan_with_prices.stripe_price_monthly_id is None
        assert plan_with_prices.stripe_price_annual_id is None

        # Local prices should be preserved (not cleared)
        assert plan_with_prices.monthly_price == Decimal("29.00")
        assert plan_with_prices.annual_price == Decimal("290.00")

    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_local_prices_persisted_when_stripe_matches(self, mock_client, plan_with_prices):
        """
        Scenario: Local has prices. Stripe has MATCHING prices.
        Expectation: Sync should LINK IDs and KEEP local prices.
        """
        # Mock Product
        mock_product = MagicMock()
        mock_product.id = "prod_pro"
        mock_product.name = "Pro"
        mock_client.list_products.return_value.data = [mock_product]

        # Mock Prices (matching) - include 'created' timestamps for sorting
        mock_price_mo = MagicMock()
        mock_price_mo.id = "price_pro_mo"
        mock_price_mo.recurring.interval = "month"
        mock_price_mo.unit_amount = 2900  # Matches 29.00
        mock_price_mo.created = 1700000000  # Timestamp for sorting

        mock_price_yr = MagicMock()
        mock_price_yr.id = "price_pro_yr"
        mock_price_yr.recurring.interval = "year"
        mock_price_yr.unit_amount = 29000  # Matches 290.00
        mock_price_yr.created = 1700000001  # Timestamp for sorting

        mock_client.list_prices.return_value.data = [mock_price_mo, mock_price_yr]

        # Mock get_price
        def get_price_side_effect(price_id):
            if price_id == "price_pro_mo":
                return mock_price_mo
            if price_id == "price_pro_yr":
                return mock_price_yr
            return None

        mock_client.get_price.side_effect = get_price_side_effect

        # Run sync
        sync_plan_prices_from_stripe(plan_key="pro")

        plan_with_prices.refresh_from_db()

        # Verify IDs linked
        assert plan_with_prices.stripe_price_monthly_id == "price_pro_mo"

        # Verify prices preserved
        assert plan_with_prices.monthly_price == Decimal("29.00")
