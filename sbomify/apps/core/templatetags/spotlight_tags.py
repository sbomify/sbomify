"""Preload search suggestions so focusing the field never waits for a request."""

from django import template
from django.http import HttpRequest

from sbomify.apps.core.spotlight import initial_suggestions
from sbomify.apps.teams.queries import get_member_role_by_key

register = template.Library()


@register.simple_tag
def search_suggestions(request: HttpRequest | None) -> list[dict[str, str]]:
    if not request or not request.user.is_authenticated:
        return []
    workspace_key = (request.session.get("current_team") or {}).get("key", "")
    return initial_suggestions(
        role=get_member_role_by_key(request.user, workspace_key) or "", workspace_key=workspace_key
    )
