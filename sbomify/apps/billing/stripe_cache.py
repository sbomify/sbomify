"""
Helper module for caching Stripe subscription data to reduce API calls.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache

from sbomify.logging import getLogger

from .billing_helpers import parse_cancel_at
from .stripe_client import TERMINAL_SUBSCRIPTION_STATUSES, StripeError, get_stripe_client

logger = getLogger(__name__)

stripe_client = get_stripe_client()

# Cache TTL: 5 minutes (300 seconds)
CACHE_TTL = 300


def get_cached_subscription(subscription_id: str, team_key: str) -> Any:
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
        logger.warning("Failed to fetch subscription from Stripe: %s", e)
        return None
    except Exception as e:
        logger.warning("Unexpected error fetching subscription: %s", e)
        return None


def set_cached_subscription(subscription_id: str, team_key: str, subscription: Any) -> None:
    """Cache a subscription object."""
    cache_key = f"stripe_sub_{subscription_id}_{team_key}"
    cache.set(cache_key, subscription, CACHE_TTL)
    logger.debug("Cached subscription data")


def invalidate_subscription_cache(subscription_id: str, team_key: str | None = None) -> None:
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
    Report whether the subscription has a pending cancel (with caching and error handling).

    A cancel is pending when cancel_at_period_end is set or when Stripe has a
    cancel_at date, so a scheduled cancel_at counts the same as a period-end cancel.

    Args:
        subscription_id: Stripe subscription ID
        team_key: Team key for cache key generation
        fallback_value: Value to return if Stripe fetch fails or the subscription is canceled or incomplete_expired

    Returns:
        True if a cancel is pending, or fallback_value on error or for a canceled or incomplete_expired subscription
    """
    if not subscription_id:
        return fallback_value

    subscription = get_cached_subscription(subscription_id, team_key)
    if subscription:
        # A canceled or incomplete_expired subscription keeps no pending cancel to reverse, so what the
        # workspace stored stands until the deleted event settles it.
        if getattr(subscription, "status", None) in TERMINAL_SUBSCRIPTION_STATUSES:
            return fallback_value
        # A cancel set through cancel_at is as pending as one set at period end.
        if parse_cancel_at(getattr(subscription, "cancel_at", None)) is not None:
            return True
        return bool(getattr(subscription, "cancel_at_period_end", fallback_value))

    # Fallback to cached database value on error
    return fallback_value
