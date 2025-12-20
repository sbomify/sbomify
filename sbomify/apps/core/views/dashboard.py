from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.teams.models import Member


class ValidateWorkspaceMixin:
    """Mixin that validates the user is still a member of their current workspace."""

    def dispatch(self, request, *args, **kwargs):
        current_team = request.session.get("current_team", {})
        team_key = current_team.get("key")

        if team_key:
            # Check if user is still a member of this workspace
            is_member = Member.objects.filter(user=request.user, team__key=team_key).exists()

            if not is_member:
                # User was removed from this workspace, recover their session
                from sbomify.apps.teams.utils import recover_workspace_session

                return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)


class DashboardView(ValidateWorkspaceMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "core/dashboard.html.j2", {})
