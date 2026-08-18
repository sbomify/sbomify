from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ComponentArtifactsView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Full-page listing of every artifact (SBOM, VEX, …) for a component.

    The component detail page shows only the latest artifact of each type; the
    "View all" link lands here, where the shared artifacts table is loaded with
    ``?full=1`` to render the complete history with search and pagination.
    """

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )
        # Page-header context per the design system contract: the title string
        # and breadcrumb trail are built here, not inline in the template.
        breadcrumb_items = [
            {"label": component["name"], "url": reverse("core:component_details", args=[component["id"]])},
            {"label": "Artifacts"},
        ]
        return render(
            request,
            "sboms/component_artifacts.html.j2",
            {
                "component": component,
                "page_title": f"{component['name']} artifacts",
                "breadcrumb_items": breadcrumb_items,
            },
        )
