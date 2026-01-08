from django.contrib import admin
from django.utils import timezone

from .stripe_client import StripeClient, StripeError


@admin.action(description="Sync prices from Stripe")
def sync_prices_from_stripe(modeladmin, request, queryset):
    """Admin action to sync prices from Stripe for selected plans."""
    stripe_client = StripeClient()
    updated_count = 0
    error_count = 0

    for plan in queryset:
        updated = False
        errors = []

        # Sync monthly price
        if plan.stripe_price_monthly_id:
            try:
                stripe_price = stripe_client.get_price(plan.stripe_price_monthly_id)
                if stripe_price.unit_amount:
                    plan.monthly_price = stripe_price.unit_amount / 100
                    updated = True
            except StripeError as e:
                errors.append(f"Monthly: {str(e)}")
                modeladmin.message_user(
                    request,
                    f"Error syncing monthly price for {plan.name}: {str(e)}",
                    level="error",
                )

        # Sync annual price
        if plan.stripe_price_annual_id:
            try:
                stripe_price = stripe_client.get_price(plan.stripe_price_annual_id)
                if stripe_price.unit_amount:
                    plan.annual_price = stripe_price.unit_amount / 100
                    updated = True
            except StripeError as e:
                errors.append(f"Annual: {str(e)}")
                modeladmin.message_user(
                    request,
                    f"Error syncing annual price for {plan.name}: {str(e)}",
                    level="error",
                )

        if updated:
            plan.last_synced_at = timezone.now()
            plan.save()
            updated_count += 1
        elif errors:
            error_count += 1

    if updated_count > 0:
        modeladmin.message_user(
            request,
            f"Successfully synced prices for {updated_count} plan(s).",
            level="success",
        )
    if error_count > 0:
        modeladmin.message_user(
            request,
            f"Encountered errors for {error_count} plan(s).",
            level="warning",
        )


class BillingPlanAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "key",
        "display_limits",
        "monthly_price",
        "annual_price",
        "discount_percent_monthly",
        "discount_percent_annual",
        "last_synced_at",
    ]
    list_filter = ["key"]
    search_fields = ["name", "key"]
    readonly_fields = ["last_synced_at"]
    actions = [sync_prices_from_stripe]

    def display_limits(self, obj):
        """Display plan limits in a compact format."""
        limits = []
        if obj.max_users is not None:
            limits.append(f"Users: {obj.max_users}")
        elif obj.key == "enterprise":
            limits.append("Users: Unlimited")

        if obj.max_products is not None:
            limits.append(f"Products: {obj.max_products}")
        elif obj.key == "enterprise":
            limits.append("Products: Unlimited")

        if obj.max_projects is not None:
            limits.append(f"Projects: {obj.max_projects}")
        elif obj.key == "enterprise":
            limits.append("Projects: Unlimited")

        if obj.max_components is not None:
            limits.append(f"Components: {obj.max_components}")
        elif obj.key == "enterprise":
            limits.append("Components: Unlimited")

        return " | ".join(limits) if limits else "Unlimited"

    display_limits.short_description = "Plan Limits"

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": ("key", "name", "description"),
            },
        ),
        (
            "Plan Limits",
            {
                "fields": (
                    "max_users",
                    "max_products",
                    "max_projects",
                    "max_components",
                ),
                "description": "Set limits for this plan. Leave blank or set to None for unlimited. "
                "Note: For Enterprise plans, typically all limits should be None (unlimited).",
            },
        ),
        (
            "Stripe Configuration",
            {
                "fields": (
                    "stripe_product_id",
                    "stripe_price_monthly_id",
                    "stripe_price_annual_id",
                ),
                "description": "Stripe product and price IDs. For Community plan, these can be left empty.",
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    "monthly_price",
                    "annual_price",
                    "discount_percent_monthly",
                    "discount_percent_annual",
                    "promo_message",
                    "last_synced_at",
                ),
            },
        ),
    )
