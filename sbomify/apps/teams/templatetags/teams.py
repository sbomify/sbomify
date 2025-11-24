from django import template

from sbomify.apps.teams.utils import get_user_teams

register = template.Library()


@register.filter
def workspace_display(name: str | None) -> str:
    """Display workspace names with a single `'s Workspace` suffix."""
    if not name:
        return "Workspace"

    trimmed = str(name).strip()
    normalized = trimmed.casefold()
    legacy_suffixes = ("'s workspace", "’s workspace")
    if any(normalized.endswith(suffix) for suffix in legacy_suffixes):
        return trimmed

    return f"{trimmed}'s Workspace"


@register.simple_tag
def current_member(members):
    if not members:
        return None
    return next((member for member in members if member.is_me), None)


@register.simple_tag(takes_context=True)
def user_workspaces(context):
    request = context.get("request")
    if not request or not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    user_teams = get_user_teams(request.user)
    if user_teams != request.session.get("user_teams"):
        request.session["user_teams"] = user_teams
        request.session.modified = True

    current_team = request.session.get("current_team") or {}
    current_key = current_team.get("key")
    if (not current_key or current_key not in user_teams) and user_teams:
        current_key = next(iter(user_teams))
        request.session["current_team"] = {"key": current_key, **user_teams[current_key]}
        request.session["current_team_key"] = current_key
        request.session.modified = True
    else:
        request.session["current_team_key"] = current_key

    context["current_workspace_key"] = current_key
    return user_teams
