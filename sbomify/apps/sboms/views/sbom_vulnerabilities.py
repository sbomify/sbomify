from __future__ import annotations

from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponsePermanentRedirect
from django.urls import reverse
from django.views import View

from sbomify.apps.core.authz import can
from sbomify.apps.core.errors import error_response
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class SbomVulnerabilitiesView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The old per-SBOM report. The workspace page now shows one SBOM through its version filter."""

    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        sbom = SBOM.objects.select_related("component__team").filter(pk=sbom_id).first()
        # The same answer for a missing SBOM and one this reader may not see:
        # the redirect names the workspace key and component id.
        if sbom is None or not can(request, "sbom:read", sbom):
            return error_response(request, HttpResponseNotFound("SBOM not found"))
        url = reverse("vulnerability_scanning:vulnerability_scans", args=[sbom.component.team.key])
        return HttpResponsePermanentRedirect(f"{url}?{urlencode({'component': sbom.component_id, 'version': sbom.id})}")
