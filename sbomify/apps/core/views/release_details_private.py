from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from pydantic import ValidationError

from sbomify.apps.core.apis import get_release, set_release_lifecycle
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Release
from sbomify.apps.core.schemas import ReleaseLifecycleSchema
from sbomify.apps.core.services.release_lifecycle import supersession_links
from sbomify.apps.core.services.release_links import release_link_rows
from sbomify.apps.core.services.release_vulnerabilities import build_release_vulnerabilities
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

        current_team = request.session.get("current_workspace", {})

        # Page-header context per the design system contract: the copy chip and
        # breadcrumb trail are lists built here, and an empty editable type
        # renders the title read-only (the latest release cannot be renamed).
        can_edit_release = bool(release.get("has_crud_permissions")) and not release.get("is_latest")
        # Deleting asks owner or admin of the product's workspace, as the API does.
        from sbomify.apps.core.authz import can
        from sbomify.apps.core.models import Product

        product = Product.objects.select_related("team").get(pk=release["product"]["id"])
        can_delete_release = bool(can(request, "release:delete", product)) and not release.get("is_latest")
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
        vulnerabilities = build_release_vulnerabilities(request, release_id)
        lifecycle = {
            **supersession_links(release["id"]),
            # A release without dates of its own takes the product's, as tracked_releases() does.
            "end_of_support": release["end_of_support"] or product.end_of_support,
            "end_of_life": release["end_of_life"] or product.end_of_life,
            "withdrawn_reason": Release.WithdrawnReason(release["withdrawn_reason"]).label
            if release["withdrawn_reason"]
            else "",
            "withdrawn_reasons": Release.WithdrawnReason.choices,
            "can_manage": can_edit_release,
        }
        linked_releases = release_link_rows(
            Release.objects.select_related("product").get(pk=release["id"]),
            include_private=True,
            url_for=lambda linked: reverse("core:release_details", args=[linked.product_id, linked.id]),
        )

        return render(
            request,
            "core/release_details_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "release": release,
                "can_delete_release": can_delete_release,
                "header_editable_type": "release" if can_edit_release else "",
                "header_copy_values": header_copy_values,
                "breadcrumb_items": breadcrumb_items,
                "vulnerabilities": vulnerabilities.value if vulnerabilities.ok else None,
                "lifecycle": lifecycle,
                "linked_releases": linked_releases,
            },
        )


class ReleaseLifecycleView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Withdraw, archive or reactivate a release from its page, through the API's rules."""

    DONE = {
        "withdraw": "Release withdrawn. sbomify no longer monitors it.",
        "archive": "Release archived. sbomify no longer monitors it.",
        "reactivate": "Release reactivated.",
    }

    def post(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        action = request.POST.get("action", "")
        try:
            payload = ReleaseLifecycleSchema.model_validate(
                {"action": action, "reason": request.POST.get("reason", "") if action == "withdraw" else ""}
            )
        except ValidationError:
            messages.error(request, "Choose to withdraw, archive or reactivate the release.")
        else:
            status_code, result = set_release_lifecycle(request, release_id, payload)
            if status_code == 200:
                messages.success(request, self.DONE[payload.action])
            else:
                messages.error(request, result.get("detail") or "The release could not be changed.")
        return redirect("core:release_details", product_id=product_id, release_id=release_id)
