from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from sbomify.apps.core.apis import create_release
from sbomify.apps.core.schemas import ReleaseCreateSchema
from sbomify.apps.core.services.product_page import build_product_releases_context
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ProductReleasesPrivateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.product_releases_public import ProductReleasesPublicView

            return ProductReleasesPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        result = build_product_releases_context(request, product_id)
        if not result.ok:
            return HttpResponse(result.error, status=result.status_code or 400)
        partial = request.headers.get("HX-Target") == "product-releases-content"
        template = "core/product_releases_content.html.j2" if partial else "core/product_releases_private.html.j2"
        return render(request, template, result.value)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        created_at_input = request.POST.get("created_at", "").strip()
        released_at_input = request.POST.get("released_at", "").strip()

        created_at = None
        if created_at_input:
            parsed_created_at = parse_datetime(created_at_input)
            if parsed_created_at:
                if timezone.is_naive(parsed_created_at):
                    parsed_created_at = timezone.make_aware(parsed_created_at, timezone.get_current_timezone())
                created_at = parsed_created_at

        released_at = None
        if released_at_input:
            parsed_released_at = parse_datetime(released_at_input)
            if parsed_released_at:
                if timezone.is_naive(parsed_released_at):
                    parsed_released_at = timezone.make_aware(parsed_released_at, timezone.get_current_timezone())
                released_at = parsed_released_at

        if released_at is None and created_at is not None:
            released_at = created_at

        payload = ReleaseCreateSchema(
            name=name,
            description=description,
            product_id=product_id,
            is_prerelease=False,
            created_at=created_at,
            released_at=released_at,
        )

        status_code, response_data = create_release(request, payload)
        if status_code == 201:
            messages.success(request, f'Release "{name}" created successfully!')
        else:
            error_detail = response_data.get("detail", "An error occurred while creating the release")
            messages.error(request, error_detail)

        return redirect("core:product_releases", product_id=product_id)
