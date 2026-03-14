"""CRA product list view — sidebar entry point."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.compliance.permissions import check_cra_access
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin


class CRAProductListView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """List products with CRA assessments for the current team."""

    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})
        team_id = current_team.get("id")

        empty_ctx = {"assessments": [], "has_cra_access": False, "current_team": current_team}

        if not team_id:
            return render(request, "compliance/cra_product_list.html.j2", empty_ctx)

        from sbomify.apps.teams.models import Team

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            return render(request, "compliance/cra_product_list.html.j2", empty_ctx)

        has_access = check_cra_access(team)

        # Short-circuit: don't fetch assessments if team lacks CRA access
        if not has_access:
            return render(
                request,
                "compliance/cra_product_list.html.j2",
                {"assessments": [], "has_cra_access": False, "current_team": current_team},
            )

        from sbomify.apps.compliance.services.wizard_service import get_assessment_list_for_team

        result = get_assessment_list_for_team(team_id)

        return render(
            request,
            "compliance/cra_product_list.html.j2",
            {
                "assessments": result.value if result.ok else [],
                "has_cra_access": has_access,
                "current_team": current_team,
            },
        )
