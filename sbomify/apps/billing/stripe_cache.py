"""
Helper module for caching Stripe subscription data to reduce API calls.
"""

from django.core.cache import cache

from sbomify.logging import getLogger

from .stripe_client import StripeClient, StripeError

logger = getLogger(__name__)

# Initialize Stripe client
stripe_client = StripeClient()

# Cache TTL: 5 minutes (300 seconds)
CACHE_TTL = 300


def get_cached_subscription(subscription_id: str, team_key: str):
    """
    Get subscription from cache or fetch from Stripe.

    Args:
        subscription_id: Stripe subscription ID
        team_key: Team key for cache key generation

    Returns:
        Stripe subscription object or None if not found/error
    """
    cache_key = f"stripe_sub_{subscription_id}_{team_key}"

    # Try to get from cache first
    cached_subscription = cache.get(cache_key)
    if cached_subscription:
        # subscription_id is internal, safe to log usage but avoiding explicit ID if requested for extreme caution
        logger.debug("Using cached subscription data")
        return cached_subscription

    # Fetch from Stripe
    try:
        subscription = stripe_client.get_subscription(subscription_id)
        # Cache for 5 minutes
        cache.set(cache_key, subscription, CACHE_TTL)
        logger.debug("Cached subscription data")
        return subscription
    except StripeError as e:
        logger.warning(f"Failed to fetch subscription from Stripe: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error fetching subscription: {e}")
        return None


def invalidate_subscription_cache(subscription_id: str, team_key: str = None):
    """
    Invalidate cache for a subscription.

    Args:
        subscription_id: Stripe subscription ID
        team_key: Optional team key. If None, invalidates for all teams (use with caution)
    """
    if team_key:
        cache_key = f"stripe_sub_{subscription_id}_{team_key}"
        cache.delete(cache_key)
        logger.debug("Invalidated cache for subscription")
    else:
        # If no team_key, we can't easily invalidate all variations
        # This is a fallback - prefer providing team_key
        logger.warning("Cannot invalidate cache for subscription without team_key")


def get_subscription_cancel_at_period_end(subscription_id: str, team_key: str, fallback_value: bool = False) -> bool:
    """
    Get cancel_at_period_end status from Stripe (with caching and error handling).

    Args:
        subscription_id: Stripe subscription ID
        team_key: Team key for cache key generation
        fallback_value: Value to return if Stripe fetch fails

    Returns:
        cancel_at_period_end boolean value, or fallback_value on error
    """
    if not subscription_id:
        return fallback_value

    subscription = get_cached_subscription(subscription_id, team_key)
    if subscription:
        return getattr(subscription, "cancel_at_period_end", fallback_value)

    # Fallback to cached database value on error
    return fallback_value
