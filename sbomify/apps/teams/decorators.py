from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden

from sbomify.apps.core.errors import error_response


def validate_role_in_url_team(allowed_roles: list[str]) -> Callable[..., Any]:
    """Require one of ``allowed_roles`` in the workspace named by the URL ``team_key``,
    checked against the database.

    This authorizes the workspace the request actually acts on, not the caller's *active*
    (session) workspace. Views that take a URL ``team_key`` must use this — trusting the
    session workspace lets an owner of workspace A act on workspace B. The DB lookup also
    avoids honouring a stale cached role in the session.
    """

    def _decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            from sbomify.apps.core.utils import token_to_number
            from sbomify.apps.teams.models import Member

            if not request.user.is_authenticated:
                return error_response(request, HttpResponseForbidden("Not logged in"))

            team_key = kwargs.get("team_key")
            if not team_key:
                return error_response(request, HttpResponseForbidden("No workspace specified"))

            try:
                team_id = token_to_number(team_key)
            except (ValueError, TypeError):
                return error_response(request, HttpResponseForbidden("Unknown workspace"))

            membership = Member.objects.filter(user=request.user, team_id=team_id).first()
            if membership is None or membership.role not in allowed_roles:
                return error_response(
                    request,
                    HttpResponseForbidden("You don't have sufficient permissions to access this workspace"),
                )

            return function(request, *args, **kwargs)  # type: ignore[no-any-return]

        return _wrapped_view

    return _decorator
