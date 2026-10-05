from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.sboms.services.vulnerability_report import build_sbom_vulnerabilities
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class SbomVulnerabilitiesView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        result = build_sbom_vulnerabilities(request, sbom_id)
        if not result.ok:
            return error_response(request, HttpResponse(result.error, status=result.status_code or 400))
        template = (
            "sboms/components/scan_vulnerabilities.html.j2"
            if request.headers.get("HX-Target") == "scan-vulnerabilities"
            else "sboms/sbom_vulnerabilities.html.j2"
        )
        return render(request, template, result.value)
