import json

from django import template
from django.utils.safestring import mark_safe

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_pricing_service import StripePricingService
from sbomify.logging import getLogger

logger = getLogger(__name__)

register = template.Library()


@register.simple_tag
def schema_org_metadata():
    """
    Generate schema.org metadata for the application, including dynamic pricing from Stripe.
    """
    # Get all non-community billing plans
    # Handle database errors gracefully (e.g., during test failures or transaction issues)
    from django.db import DatabaseError, InternalError

    try:
        plans = list(BillingPlan.objects.exclude(key="community"))
    except (InternalError, DatabaseError):
        # If database query fails (e.g., transaction aborted), return empty schema
        plans = []

    schema = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "SBOMify",
        "description": (
            "SBOMify is a powerful Software Bill of Materials (SBOM) management platform that helps "
            "organizations track, analyze, and manage their software dependencies and security vulnerabilities."
        ),
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "Web",
        "offers": [],
    }

    for plan in plans:
        # Use model prices first, fall back to Stripe API if model prices are None
        plan_prices = {}

        if plan.monthly_price_discounted is not None:
            plan_prices["monthly"] = float(plan.monthly_price_discounted)
        elif plan.monthly_price is not None:
            plan_prices["monthly"] = float(plan.monthly_price)

        if plan.annual_price_discounted is not None:
            plan_prices["annual"] = float(plan.annual_price_discounted)
        elif plan.annual_price is not None:
            plan_prices["annual"] = float(plan.annual_price)

        # Fall back to Stripe API if model prices are not available
        from sbomify.apps.billing.config import is_billing_enabled

        if not plan_prices and is_billing_enabled():
            try:
                stripe_pricing = StripePricingService().get_all_plans_pricing(force_refresh=False)
                plan_data = stripe_pricing.get(plan.key, {})
                if plan_data.get("monthly_price_discounted") is not None:
                    plan_prices["monthly"] = float(plan_data["monthly_price_discounted"])
                elif plan_data.get("monthly_price") is not None:
                    plan_prices["monthly"] = float(plan_data["monthly_price"])
                if plan_data.get("annual_price_discounted") is not None:
                    plan_prices["annual"] = float(plan_data["annual_price_discounted"])
                elif plan_data.get("annual_price") is not None:
                    plan_prices["annual"] = float(plan_data["annual_price"])
            except Exception:
                logger.debug("Failed to fetch Stripe pricing for schema markup")

        # Add monthly offer if available
        if "monthly" in plan_prices:
            schema["offers"].append(
                {
                    "@type": "Offer",
                    "name": f"{plan.name} - Monthly",
                    "price": plan_prices["monthly"],
                    "priceCurrency": "USD",
                    "priceSpecification": {
                        "@type": "UnitPriceSpecification",
                        "price": plan_prices["monthly"],
                        "priceCurrency": "USD",
                        "billingDuration": "P1M",
                        "billingIncrement": 1,
                    },
                }
            )

        # Add annual offer if available
        if "annual" in plan_prices:
            schema["offers"].append(
                {
                    "@type": "Offer",
                    "name": f"{plan.name} - Annual",
                    "price": plan_prices["annual"],
                    "priceCurrency": "USD",
                    "priceSpecification": {
                        "@type": "UnitPriceSpecification",
                        "price": plan_prices["annual"],
                        "priceCurrency": "USD",
                        "billingDuration": "P1Y",
                        "billingIncrement": 1,
                    },
                }
            )

    json_ld = json.dumps(schema)
    # mark_safe is safe here because the schema is built only from trusted backend data (billing plans, Stripe prices),
    # and json.dumps ensures proper escaping. No user-supplied data is included in the output.
    return mark_safe(f'<script type="application/ld+json">{json_ld}</script>')  # nosec
