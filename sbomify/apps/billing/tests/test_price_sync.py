
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_sync import sync_plan_prices_from_stripe

pytestmark = pytest.mark.django_db


class TestSyncPlanPrices:
    @pytest.fixture
    def fresh_plan(self):
        """Create a plan with no Stripe IDs and no prices (fresh start)."""
        return BillingPlan.objects.create(
            key="enterprise",
            name="Enterprise",
            description="Enterprise Plan",
            monthly_price=None,
            annual_price=None,
            stripe_product_id=None,
            stripe_price_monthly_id=None,
            stripe_price_annual_id=None,
        )

    @patch("sbomify.apps.billing.stripe_sync.stripe_client")
    def test_sync_fresh_start_no_ids(self, mock_client, fresh_plan):
        """
        Test that sync works for a plan with no local Stripe IDs/prices,
        by looking up the product by name in Stripe.
        """
        # Mock Stripe Product list to return matching product
        mock_product = MagicMock()
        mock_product.id = "prod_enterprise"
        mock_product.name = "Enterprise"
        
        # When listing products, return our match
        mock_client.stripe.Product.list.return_value.data = [mock_product]
        
        # Mock Stripe Price list for the product - include 'created' timestamps for sorting
        mock_price_monthly = MagicMock()
        mock_price_monthly.id = "price_ent_mo"
        mock_price_monthly.recurring.interval = "month"
        mock_price_monthly.unit_amount = 5000  # $50.00
        mock_price_monthly.created = 1700000000  # Timestamp for sorting
        
        mock_price_annual = MagicMock()
        mock_price_annual.id = "price_ent_yr"
        mock_price_annual.recurring.interval = "year"
        mock_price_annual.unit_amount = 50000  # $500.00
        mock_price_annual.created = 1700000001  # Timestamp for sorting
        
        mock_client.stripe.Price.list.return_value.data = [
            mock_price_monthly,
            mock_price_annual
        ]
        
        # Mock get_price calls (used later in the sync function to fetch price details)
        def get_price_side_effect(price_id):
            if price_id == "price_ent_mo":
                return mock_price_monthly
            if price_id == "price_ent_yr":
                return mock_price_annual
            return None
            
        mock_client.get_price.side_effect = get_price_side_effect

        # Run sync
        results = sync_plan_prices_from_stripe(plan_key="enterprise")
        
        # Verify results
        assert results["failed"] == 0
        # If fixed, this should be 0 skipped, 1 synced.
        # Currently expected to be 1 skipped (broken behavior).
        
        fresh_plan.refresh_from_db()
        
        # Assertions that will fail until we fix the code
        assert fresh_plan.stripe_product_id == "prod_enterprise"
        assert fresh_plan.stripe_price_monthly_id == "price_ent_mo"
        assert fresh_plan.stripe_price_annual_id == "price_ent_yr"
        assert fresh_plan.monthly_price == Decimal("50.00")
        assert fresh_plan.annual_price == Decimal("500.00")
