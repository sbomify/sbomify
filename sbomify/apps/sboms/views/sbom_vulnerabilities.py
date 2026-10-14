from __future__ import annotations

from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponsePermanentRedirect
from django.urls import reverse
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class SbomVulnerabilitiesView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The old per-SBOM report. The workspace page now shows one SBOM through its version filter."""

    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        sbom = SBOM.objects.filter(pk=sbom_id).values("id", "component_id", "component__team__key").first()
        if sbom is None:
            return error_response(request, HttpResponseNotFound("SBOM not found"))
        url = reverse("vulnerability_scanning:vulnerability_scans", args=[sbom["component__team__key"]])
        return HttpResponsePermanentRedirect(
            f"{url}?{urlencode({'component': sbom['component_id'], 'version': sbom['id']})}"
        )
