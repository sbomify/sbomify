"""Recurring revenue, derived from plan list prices.

This is an estimate and says so on the page. ``BillingPlan.monthly_price`` and
``annual_price`` are documented in the model as display values that must match
Stripe, not as invoiced amounts, and enterprise agreements can be priced per
contract with no price on the plan at all. Reading real numbers means reading
Stripe, which is a later step; what this gives you today is a figure that moves
when the customer base moves, plus an honest count of what it could not price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.services.workspace_status import paying_workspaces

MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class RecurringRevenue:
    """Monthly recurring revenue and the confidence attached to it."""

    mrr: Decimal
    """Sum of the monthly-equivalent list price of every paying workspace."""

    priced_workspaces: int
    """Paying workspaces whose plan carries a price for their billing period."""

    unpriced_workspaces: int
    """Paying workspaces contributing nothing, because their plan has no price.

    Almost always enterprise on a negotiated contract. Shown next to the MRR
    so a large number here is visible rather than silently missing revenue.
    """

    @property
    def arr(self) -> Decimal:
        return self.mrr * MONTHS_PER_YEAR


def _monthly_equivalent(plan: BillingPlan, billing_period: str) -> Decimal | None:
    """Price of one month on this plan, or None if the plan has no price.

    An annual subscription is divided rather than counted in the month it is
    billed, so a year of annual customers reads as a flat line instead of
    twelve spikes.
    """
    if billing_period == "annual":
        if plan.annual_price is None:
            return None
        return Decimal(plan.annual_price) / MONTHS_PER_YEAR
    if plan.monthly_price is None:
        return None
    return Decimal(plan.monthly_price)


def recurring_revenue() -> RecurringRevenue:
    """Monthly recurring revenue across every paying workspace."""
    plans = {plan.key: plan for plan in BillingPlan.objects.all() if plan.key}

    mrr = Decimal("0")
    priced = 0
    unpriced = 0

    for workspace in paying_workspaces().only("billing_plan", "billing_plan_limits"):
        plan = plans.get(workspace.billing_plan or "")
        limits = workspace.billing_plan_limits or {}
        amount = _monthly_equivalent(plan, limits.get("billing_period") or "monthly") if plan else None
        if amount is None:
            unpriced += 1
            continue
        mrr += amount
        priced += 1

    return RecurringRevenue(
        mrr=mrr.quantize(Decimal("0.01")),
        priced_workspaces=priced,
        unpriced_workspaces=unpriced,
    )
