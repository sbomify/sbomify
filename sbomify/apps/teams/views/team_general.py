import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.forms import TeamGeneralSettingsForm
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import refresh_current_team_session

logger = logging.getLogger(__name__)


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

        # Update the team name with atomicity using select_for_update
        # Note: Owner permission is already enforced by TeamRoleRequiredMixin
        # Note: get_team() above already validated the team exists and user has access
        try:
            from django.db import transaction

            with transaction.atomic():
                team_obj = Team.objects.select_for_update().get(key=team_key)
                team_obj.name = new_name
                team_obj.save(update_fields=["name"])

            refresh_current_team_session(request, team_obj)

            return htmx_success_response(
                "Workspace settings updated successfully", triggers={"refreshTeamGeneral": True}
            )

        except Team.DoesNotExist:
            return htmx_error_response("Workspace not found")
        except Exception:
            logger.exception("Failed to update workspace name for team_key=%s", team_key)
            return htmx_error_response("Failed to update workspace. Please try again.")
