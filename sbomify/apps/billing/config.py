from __future__ import annotations

from typing import Any

from django.conf import settings


def is_billing_enabled() -> bool:
    """Check if billing is enabled in the current environment."""
    return bool(getattr(settings, "BILLING", True))


def get_unlimited_plan_limits() -> dict[str, int | str | None]:
    """Get unlimited plan limits for when billing is disabled."""
    return {
        "max_products": None,
        "max_components": None,
        "subscription_status": "active",
    }


def needs_plan_selection(team: Any, user: Any) -> bool:
    """Check if a workspace still needs the owner to select a billing plan.

    Deliberately owner-only, even though admins can now *manage* billing
    (``billing:manage`` is the ``ADMINISTER`` tier). This is not a permission
    check — callers use it to force a redirect into the plan wizard
    (``core/views/__init__.py`` and ``core/views/dashboard.py``), so widening it
    would trap every admin of an un-onboarded workspace in the wizard instead of
    letting them reach the dashboard. Who is *prompted* to finish onboarding and
    who is *allowed* to change the plan are separate questions; the latter lives
    in ``require_billing_manager``.

    If *team* is None, falls back to the user's default team.
    """
    if not is_billing_enabled():
        return False

    from sbomify.apps.core.authz import OWNER_ONLY
    from sbomify.apps.teams.models import Member

    if team is None:
        member = Member.objects.filter(user=user, is_default_team=True).select_related("team").first()
        if not member or member.role not in OWNER_ONLY:
            return False
        return not member.team.has_selected_billing_plan

    if team.has_selected_billing_plan:
        return False

    return Member.objects.filter(user=user, team=team, role__in=OWNER_ONLY).exists()
