"""Utility code used throughout the app"""

from .models import Member


def get_user_teams(user, include_team_id: bool = False) -> dict:
    user_memberships = Member.objects.filter(user=user).order_by("team__name").all()
    user_teams = {}

    for membership in user_memberships:
        user_teams[membership.team.key] = {
            "name": membership.team.name,
            "role": membership.role,
            "is_default_team": membership.is_default_team,
        }

        # We don't want it in session so by default it's not returned, but it's needed internally at some
        # places like the api for getting all items of a specific type that the current user has access to.
        if include_team_id:
            user_teams[membership.team.key]["team_id"] = membership.team_id

    return user_teams


def get_user_default_team(user) -> int:
    try:
        default_team = Member.objects.get(user=user, is_default_team=True)
        return default_team.team_id
    except Member.DoesNotExist:
        return None
