from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from sbomify.apps.core.apis import create_release, get_product, list_all_releases
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ReleaseCreateSchema


class ProductReleasesPrivateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.product_releases_public import ProductReleasesPublicView

            return ProductReleasesPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        status_code, product = get_product(request, product_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        status_code, releases = list_all_releases(request, product_id=product_id, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=releases.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})

        return render(
            request,
            "core/product_releases_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "product": product,
                "releases": releases.get("items"),
                "default_release_datetime": timezone.localtime(),
            },
        )

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
