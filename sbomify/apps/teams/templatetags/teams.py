from datetime import datetime, timedelta

from django import template
from django.utils import timezone

from sbomify.apps.teams.utils import update_user_teams_session

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

    user_teams = request.session.get("user_teams")
    last_checked_raw = request.session.get("user_teams_checked_at")
    last_checked = None
    if last_checked_raw:
        try:
            last_checked = datetime.fromisoformat(last_checked_raw)
            if timezone.is_naive(last_checked):
                last_checked = timezone.make_aware(last_checked, timezone.get_current_timezone())
        except ValueError:
            last_checked = None

    ttl_seconds = 300
    needs_refresh = (
        not user_teams
        or not request.session.get("user_teams_version")
        or not last_checked
        or (timezone.now() - last_checked) > timedelta(seconds=ttl_seconds)
    )

    if needs_refresh:
        user_teams = update_user_teams_session(request, request.user)

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
