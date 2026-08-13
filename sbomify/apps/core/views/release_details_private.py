from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
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

        from sbomify.apps.core.models import Release

        sibling_releases = list(
            Release.objects.filter(product_id=product_id, product__team_id=current_team.get("id"))
            .exclude(id=release_id)
            .order_by("-created_at")
        )

        return render(
            request,
            "core/release_details_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "release": release,
                "sibling_releases": sibling_releases,
            },
        )


class ReleaseDiffView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """What changed between two releases of a product."""

    def get(self, request: HttpRequest, product_id: str, release_id: str, other_release_id: str) -> HttpResponse:
        from sbomify.apps.core.services.release_diff import build_diff_page_context
        from sbomify.apps.teams.models import Team

        team_id = request.session.get("current_team", {}).get("id")
        team = Team.objects.filter(id=team_id).first() if team_id else None
        if team is None:
            return error_response(request, HttpResponse(status=403, content="No workspace context"))

        result = build_diff_page_context(team, product_id, release_id, other_release_id)
        if not result.ok:
            return error_response(
                request, HttpResponse(status=result.status_code or 400, content=result.error or "Diff failed")
            )

        context = dict(result.value or {})
        context["APP_BASE_URL"] = settings.APP_BASE_URL
        context["current_team"] = request.session.get("current_team", {})
        return render(request, "core/release_diff.html.j2", context)
