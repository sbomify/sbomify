from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.authz import can
from sbomify.apps.core.models import User
from sbomify.apps.core.queries import get_team_asset_counts
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.teams.models import Team

from .billing_helpers import (
    RATE_LIMIT,
    RATE_LIMIT_PERIOD,
    acquire_checkout_lock,
    check_rate_limit,
    get_community_plan_limits,
    handle_community_downgrade_visibility,
    release_checkout_lock,
)
from .models import BillingPlan
from .schemas import ChangePlanRequest, ChangePlanResponse, PlanSchema, UsageSchema
from .stripe_client import BillingRetryableError, StripeError, StripeResourceMissingError, get_stripe_client

router = Router(tags=["Billing"], auth=(PersonalAccessTokenAuth(), django_auth))


@router.get("/plans/", response={200: list[PlanSchema], 404: ErrorResponse})
def get_plans(request: HttpRequest) -> tuple[int, Any]:
    """Get all available billing plans."""
    plans = BillingPlan.objects.all()
    return 200, [
        PlanSchema.model_validate(
            {
                "key": plan.key,
                "name": plan.name,
                "description": plan.description,
                "max_products": plan.max_products,
                "max_components": plan.max_components,
            }
        )
        for plan in plans
    ]


@router.get("/usage/", response={200: UsageSchema, 403: ErrorResponse, 404: ErrorResponse})
def get_usage(request: HttpRequest) -> tuple[int, Any]:
    """Get current team's usage statistics.

    Note: Usage data (product/component counts) is not sensitive billing data.
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

        if not can(request, "workspace:read", team):
            return 403, {"detail": "Forbidden"}

        counts = get_team_asset_counts(str(team.id))

        return 200, UsageSchema(
            products=counts["products"],
            components=counts["components"],
            current_plan=team.billing_plan if team.billing_plan else None,
        )
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}


@router.post(
    "/change-plan/",
    response={
        200: ChangePlanResponse,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        429: ErrorResponse,
        503: ErrorResponse,
    },
)
def change_plan(request: HttpRequest, data: ChangePlanRequest) -> tuple[int, Any]:
    """Change the current team's billing plan."""
    if check_rate_limit(f"change_plan:{request.user.pk}", limit=RATE_LIMIT, period=RATE_LIMIT_PERIOD):
        return 429, {"detail": "Too many requests. Please try again later."}

    team_key = data.team_key or request.session.get("current_team", {}).get("key")

    if not team_key:
        return 404, {"detail": "No team selected"}

    try:
        team = Team.objects.get(key=team_key)

        # Route through can() rather than require_billing_manager: this endpoint
        # accepts personal access tokens, and can() is the only place token
        # action scopes are enforced. A hand-rolled ORM role check would let a
        # narrowly-scoped token (e.g. publish-only) change the plan — and a
        # downgrade flips private products and components public.
        if not can(request, "billing:manage", team):
            # Deliberately not a role-specific message. can() also denies on
            # token action scope, so naming roles would tell the holder of a
            # publish-only token that their *role* is the problem and send them
            # to an admin who cannot fix it.
            return 403, {"detail": "You don't have permission to change this workspace's billing plan"}

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
    except BillingRetryableError:
        return 503, {"detail": "Billing is unavailable right now. Try again in a few minutes."}
    except (StripeError, ValueError):
        return 400, {"detail": "Invalid request"}


def _handle_community_downgrade(team: Team, stripe_client: Any) -> tuple[int, Any]:
    """Handle downgrade to community plan."""
    with transaction.atomic():
        team = Team.objects.select_for_update().get(pk=team.pk)
        billing_limits = team.billing_plan_limits or {}

        # Only a subscription Stripe reports gone or ended moves the workspace
        # now. Any other Stripe error propagates and rolls this back: reading a
        # timeout as "no subscription" published a paying workspace's components.
        subscription = None
        subscription_missing = False
        if subscription_id := billing_limits.get("stripe_subscription_id"):
            try:
                subscription = stripe_client.get_subscription(subscription_id)
            except StripeResourceMissingError:
                subscription_missing = True

        if subscription is not None and subscription.status not in ("canceled", "incomplete_expired"):
            if billing_limits.get("cancel_at_period_end") and billing_limits.get("scheduled_downgrade_plan"):
                return 400, {
                    "detail": (
                        "A downgrade is already scheduled. "
                        "Your current plan will remain active until the end of your billing period."
                    )
                }

            stripe_client.modify_subscription(subscription.id, cancel_at_period_end=True)

            existing_limits = billing_limits.copy()
            existing_limits.update(
                {
                    "cancel_at_period_end": True,
                    "scheduled_downgrade_plan": "community",
                    "subscription_status": subscription.status,
                    "last_updated": timezone.now().isoformat(),
                }
            )
            team.billing_plan_limits = existing_limits
        else:
            team.billing_plan = "community"
            existing_limits = billing_limits.copy()
            existing_limits.update(get_community_plan_limits())
            # The downgrade happens now, so nothing is left scheduled.
            existing_limits.pop("scheduled_downgrade_plan", None)
            existing_limits["cancel_at_period_end"] = False
            if subscription is not None:
                existing_limits["subscription_status"] = subscription.status
            elif subscription_missing:
                # Stripe has no such subscription, so forget both ids, as the sync's reconcile does.
                existing_limits.pop("stripe_subscription_id", None)
                existing_limits.pop("stripe_customer_id", None)
                existing_limits["subscription_status"] = "canceled"
            team.billing_plan_limits = existing_limits
            handle_community_downgrade_visibility(team)

        team.save()
    return 200, {"success": True}


def _handle_business_upgrade(
    team: Team, request: HttpRequest, plan: BillingPlan, data: ChangePlanRequest, stripe_client: Any
) -> tuple[int, Any]:
    """Handle upgrade to business plan."""
    user = cast(User, request.user)

    team_key = team.key
    if not team_key:
        return 400, {"detail": "Workspace is not properly configured. Please contact support."}

    customer_id = f"c_{team_key}"

    try:
        customer = stripe_client.get_customer(customer_id)
    except StripeError:
        customer = stripe_client.create_customer(
            email=user.email,
            name=team.name,
            metadata={"team_key": team_key},
            id=customer_id,
        )

    price_id = plan.stripe_price_annual_id if data.billing_period == "annual" else plan.stripe_price_monthly_id
    if not price_id:
        return 400, {"detail": "Selected billing option is not available. Please try a different plan or period."}

    if not acquire_checkout_lock(team_key):
        return 429, {"detail": "A checkout is already in progress. Please wait a moment and try again."}

    try:
        success_url = (
            request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}"
        )

        session = stripe_client.create_checkout_session(
            customer_id=customer.id,
            price_id=price_id,
            success_url=success_url,
            cancel_url=request.build_absolute_uri("/"),
            metadata={"team_key": team_key, "plan_key": plan.key},
        )

        return 200, ChangePlanResponse(redirect_url=session.url)
    except Exception:
        release_checkout_lock(team_key)
        raise
