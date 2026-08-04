from __future__ import annotations

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View


class DesignSystemView(LoginRequiredMixin, View):
    """Local-development-only gallery showing every design-system component in a single view.

    The URL is only registered when DEBUG is on; this guard is defense in depth so the
    page can never render in production even if the route were exposed by mistake.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not settings.DEBUG:
            raise Http404
        context = {
            "team": request.session.get("current_team", {}),
            "demo_select_options": [
                {"value": "sbom", "label": "SBOM"},
                {"value": "document", "label": "Document"},
                {"value": "release", "label": "Release"},
            ],
            "demo_breadcrumbs": [
                {"label": "Products", "url": "#"},
                {"label": "Acme Widget", "url": "#"},
                {"label": "Releases"},
            ],
            "demo_tabs": [
                {"id": "overview", "label": "Overview", "icon": "fas fa-chart-line"},
                {"id": "sboms", "label": "SBOMs", "icon": "fas fa-file-code"},
                {"id": "documents", "label": "Documents", "icon": "fas fa-file-alt"},
            ],
            "demo_page_range": [1, 2, 3, "…", 8],
            "demo_dropdown_items": [
                {"label": "Edit", "icon": "fas fa-pen"},
                {"label": "Duplicate", "icon": "fas fa-copy"},
                {"divider": True},
                {"label": "Delete", "icon": "fas fa-trash", "danger": True},
            ],
            "demo_code": (
                'curl -X POST "$SBOMIFY_URL/api/v1/sboms" \\\n'
                '  -H "Authorization: Bearer $TOKEN" \\\n'
                '  -F "file=@bom.cdx.json"'
            ),
        }
        return render(request, "core/design_system.html.j2", context)
