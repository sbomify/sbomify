"""Template tags for team-related functionality."""

from django import template

from teams.utils import get_user_teams as get_teams_util

register = template.Library()


@register.simple_tag(takes_context=True)
def get_user_teams(context):
    """Get fresh user teams data directly from the database."""
    request = context["request"]

    if not request.user.is_authenticated:
        return {}

    # Get fresh team data directly from database (no caching)
    return get_teams_util(request.user)
