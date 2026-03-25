from __future__ import annotations

from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.controls.models import Control
from sbomify.apps.controls.services.catalog_service import activate_builtin_catalog, delete_catalog, get_active_catalogs
from sbomify.apps.controls.services.status_service import get_controls_detail, upsert_status
from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.logging import getLogger

logger = getLogger(__name__)


class ControlsCatalogView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle activate/deactivate catalog POST actions."""

    allowed_roles = ["owner", "admin"]

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.teams.utils import redirect_to_team_settings

        action = request.POST.get("controls_catalog_action", "")

        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return redirect_to_team_settings(team_key, "controls")

        if action == "activate":
            activate_result = activate_builtin_catalog(team, "soc2-type2")
            if activate_result.ok and activate_result.value is not None:
                catalog = activate_result.value
                ctrl_count = catalog.controls.count()
                messages.success(request, f"Activated {catalog.name} catalog with {ctrl_count} controls.")
            else:
                messages.error(request, activate_result.error or "Failed to activate catalog")

        elif action == "deactivate":
            catalog_id = request.POST.get("catalog_id", "")
            if not catalog_id:
                messages.error(request, "No catalog specified")
                return redirect_to_team_settings(team_key, "controls")

            deactivate_result = delete_catalog(catalog_id, team)
            if deactivate_result.ok:
                messages.success(request, "Catalog deactivated and all controls removed.")
            else:
                messages.error(request, deactivate_result.error or "Failed to deactivate catalog")
        else:
            messages.error(request, "Invalid action")

        return redirect_to_team_settings(team_key, "controls")


class ControlsStatusView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle individual control status update POST (HTMX inline)."""

    allowed_roles = ["owner", "admin"]

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from django.shortcuts import render

        from sbomify.apps.teams.apis import get_team
        from sbomify.apps.teams.utils import redirect_to_team_settings

        user = cast(User, request.user)
        control_id = request.POST.get("control_id", "")
        status = request.POST.get("status", "")

        if not control_id or not status:
            messages.error(request, "Missing control or status")
            return redirect_to_team_settings(team_key, "controls")

        try:
            control = Control.objects.get(id=control_id)
        except Control.DoesNotExist:
            messages.error(request, "Control not found")
            return redirect_to_team_settings(team_key, "controls")

        upsert_result = upsert_status(control, None, status, user)  # type: ignore[arg-type]
        if not upsert_result.ok:
            messages.error(request, upsert_result.error or "Failed to update status")
            return redirect_to_team_settings(team_key, "controls")

        # For HTMX requests, return the updated controls table partial
        if request.headers.get("HX-Request"):
            try:
                team = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                messages.error(request, "Workspace not found")
                return redirect_to_team_settings(team_key, "controls")

            catalogs_result = get_active_catalogs(team)
            catalog = catalogs_result.value[0] if catalogs_result.ok and catalogs_result.value else None

            controls_categories: list[dict[str, Any]] = []
            if catalog:
                detail_result = get_controls_detail(catalog)
                if detail_result.ok and detail_result.value is not None:
                    controls_categories = detail_result.value

            # Get team data for template context
            resp_code, team_data = get_team(request, team_key)
            if resp_code != 200:
                return redirect_to_team_settings(team_key, "controls")

            try:
                team_dict = team_data.dict() if hasattr(team_data, "dict") else team_data.model_dump()
            except AttributeError:
                team_dict = team_data

            return render(
                request,
                "controls/controls_table.html.j2",
                {
                    "team": team_dict,
                    "controls_catalog": catalog,
                    "controls_categories": controls_categories,
                },
            )

        messages.success(request, "Control status updated.")
        return redirect_to_team_settings(team_key, "controls")
