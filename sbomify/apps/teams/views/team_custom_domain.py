from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import get_app_hostname, plan_has_custom_domain_access


class TeamCustomDomainView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing workspace custom domain settings."""

    allowed_roles = ["owner"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        has_custom_domain_access = plan_has_custom_domain_access(team.billing_plan)
        app_hostname = get_app_hostname()

        return render(
            request,
            "teams/team_custom_domain.html.j2",
            {
                "team": team,
                "has_custom_domain_access": has_custom_domain_access,
                "app_hostname": app_hostname,
            },
        )
