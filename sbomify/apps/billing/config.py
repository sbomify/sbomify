from django.conf import settings


def is_billing_enabled() -> bool:
    """Check if billing is enabled in the current environment."""
    return getattr(settings, "BILLING", True)


def get_unlimited_plan_limits() -> dict:
    """Get unlimited plan limits for when billing is disabled."""
    return {
        "max_products": None,
        "max_projects": None,
        "max_components": None,
        "subscription_status": "active",
    }


def needs_plan_selection(team, user) -> bool:
    """Check if a workspace still needs the owner to select a billing plan.

    Returns True only when billing is enabled, the team hasn't selected a plan,
    and the given user is an owner of that team.

    If *team* is None, falls back to the user's default team.
    """
    if not is_billing_enabled():
        return False

    from sbomify.apps.teams.models import Member

    if team is None:
        member = Member.objects.filter(user=user, is_default_team=True).select_related("team").first()
        if not member or member.role != "owner":
            return False
        return not member.team.has_selected_billing_plan

    if team.has_selected_billing_plan:
        return False

    return Member.objects.filter(user=user, team=team, role="owner").exists()
