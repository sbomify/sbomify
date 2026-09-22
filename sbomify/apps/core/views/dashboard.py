from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key


class ValidateWorkspaceMixin:
    """Mixin that validates the user is still a member of their current workspace."""

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        current_team = request.session.get("current_team", {})
        team_key = current_team.get("key")

        if team_key:
            # Check if user is still a member of this workspace
            is_member = get_member_role_by_key(request.user, team_key) is not None

            if not is_member:
                # User was removed from this workspace, recover their session
                from sbomify.apps.teams.utils import recover_workspace_session

                return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class DashboardView(GuestAccessBlockedMixin, ValidateWorkspaceMixin, LoginRequiredMixin, View):
    show_trends: bool = False

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})

        if not current_team.get("has_completed_wizard", True):
            return redirect("teams:onboarding_wizard")

        from sbomify.apps.billing.config import needs_plan_selection
        from sbomify.apps.core.services.dashboard_page import get_dashboard_workspace

        workspace_result = get_dashboard_workspace(current_team.get("key"))
        if not workspace_result.ok:
            return HttpResponse(workspace_result.error, status=workspace_result.status_code or 400)
        team = workspace_result.value

        if needs_plan_selection(team, request.user):
            return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")

        if self.show_trends:
            return render(request, "core/dashboard_trends.html.j2")

        from sbomify.apps.core.services.dashboard_page import build_dashboard_context, get_first_component

        result = build_dashboard_context(team.id) if team else None
        if result is not None and not result.ok:
            return HttpResponse(result.error, status=result.status_code or 400)
        dashboard = result.value if result and result.value else {"is_first_visit": True}
        subtitle = "Prioritise vulnerabilities and keep your product evidence current."
        if dashboard.get("is_first_visit"):
            subtitle = "Your workspace at a glance. Add your first artifact to start tracking exposure."

        context = {
            "current_team": current_team,
            "page_subtitle": subtitle,
            "dashboard": dashboard,
        }

        # The hero is one Get-started action, not a checklist — the wizard
        # command sets a repository up end to end. The only per-request lookup
        # left is whether a component exists yet, which gates the
        # upload-a-file alternative (an upload needs somewhere to land).
        if team and context["dashboard"].get("is_first_visit"):
            context["onboarding"] = {
                "first_component": get_first_component(team.id).value,
            }

        return render(request, "core/dashboard.html.j2", context)
