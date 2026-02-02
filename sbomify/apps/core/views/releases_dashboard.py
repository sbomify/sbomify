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

    # Compute stats for dashboard
    public_count = sum(1 for r in sorted_releases if r.get("is_public"))
    private_count = len(sorted_releases) - public_count

    # Serialize releases for JSON (Alpine.js table)
    releases_json = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r.get("description", ""),
            "product_id": r.get("product_id"),
            "product_name": r.get("product_name", ""),
            "is_latest": r.get("is_latest", False),
            "is_prerelease": r.get("is_prerelease", False),
            "is_public": r.get("is_public", False),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "released_at": r["released_at"].isoformat() if r.get("released_at") else None,
            "artifacts_count": r.get("artifacts_count", 0),
            "has_sboms": r.get("has_sboms", False),
        }
        for r in sorted_releases
    ]

    return {
        "APP_BASE_URL": settings.APP_BASE_URL,
        "releases": releases_json,
        "releases_count": len(sorted_releases),
        "public_count": public_count,
        "private_count": private_count,
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
