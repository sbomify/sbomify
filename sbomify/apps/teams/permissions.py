from django.contrib.auth.mixins import AccessMixin
from django.http import HttpResponseForbidden

from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.models import Member


class TeamRoleRequiredMixin(AccessMixin):
    allowed_roles: list[str] = []

    def dispatch(self, request, *args, **kwargs):
        current_team = request.session.get("current_team", {})

        team_key = current_team.get("key", None)
        if team_key is None:
            return error_response(request, HttpResponseForbidden("You are not a member of any team"))

        try:
            Member.objects.get(user=request.user, team__key=team_key, role__in=self.allowed_roles)
        except Member.DoesNotExist:
            return error_response(
                request, HttpResponseForbidden("You don't have sufficient permissions to access this page")
            )

        return super().dispatch(request, *args, **kwargs)
