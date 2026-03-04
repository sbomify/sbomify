"""Billing and role checks for CRA Compliance."""

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Team


def check_cra_access(team: Team) -> bool:
    """Returns True if team has Business+ plan (or billing disabled)."""
    if not is_billing_enabled():
        return True
    plan = BillingPlan.objects.filter(key=team.billing_plan).first()
    if plan is None:
        return False
    return plan.has_cra_compliance
