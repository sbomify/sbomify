from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import list_all_releases
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


def _get_releases_context(request: HttpRequest) -> dict | None:
    """Helper to get common context for releases views."""
    status_code, releases = list_all_releases(request, product_id=None, page=1, page_size=-1)
    if status_code != 200:
        return None

    # Sort releases by name (alphabetically) then by created_at (newest first)
    sorted_releases = sorted(
        releases.get("items", []),
        key=lambda r: (r["name"].lower(), -r["created_at"].timestamp() if r["created_at"] else 0),
    )

    return {
        "APP_BASE_URL": settings.APP_BASE_URL,
        "releases": sorted_releases,
    }


class ReleasesDashboardView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_releases_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load releases"))

        return render(request, "core/releases_dashboard.html.j2", context)


class ReleasesTableView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """View for HTMX table refresh."""

    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_releases_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load releases"))

        return render(request, "core/releases_table.html.j2", context)
