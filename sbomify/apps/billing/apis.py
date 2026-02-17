from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.queries import get_team_asset_counts
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.teams.models import Team

from .billing_helpers import (
    RATE_LIMIT,
    RATE_LIMIT_PERIOD,
    check_rate_limit,
    handle_community_downgrade_visibility,
    require_team_owner,
)
from .models import BillingPlan
from .schemas import ChangePlanRequest, ChangePlanResponse, PlanSchema, UsageSchema
from .stripe_client import StripeError, get_stripe_client

router = Router(tags=["Billing"], auth=(PersonalAccessTokenAuth(), django_auth))


@router.get("/plans/", response={200: list[PlanSchema], 404: ErrorResponse})
def get_plans(request: HttpRequest):
    """Get all available billing plans."""
    plans = BillingPlan.objects.all()
    return 200, [
        PlanSchema.model_validate(
            {
                "key": plan.key,
                "name": plan.name,
                "description": plan.description,
                "max_products": plan.max_products,
                "max_projects": plan.max_projects,
                "max_components": plan.max_components,
            }
        )
        for plan in plans
    ]


@router.get("/usage/", response={200: UsageSchema, 403: ErrorResponse, 404: ErrorResponse})
def get_usage(request: HttpRequest):
    """Get current team's usage statistics.

    Note: Usage data (product/project/component counts) is not sensitive billing data.
    Any team member can view usage stats — the membership check below is sufficient.
    Owner-level access is not required here (unlike billing mutations).
    """
    team_key = request.GET.get("team_key") or request.session.get("current_team", {}).get("key")
    if not team_key:
        return 404, {"detail": "No team selected"}

    try:
        team = Team.objects.get(key=team_key)

        if not team.members.filter(member__user=request.user).exists():
            return 403, {"detail": "You do not have access to this workspace"}

        counts = get_team_asset_counts(team.id)

        return 200, UsageSchema(
            products=counts["products"],
            projects=counts["projects"],
            components=counts["components"],
            current_plan=team.billing_plan if team.billing_plan else None,
        )
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}


@router.post(
    "/change-plan/",
    response={200: ChangePlanResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 429: ErrorResponse},
)
def change_plan(request: HttpRequest, data: ChangePlanRequest):
    """Change the current team's billing plan."""
    if check_rate_limit(f"change_plan:{request.user.pk}", limit=RATE_LIMIT, period=RATE_LIMIT_PERIOD):
        return 429, {"detail": "Too many requests. Please try again later."}

    team_key = data.team_key or request.session.get("current_team", {}).get("key")

    if not team_key:
        return 404, {"detail": "No team selected"}

    try:
        team = Team.objects.get(key=team_key)

        is_owner, error_msg = require_team_owner(team, request.user)
        if not is_owner:
            return 403, {"detail": error_msg}

        plan = BillingPlan.objects.get(key=data.plan)
        stripe_client = get_stripe_client()

        if plan.key == "community":
            return _handle_community_downgrade(team, stripe_client)
        elif plan.key == "business":
            return _handle_business_upgrade(team, request, plan, data, stripe_client)

        return 400, {"detail": "Invalid plan"}

    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}
    except BillingPlan.DoesNotExist:
        return 400, {"detail": "Invalid plan"}
    except (StripeError, ValueError):
        return 400, {"detail": "Invalid request"}


def _handle_community_downgrade(team, stripe_client):
    """Handle downgrade to community plan."""
    customer_id = f"c_{team.key}"

    with transaction.atomic():
        team = Team.objects.select_for_update().get(pk=team.pk)
        billing_limits = team.billing_plan_limits or {}

        try:
            customer = stripe_client.get_customer(customer_id)
            subscriptions = stripe_client.list_subscriptions(customer.id, limit=1)

            if subscriptions.data:
                cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
                scheduled_downgrade_plan = billing_limits.get("scheduled_downgrade_plan")

                if cancel_at_period_end and scheduled_downgrade_plan:
                    return 400, {
                        "detail": (
                            "A downgrade is already scheduled. "
                            "Your current plan will remain active until the end of your billing period."
                        )
                    }

                stripe_client.modify_subscription(subscriptions.data[0].id, cancel_at_period_end=True)

                existing_limits = billing_limits.copy()
                existing_limits.update(
                    {
                        "cancel_at_period_end": True,
                        "scheduled_downgrade_plan": "community",
                        "stripe_subscription_id": subscriptions.data[0].id,
                        "subscription_status": "active",
                        "last_updated": timezone.now().isoformat(),
                    }
                )
                if "stripe_customer_id" not in existing_limits:
                    existing_limits["stripe_customer_id"] = customer.id

                team.billing_plan_limits = existing_limits
            else:
                plan = BillingPlan.objects.get(key="community")
                team.billing_plan = plan.key
                existing_limits = billing_limits.copy()
                existing_limits.update(
                    {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                    }
                )
                team.billing_plan_limits = existing_limits
                handle_community_downgrade_visibility(team)

        except StripeError:
            plan = BillingPlan.objects.get(key="community")
            team.billing_plan = plan.key
            existing_limits = billing_limits.copy()
            existing_limits.update(
                {
                    "max_products": plan.max_products,
                    "max_projects": plan.max_projects,
                    "max_components": plan.max_components,
                }
            )
            team.billing_plan_limits = existing_limits
            handle_community_downgrade_visibility(team)

        team.save()
    return 200, {"success": True}


def _handle_business_upgrade(team, request, plan, data, stripe_client):
    """Handle upgrade to business plan."""
    team_key = team.key
    customer_id = f"c_{team_key}"

    try:
        customer = stripe_client.get_customer(customer_id)
    except StripeError:
        customer = stripe_client.create_customer(
            email=request.user.email,
            name=team.name,
            metadata={"team_key": team_key},
            id=customer_id,
        )

    price_id = plan.stripe_price_annual_id if data.billing_period == "annual" else plan.stripe_price_monthly_id

    success_url = request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}"

    session = stripe_client.create_checkout_session(
        customer_id=customer.id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=request.build_absolute_uri("/"),
        metadata={"team_key": team_key},
    )

    return 200, ChangePlanResponse(redirect_url=session.url)
