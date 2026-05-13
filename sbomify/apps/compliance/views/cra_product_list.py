"""CRA product list view — sidebar entry point."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.compliance.permissions import check_cra_access
from sbomify.apps.core.utils import get_team_id_from_session
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin


class CRAProductListView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """List products with CRA assessments for the current team.

    TeamRoleRequiredMixin enforces that a workspace is selected and the
    user has owner/admin role before get() is reached.
    """

    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})
        team_id = get_team_id_from_session(request)

        # Use session billing plan key — no Team DB query needed
        billing_plan = current_team.get("billing_plan")
        has_access = check_cra_access(billing_plan_key=billing_plan)

        if not has_access:
            return render(
                request,
                "compliance/cra_product_list.html.j2",
                {"assessments": [], "has_cra_access": False, "current_team": current_team},
            )

        from sbomify.apps.compliance.services.wizard_service import get_assessment_list_for_team

        assert team_id is not None  # guaranteed by TeamRoleRequiredMixin
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
