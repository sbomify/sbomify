from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponsePermanentRedirect
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.vulnerability_scanning.services.workspace_vulnerabilities import resolve_sbom_vulnerabilities_url


class SbomVulnerabilitiesView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The old per-SBOM report. The workspace page now shows one SBOM through its version filter."""

    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        result = resolve_sbom_vulnerabilities_url(request, sbom_id)
        if not result.ok or result.value is None:
            return error_response(request, HttpResponseNotFound(result.error or "SBOM not found"))
        return HttpResponsePermanentRedirect(result.value)
