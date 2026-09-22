from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.services.product_page import build_product_page_context, update_product_page
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ProductDetailsPrivateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.product_details_public import ProductDetailsPublicView

            return ProductDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        result = build_product_page_context(request, product_id)
        if not result.ok:
            return error_response(request, HttpResponse(result.error, status=result.status_code or 400))
        template = {
            "product-content": "core/product_content.html.j2",
            "product-components": "core/product_components.html.j2",
        }.get(request.headers.get("HX-Target", ""), "core/product_details_private.html.j2")
        return render(request, template, result.value)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        result = update_product_page(request, product_id)
        if request.headers.get("HX-Request"):
            if not result.ok:
                return htmx_error_response(result.error or "Unable to update product")
            return htmx_success_response(result.value or "Product updated", triggers={"refresh-product": True})
        if result.ok:
            messages.success(request, result.value or "Product updated")
        else:
            messages.error(request, result.error or "Unable to update product")
        return redirect("core:product_details", product_id=product_id)
