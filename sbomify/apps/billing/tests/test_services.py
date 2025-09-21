from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from sbomify.apps.billing.services import get_stripe_prices

class StripePricingServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('stripe.Price.list')
    def test_get_stripe_prices_success(self, mock_price_list):
        # Mock Stripe response
        mock_price = MagicMock()
        mock_price.unit_amount = 19900  # $199.00
        mock_price.recurring.interval = 'month'
        mock_price.product = MagicMock()
        mock_price.product.metadata = {'plan_key': 'business'}

        mock_price_annual = MagicMock()
        mock_price_annual.unit_amount = 190800  # $1,908.00
        mock_price_annual.recurring.interval = 'year'
        mock_price_annual.product = MagicMock()
        mock_price_annual.product.metadata = {'plan_key': 'business'}

        mock_price_list.return_value = MagicMock(data=[mock_price, mock_price_annual])

        # Test the service
        prices = get_stripe_prices()

        # Verify results
        self.assertIn('business', prices)
        self.assertEqual(prices['business']['monthly'], 199.00)
        self.assertEqual(prices['business']['annual'], 1908.00)

        # Verify caching
        cached_prices = cache.get('stripe_prices')
        self.assertEqual(cached_prices, prices)

    @patch('stripe.Price.list')
    def test_get_stripe_prices_error(self, mock_price_list):
        # Mock Stripe error
        mock_price_list.side_effect = Exception("Stripe API Error")

        # Test the service
        prices = get_stripe_prices()

        # Verify empty dict is returned on error
        self.assertEqual(prices, {})

    @patch('stripe.Price.list')
    def test_get_stripe_prices_cache(self, mock_price_list):
        # Set up cache
        test_prices = {'business': {'monthly': 199.00, 'annual': 1908.00}}
        cache.set('stripe_prices', test_prices, 3600)

        # Test the service
        prices = get_stripe_prices()

        # Verify cached prices are returned
        self.assertEqual(prices, test_prices)

        # Verify Stripe API was not called
        mock_price_list.assert_not_called()