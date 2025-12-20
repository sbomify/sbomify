from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import (
    get_team,
    get_team_branding,
    update_team_branding,
)
from sbomify.apps.teams.forms import TeamBrandingForm
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.schemas import UpdateTeamBrandingSchema


class TeamBrandingView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        status_code, branding_info = get_team_branding(request, team_key)
        if status_code != 200:
            return htmx_error_response(branding_info.get("detail", "Failed to load branding"))

        return render(
            request,
            "teams/team_branding.html.j2",
            {
                "team": team,
                "branding_info": branding_info,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        status_code, branding_info = get_team_branding(request, team_key)
        if status_code != 200:
            return htmx_error_response(branding_info.get("detail", "Failed to load branding"))

        form = TeamBrandingForm(request.POST, request.FILES)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        payload = UpdateTeamBrandingSchema(
            brand_color=form.cleaned_data.get("brand_color"),
            accent_color=form.cleaned_data.get("accent_color"),
            branding_enabled=form.cleaned_data.get("branding_enabled"),
            icon_pending_deletion=form.cleaned_data.get("icon_pending_deletion", False),
            logo_pending_deletion=form.cleaned_data.get("logo_pending_deletion", False),
        )
        status_code, result = update_team_branding(request, team_key, payload)
        if status_code != 200:
            return htmx_error_response(result.get("detail", "Failed to update branding"))

        return htmx_success_response("Branding updated successfully", triggers={"refreshTeamBranding": True})
