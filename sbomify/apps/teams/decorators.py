from functools import wraps

from django.http import HttpResponseForbidden

from sbomify.apps.core.errors import error_response


def validate_role_in_current_team(allowed_roles):
    """
    Verify that a user is logged in and current logged in user has one of the given roles
    within the team.

    Args:
        allowed_roles: List of allowed roles (e.g., ['owner', 'admin'])

    Returns:
        Decorator function that checks user authentication and role permissions
    """

    def _decorator(function):
        @wraps(function)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return error_response(request, HttpResponseForbidden("Not logged in"))

            # Get current team from session
            current_team = request.session.get("current_team", {})
            team_key = current_team.get("key", None)

            if team_key is None:
                return error_response(request, HttpResponseForbidden("No current team selected"))

            # Get user teams from session
            user_teams = request.session.get("user_teams", {})

            if team_key not in user_teams:
                return error_response(request, HttpResponseForbidden("Unknown team"))

            # Check if user has the required role
            user_role = user_teams[team_key].get("role", "")
            if user_role not in allowed_roles:
                return error_response(
                    request,
                    HttpResponseForbidden("You don't have sufficient permissions to access this page"),
                )

            return function(request, *args, **kwargs)

        return _wrapped_view

    return _decorator
