from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.forms import TeamGeneralSettingsForm
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import refresh_current_team_session


class TeamGeneralView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing workspace general settings (name)."""

    allowed_roles = ["owner"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        form = TeamGeneralSettingsForm(initial={"name": team.name})

        return render(
            request,
            "teams/team_general.html.j2",
            {
                "team": team,
                "form": form,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        form = TeamGeneralSettingsForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        new_name = form.cleaned_data["name"]

        # Update the team name directly
        try:
            team_obj = Team.objects.get(key=team_key)

            # Verify user is owner
            if not Member.objects.filter(user=request.user, team=team_obj, role="owner").exists():
                return htmx_error_response("Only owners can update workspace settings")

            team_obj.name = new_name
            team_obj.save(update_fields=["name"])

            # Update session to reflect the new name
            refresh_current_team_session(request, team_obj)

            return htmx_success_response(
                "Workspace settings updated successfully", triggers={"refreshTeamGeneral": True}
            )

        except Team.DoesNotExist:
            return htmx_error_response("Workspace not found")
        except Exception as e:
            return htmx_error_response(f"Failed to update workspace: {str(e)}")
