from django.conf import settings


def is_billing_enabled() -> bool:
    """Check if billing is enabled in the current environment."""
    return getattr(settings, "BILLING", True)


def get_unlimited_plan_limits() -> dict:
    """Get unlimited plan limits for when billing is disabled."""
    return {
        "max_products": None,
        "max_projects": None,
        "max_components": None,
        "subscription_status": "active",
    }
