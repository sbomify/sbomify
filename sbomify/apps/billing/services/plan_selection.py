"""Display data for the shared plan cards and their existing selection flow."""

from typing import Any

from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.plan_features import PLAN_FEATURES, features_lost_moving_to
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.queries import get_team_user_counts

_ORDER = {BillingPlan.KEY_COMMUNITY: 0, BillingPlan.KEY_BUSINESS: 1, BillingPlan.KEY_ENTERPRISE: 2}


def _usage(workspace: Team) -> dict[str, int]:
    """Two member counts, on purpose, matching what the rest of the product does.

    ``users`` is people, counted the way the members tab counts them, for the
    usage card. ``seats`` is what ``can_add_user_to_team`` enforces and what a
    plan's limits are checked against: an unexpired invitation is a seat already
    taken, and the synthetic bot members OIDC creates hold none.
    """
    users, _, seats = get_team_user_counts(workspace.id)
    return {
        "users": users,
        "seats": seats,
        "products": Product.objects.filter(team=workspace).count(),
        "components": Component.objects.filter(team=workspace).count(),
    }


def _exceeded(usage: dict[str, int], plan: BillingPlan) -> list[str]:
    # "members" is the word the cards use for max_users, so the warning keeps it
    # even though the number it counts is seats.
    return [
        f"{usage[key]} {label} (limit: {limit})"
        for key, label, limit in (
            ("seats", "members", plan.max_users),
            ("products", "products", plan.max_products),
            ("components", "components", plan.max_components),
        )
        if limit is not None and usage[key] > limit
    ]


def _guarded(workspace: Team, plan_key: str) -> bool:
    """Whether moving to ``plan_key`` is checked against its limits.

    Only a cheaper plan, and only from a live subscription. The plan cards and
    the request both ask this, so the server refuses exactly what the cards do.
    """
    current = workspace.billing_plan or BillingPlan.KEY_COMMUNITY
    subscribed = (workspace.billing_plan_limits or {}).get("subscription_status") in ("active", "trialing")
    return subscribed and _ORDER.get(plan_key, 99) < _ORDER.get(current, 99)


def usage_over(workspace: Team, plan: BillingPlan) -> list[str]:
    """Each of ``plan``'s limits that ``workspace`` is already past, ready to show.

    One count for every place that asks, so the plan cards, the request and the
    scheduled downgrade cannot disagree about which quotas a plan has.
    """
    return _exceeded(_usage(workspace), plan)


def check_downgrade(workspace: Team, plan: BillingPlan) -> ServiceResult[None]:
    """Refuse a move down to ``plan`` that ``workspace`` has outgrown.

    The plan cards disable that choice through ``downgradeLimits``. This is the
    same check for the request itself, which nothing on the page controls.
    """
    if not _guarded(workspace, plan.key or ""):
        return ServiceResult.success()
    exceeded = usage_over(workspace, plan)
    if exceeded:
        return ServiceResult.failure(f"Reduce usage to choose {plan.name}: {', '.join(exceeded)}.", status_code=409)
    return ServiceResult.success()


def build_plan_selection_context(
    request: HttpRequest, workspace: Team, stripe_pricing_data: dict[str, dict[str, Any]]
) -> ServiceResult[dict[str, Any]]:
    order = _ORDER
    usage = _usage(workspace)
    billing_limits = workspace.billing_plan_limits or {}
    current_plan = workspace.billing_plan or BillingPlan.KEY_COMMUNITY
    is_subscribed = billing_limits.get("subscription_status") in ("active", "trialing")
    plans: list[dict[str, Any]] = []
    downgrade_limits: dict[str, Any] = {}
    annual_savings_percent = None

    for plan in sorted(BillingPlan.objects.all(), key=lambda item: order.get(item.key or "", 99)):
        key = plan.key or ""
        pricing = dict(stripe_pricing_data.get(key, {}))
        pricing.setdefault("promo_message", plan.promo_message)
        is_downgrade = order.get(key, 99) < order.get(current_plan, 99)
        exceeded = _exceeded(usage, plan) if _guarded(workspace, key) else []
        downgrade_limits[key] = {"exceeds": bool(exceeded), "resources": exceeded}
        prices = []
        if key == BillingPlan.KEY_BUSINESS:
            annual_savings_percent = pricing.get("annual_savings_percent")
            for period, unit in (("monthly", "month"), ("annual", "year")):
                amount = pricing.get(f"{period}_price_discounted")
                original = pricing.get("monthly_price_base_annualized" if period == "annual" else "monthly_price")
                prices.append(
                    {
                        "period": period,
                        "amount": amount,
                        "original": original,
                        "unit": unit,
                        "discount": pricing.get(f"discount_percent_{period}"),
                        "promo": pricing.get("promo_message"),
                        "savings": pricing.get("total_annual_savings") if period == "annual" else None,
                    }
                )
        plans.append(
            {
                "key": key,
                "name": plan.name,
                "description": plan.description,
                "features": PLAN_FEATURES.get(key, ()),
                "current": key == current_plan,
                "downgrade": is_downgrade,
                # Only leaving a live subscription for the free plan runs to the
                # end of the billing period. An Enterprise-to-Business move is a
                # subscription update, and a workspace with nothing to cancel
                # changes over straight away.
                "ends_subscription": is_downgrade and key == BillingPlan.KEY_COMMUNITY and is_subscribed,
                "lost_features": features_lost_moving_to(current_plan, key) if is_downgrade else [],
                "prices": prices,
                "limits": [
                    {"label": "member", "count": plan.max_users},
                    {"label": "product", "count": plan.max_products},
                    {"label": "component", "count": plan.max_components},
                ],
            }
        )

    return ServiceResult.success(
        {
            "plans": plans,
            "team_key": workspace.key,
            "team": workspace,
            "usage": usage,
            "annual_savings_percent": annual_savings_percent,
            "plan_selection_data": {
                "currentPlan": current_plan,
                "csrfToken": get_token(request),
                "enterpriseContactUrl": reverse("billing:enterprise_contact"),
                "currentSubscriptionStatus": billing_limits.get("subscription_status", ""),
                "portalUrl": reverse("billing:create_portal_session", args=[workspace.key])
                if billing_limits.get("stripe_customer_id")
                else None,
                "cancelAtPeriodEnd": billing_limits.get("cancel_at_period_end", False),
                "currentPeriodEnd": billing_limits.get("next_billing_date", ""),
                "downgradeLimits": downgrade_limits,
                "billingPeriod": billing_limits.get("billing_period", "monthly"),
            },
        }
    )
