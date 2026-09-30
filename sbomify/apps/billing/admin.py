from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.db.models import Q
from django.http import HttpRequest

from .models import BillingPlan
from .stripe_sync import sync_plan_prices_from_stripe

if TYPE_CHECKING:
    from django.db.models import QuerySet

    _BillingPlanAdminBase = admin.ModelAdmin[BillingPlan]
else:
    _BillingPlanAdminBase = admin.ModelAdmin


@admin.action(description="Sync prices from Stripe")
def sync_prices_from_stripe(
    modeladmin: BillingPlanAdmin, request: HttpRequest, queryset: QuerySet[BillingPlan]
) -> None:
    """Admin action to sync prices from Stripe for selected plans.

    Community has no Stripe prices, and a plan without a key would make the
    sync run for every plan, so both are left out.
    """
    synced = failed = 0
    for key in queryset.exclude(Q(key__isnull=True) | Q(key=BillingPlan.KEY_COMMUNITY)).values_list("key", flat=True):
        results = sync_plan_prices_from_stripe(key)
        synced += results["synced"]
        failed += results["failed"]
        for error in results["errors"]:
            modeladmin.message_user(request, error, level=messages.ERROR)

    if synced:
        modeladmin.message_user(request, f"Successfully synced prices for {synced} plan(s).", level=messages.SUCCESS)
    if failed:
        modeladmin.message_user(request, f"Encountered errors for {failed} plan(s).", level=messages.WARNING)


class BillingPlanAdmin(_BillingPlanAdminBase):
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

    @admin.display(description="Plan Limits")
    def display_limits(self, obj: BillingPlan) -> str:
        """Display plan limits in a compact format."""
        limits: list[str] = []
        if obj.max_users is not None:
            limits.append(f"Users: {obj.max_users}")
        elif obj.key == "enterprise":
            limits.append("Users: Unlimited")

        if obj.max_products is not None:
            limits.append(f"Products: {obj.max_products}")
        elif obj.key == "enterprise":
            limits.append("Products: Unlimited")

        if obj.max_components is not None:
            limits.append(f"Components: {obj.max_components}")
        elif obj.key == "enterprise":
            limits.append("Components: Unlimited")

        return " | ".join(limits) if limits else "Unlimited"

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
