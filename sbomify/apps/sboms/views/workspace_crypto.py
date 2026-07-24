from __future__ import annotations

from typing import cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.sboms.services.crypto_dashboard import build_workspace_crypto_rollup
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class WorkspaceCryptoView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Workspace crypto readiness dashboard: one row per component with its
    PQC verdict, vulnerable-algorithm distribution, and certificate posture,
    aggregated from persisted assessment runs (no artifact reads)."""

    template_name = "sboms/workspace_crypto.html.j2"

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            team_id = token_to_number(team_key)
            team = Team.objects.get(pk=team_id)
        except (ValueError, Team.DoesNotExist):
            return error_response(request, HttpResponseNotFound("Workspace not found"))

        # Role check runs against the URL workspace, not the session's current
        # team: GuestAccessBlockedMixin only inspects the session, so a guest
        # of THIS workspace whose session points elsewhere would pass it.
        if not Member.objects.filter(user=cast(User, request.user), team=team).exclude(role="guest").exists():
            return error_response(request, HttpResponseForbidden("Access denied"))

        rollup = build_workspace_crypto_rollup(team_id)
        return render(request, self.template_name, {"team": team, "rollup": rollup})
