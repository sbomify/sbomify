from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.teams.models import Member
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


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


class DashboardView(GuestAccessBlockedMixin, ValidateWorkspaceMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})

        if not current_team.get("has_completed_wizard", True):
            return redirect("teams:onboarding_wizard")

        from sbomify.apps.billing.config import needs_plan_selection
        from sbomify.apps.teams.models import Team

        team = None
        team_key = current_team.get("key")
        if team_key:
            team = Team.objects.filter(key=team_key).first()

        if needs_plan_selection(team, request.user):
            return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")

        has_crud_permissions = current_team.get("role") in ["owner", "admin"]

        context = {
            "current_team": current_team,
            "has_crud_permissions": has_crud_permissions,
        }

        return render(request, "core/dashboard.html.j2", context)
