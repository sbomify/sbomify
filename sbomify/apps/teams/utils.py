"""Utility code used throughout the app"""

from collections import defaultdict

from django.contrib.auth import get_user_model

from sbomify.apps.billing.models import BillingPlan

from .models import Member, Team

User = get_user_model()


def get_user_teams(user) -> dict:
    """Get all teams for a user.

    Returns:
        A dictionary mapping team keys to team data
    """
    teams = defaultdict(dict)
    memberships = Member.objects.filter(user=user).select_related("team").all()

    for membership in memberships:
        teams[membership.team.key] = {
            "id": membership.team.id,
            "name": membership.team.name,
            "role": membership.role,
            "is_default_team": membership.is_default_team,
            "has_completed_wizard": membership.team.has_completed_wizard,
            "billing_plan": membership.team.billing_plan,
            "branding_info": membership.team.branding_info,
        }

    return dict(teams)


def get_user_default_team(user) -> int:
    """Get the user's default team ID. Returns the first team they're a member of."""
    try:
        default_team = Member.objects.get(user=user, is_default_team=True)
        return default_team.team_id
    except Member.DoesNotExist:
        return None


def can_add_user_to_team(team: Team) -> tuple[bool, str]:
    """
    Check if a team can add more users based on their billing plan limits.

    Args:
        team: The team to check

    Returns:
        Tuple of (can_add, error_message). If can_add is False, error_message contains the reason.
    """
    # If no billing plan, default to community limits (1 user = owner only)
    if not team.billing_plan:
        current_members = Member.objects.filter(team=team).count()
        if current_members >= 1:
            return (False, "Community plan allows only 1 user (owner). Please upgrade your plan to add more members.")
        return True, ""

    try:
        plan = BillingPlan.objects.get(key=team.billing_plan)

        # Enterprise plans have unlimited users
        if plan.allows_unlimited_users:
            return True, ""

        current_members = Member.objects.filter(team=team).count()

        if current_members >= plan.max_users:
            return (
                False,
                f"Your {plan.name} plan allows only {plan.max_users} users. "
                f"Please upgrade your plan to add more members.",
            )

        return True, ""

    except BillingPlan.DoesNotExist:
        # If plan doesn't exist, treat as community
        current_members = Member.objects.filter(team=team).count()
        if current_members >= 1:
            return (False, "Community plan allows only 1 user (owner). Please upgrade your plan to add more members.")
        return True, ""
