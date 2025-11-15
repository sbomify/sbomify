from django.contrib.auth.mixins import  AccessMixin
from django.http import HttpResponseForbidden

from sbomify.apps.core.errors import error_response


class TeamRoleRequiredMixin(AccessMixin):
    allowed_roles: list[str] = []

    def dispatch(self, request, *args, **kwargs):
        current_team = request.session.get("current_team", {})

        team_key = current_team.get("key", None)
        if team_key is None:
            return error_response(request, HttpResponseForbidden("No current team selected"))

        user_teams = request.session.get("user_teams", {})
        if team_key not in user_teams:
            return error_response(request, HttpResponseForbidden("Unknown team"))

        user_role = user_teams[team_key].get("role", "")
        if user_role not in self.allowed_roles:
            return error_response(
                request,
                HttpResponseForbidden("You don't have sufficient permissions to access this page"),
            )

        return super().dispatch(request, *args, **kwargs)
