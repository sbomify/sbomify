"""Product custom metadata HTMX views."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import HtmxFragmentMixin, htmx_error_response
from sbomify.apps.core.services.product_custom_metadata import (
    build_custom_metadata_context,
    save_custom_metadata,
)
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ProductCustomMetadataView(HtmxFragmentMixin, GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Render and save a product's custom key/value metadata."""

    template_name = "core/components/product_custom_metadata_card.html.j2"

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        result = build_custom_metadata_context(request, product_id)
        if not result.ok:
            return htmx_error_response(result.error or "Product not found")
        return render(request, self.template_name, result.value)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        saved = save_custom_metadata(request, product_id)
        if not saved.ok:
            return htmx_error_response(saved.error or "Failed to save custom metadata")
        result = build_custom_metadata_context(request, product_id)
        if not result.ok:
            return htmx_error_response(result.error or "Product not found")
        return render(request, self.template_name, result.value)
