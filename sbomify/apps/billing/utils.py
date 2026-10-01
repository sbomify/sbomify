"""
Utility functions for billing app.
"""

import logging
import sys
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)

# Constants - can be overridden via Django settings
PRICE_VALIDATION_TOLERANCE = Decimal(
    getattr(settings, "BILLING_PRICE_VALIDATION_TOLERANCE", "0.01")
)  # Allow 1 cent difference for floating point precision
STRIPE_API_LIMIT = getattr(settings, "BILLING_STRIPE_API_LIMIT", 100)  # Default limit for Stripe API pagination
CACHE_TTL_HOURS = getattr(settings, "BILLING_CACHE_TTL_HOURS", 1)  # Default cache TTL in hours


def is_test_environment() -> bool:
    """Check if we're in a test environment. Used to skip Stripe API calls during tests."""
    return any(
        [
            not getattr(settings, "STRIPE_SECRET_KEY", None),
            getattr(settings, "STRIPE_SECRET_KEY", "") == "sk_test_dummy_key_for_ci",
            getattr(settings, "TESTING", False),
            "test" in settings.DATABASES.get("default", {}).get("NAME", ""),
            "pytest" in sys.modules,
        ]
    )
