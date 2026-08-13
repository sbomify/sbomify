from __future__ import annotations

from typing import cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.sboms.services.hardware_dashboard import build_workspace_hardware_rollup
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class WorkspaceHardwareView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Workspace hardware rollup: parts across every hardware-bearing
    artifact, grouped by manufacturer and part name, with the parts more than
    one product depends on flagged — the supply-chain concentration signal."""

    template_name = "sboms/workspace_hardware.html.j2"

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            team_id = token_to_number(team_key)
            team = Team.objects.get(pk=team_id)
        except (ValueError, Team.DoesNotExist):
            return error_response(request, HttpResponseNotFound("Workspace not found"))

        # Role check runs against the URL workspace, not the session's current
        # team — same reasoning as the crypto dashboard beside this.
        if not Member.objects.filter(user=cast(User, request.user), team=team).exclude(role="guest").exists():
            return error_response(request, HttpResponseForbidden("Access denied"))

        rollup = build_workspace_hardware_rollup(team_id)
        return render(request, self.template_name, {"team": team, "rollup": rollup})
