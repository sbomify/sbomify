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

        from sbomify.apps.core.services.dashboard_page import build_dashboard_context

        hour = timezone.localtime().hour
        daypart = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        greeting = f"Good {daypart}"
        first_name = getattr(request.user, "first_name", "")
        if first_name:
            greeting += f", {first_name}"

        context = {
            "current_team": current_team,
            "has_crud_permissions": has_crud_permissions,
            "greeting": greeting,
            "dashboard": build_dashboard_context(team.id) if team else {"is_first_visit": True},
        }

        # Onboarding checklist progress — computed uncached so it reflects a newly
        # created product/component immediately (the dashboard digest is cached).
        if team and context["dashboard"].get("is_first_visit"):
            from sbomify.apps.core.models import Component, Product

            first_component = Component.objects.filter(team_id=team.id).first()
            has_product = Product.objects.filter(team_id=team.id).exists()
            context["onboarding"] = {
                "has_product": has_product,
                "has_component": first_component is not None,
                "first_component": first_component,
                "first_component_id": first_component.id if first_component else None,
                "done_count": (1 if has_product else 0) + (1 if first_component else 0),
            }

        return render(request, "core/dashboard.html.j2", context)
