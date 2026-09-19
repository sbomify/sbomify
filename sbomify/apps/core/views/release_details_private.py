from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_release
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ReleaseDetailsPrivateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.release_details_public import ReleaseDetailsPublicView

            return ReleaseDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        status_code, release = get_release(request, release_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=release.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})

        from sbomify.apps.core.services.release_diff import sibling_releases_for

        sibling_releases = sibling_releases_for(current_team.get("id"), product_id, exclude_release_id=release_id)

        # Page-header context per the design system contract: the copy chip and
        # breadcrumb trail are lists built here, and an empty editable type
        # renders the title read-only (the latest release cannot be renamed).
        can_edit_release = bool(release.get("has_crud_permissions")) and not release.get("is_latest")
        header_copy_values = [
            {"value": release["id"], "title": f"Release ID: {release['id']} (click to copy)"},
        ]
        breadcrumb_items = [
            {
                "label": release["product"]["name"],
                "url": reverse("core:product_details", args=[release["product"]["id"]]),
            },
            {"label": release["name"]},
        ]

        return render(
            request,
            "core/release_details_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "release": release,
                "sibling_releases": sibling_releases,
                "header_editable_type": "release" if can_edit_release else "",
                "header_copy_values": header_copy_values,
                "breadcrumb_items": breadcrumb_items,
            },
        )


class ReleaseDiffView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """What changed between two releases of a product."""

    def get(self, request: HttpRequest, product_id: str, release_id: str, other_release_id: str) -> HttpResponse:
        from sbomify.apps.core.authz import can
        from sbomify.apps.core.services.release_diff import build_diff_page_context
        from sbomify.apps.teams.models import Team

        team_id = request.session.get("current_team", {}).get("id")
        team = Team.objects.filter(id=team_id).first() if team_id else None
        if team is None:
            return error_response(request, HttpResponse(status=403, content="No workspace context"))
        # The session names the workspace; can() decides whether this user may
        # still read it — a stale session must not keep exposing diff data.
        if not can(request, "workspace:read", team):
            return error_response(request, HttpResponse(status=403, content="Forbidden"))

        result = build_diff_page_context(team, product_id, release_id, other_release_id)
        if not result.ok:
            return error_response(
                request, HttpResponse(status=result.status_code or 400, content=result.error or "Diff failed")
            )

        context = dict(result.value or {})
        context["APP_BASE_URL"] = settings.APP_BASE_URL
        context["current_team"] = request.session.get("current_team", {})
        return render(request, "core/release_diff.html.j2", context)
