from django.contrib.auth.mixins import AccessMixin
from django.http import HttpResponseForbidden

from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.models import Member


class TeamRoleRequiredMixin(AccessMixin):
    allowed_roles: list[str] = []

    def dispatch(self, request, *args, **kwargs):
        # Check authentication first - let LoginRequiredMixin handle redirect if not authenticated
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        current_team = request.session.get("current_team", {})

        team_key = current_team.get("key", None)
        if team_key is None:
            return error_response(request, HttpResponseForbidden("You are not a member of any team"))

        try:
            Member.objects.get(user=request.user, team__key=team_key, role__in=self.allowed_roles)
        except Member.DoesNotExist:
            # Check if user has ANY membership in this team (just not the right role)
            has_any_membership = Member.objects.filter(user=request.user, team__key=team_key).exists()

            if has_any_membership:
                # User is a member but doesn't have the required role
                return error_response(
                    request, HttpResponseForbidden("You don't have sufficient permissions to access this page")
                )

            # User is not a member of this workspace at all - they may have been removed
            # Try to switch to another workspace they are a member of
            from sbomify.apps.teams.utils import recover_workspace_session

            return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)
