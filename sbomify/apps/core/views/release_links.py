"""The "Ships with" card on the release page: link and unlink other products' releases."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import HtmxFragmentMixin, htmx_error_response
from sbomify.apps.core.services.release_links_card import build_release_links_context, handle_release_links_action
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ReleaseLinksView(HtmxFragmentMixin, GuestAccessBlockedMixin, LoginRequiredMixin, View):
    template_name = "core/components/release_links_card.html.j2"

    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        result = build_release_links_context(request, release_id)
        if not result.ok:
            return htmx_error_response(result.error or "Release not found")
        return render(request, self.template_name, result.value)

    def post(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        action = handle_release_links_action(request, release_id)
        if not action.ok:
            return htmx_error_response(action.error or "Failed to update linked releases")
        result = build_release_links_context(request, release_id)
        if not result.ok:
            return htmx_error_response(result.error or "Release not found")
        return render(request, self.template_name, result.value)
