from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.teams.models import Member
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ValidateWorkspaceMixin:
    """Mixin that validates the user is still a member of their current workspace."""

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        current_team = request.session.get("current_team", {})
        team_key = current_team.get("key")

        if team_key:
            # Check if user is still a member of this workspace
            is_member = Member.objects.filter(user=request.user, team__key=team_key).exists()

            if not is_member:
                # User was removed from this workspace, recover their session
                from sbomify.apps.teams.utils import recover_workspace_session

                return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


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

        from django.utils import timezone

        from sbomify.apps.core.services.dashboard_page import build_dashboard_context, get_first_component

        hour = timezone.localtime().hour
        daypart = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        greeting = f"Good {daypart}"
        first_name = getattr(request.user, "first_name", "")
        if first_name:
            greeting += f", {first_name}"

        dashboard = build_dashboard_context(team.id) if team else {"is_first_visit": True}
        # Built here rather than in the template: it names the workspace, and the
        # page header takes its subtitle as one string.
        if dashboard.get("is_first_visit"):
            subtitle = "Let's get your first component reporting."
        else:
            subtitle = f"The security picture across {current_team.get('name', 'your workspace')}."

        context = {
            "current_team": current_team,
            "has_crud_permissions": has_crud_permissions,
            "greeting": greeting,
            "page_subtitle": subtitle,
            "dashboard": dashboard,
        }

        # The hero is one Get-started action, not a checklist — the wizard
        # command sets a repository up end to end. The only per-request lookup
        # left is whether a component exists yet, which gates the
        # upload-a-file alternative (an upload needs somewhere to land).
        if team and context["dashboard"].get("is_first_visit"):
            context["onboarding"] = {
                "first_component": get_first_component(team.id),
            }

        return render(request, "core/dashboard.html.j2", context)
