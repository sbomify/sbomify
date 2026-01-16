from typing import Dict

import stripe
from django.conf import settings
from django.core.cache import cache


def get_stripe_prices() -> Dict[str, Dict[str, float]]:
    """
    Get current prices from Stripe, with caching.
    Returns a dict of plan_key -> {monthly: price, annual: price}
    """
    cache_key = "stripe_prices"
    cached_prices = cache.get(cache_key)
    if cached_prices:
        return cached_prices

    stripe.api_key = settings.STRIPE_SECRET_KEY
    prices = {}

    try:
        # Get all active prices
        stripe_prices = stripe.Price.list(active=True, expand=["data.product"])

        # Group prices by product
        for price in stripe_prices.data:
            product = price.product
            if not product or not product.metadata.get("plan_key"):
                continue

            plan_key = product.metadata["plan_key"]
            if plan_key not in prices:
                prices[plan_key] = {}

            # Convert from cents to dollars
            amount = price.unit_amount / 100 if price.unit_amount else 0

            if price.recurring.interval == "month":
                prices[plan_key]["monthly"] = amount
            elif price.recurring.interval == "year":
                prices[plan_key]["annual"] = amount

        # Cache for 1 hour
        cache.set(cache_key, prices, 3600)
        return prices
    except (stripe.error.StripeError, Exception):
        # If Stripe is unavailable or any other error occurs, return empty dict
        return {}
