from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.utils import verify_item_access


class ProductReleasesPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        try:
            product: Product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Product not found"))

        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

        has_crud_permissions = verify_item_access(request, product, ["owner", "admin"])
        releases = Release.objects.filter(product=product).order_by("-created_at")

        return render(
            request,
            "core/product_releases_private.html.j2",
            {
                "product": product,
                "releases": releases,
                "has_crud_permissions": has_crud_permissions,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": request.session.get("current_team", {}),
            },
        )

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        from django.contrib import messages

        from sbomify.apps.core.apis import create_release
        from sbomify.apps.core.schemas import ReleaseCreateSchema

        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        payload = ReleaseCreateSchema(
            name=name,
            description=description,
            product_id=product_id,
            is_prerelease=False,
        )

        status_code, response_data = create_release(request, payload)

        if status_code == 201:
            messages.success(request, f'Release "{name}" created successfully!')
        else:
            error_detail = response_data.get("detail", "An error occurred while creating the release")
            messages.error(request, error_detail)

        return redirect("core:product_releases", product_id=product_id)
