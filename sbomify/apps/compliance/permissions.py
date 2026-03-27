"""Billing and role checks for CRA Compliance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team


def check_cra_access(team: Team | None = None, *, billing_plan_key: str | None = None) -> bool:
    """Returns True if team has Business+ plan (or billing disabled).

    Pure key check — no DB query. Can be called with either a Team object
    or a billing_plan_key string from the session.
    """
    if not is_billing_enabled():
        return True
    raw_key = billing_plan_key or (team.billing_plan if team else None)
    if not raw_key:
        return False
    return raw_key.strip().lower() in BillingPlan.CRA_ELIGIBLE_PLAN_KEYS
