from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.utils import verify_item_access


class ReleaseDetailsPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        try:
            product: Product = Product.objects.get(pk=product_id)
            release: Release = (
                Release.objects.select_related("product")
                .prefetch_related("artifacts__sbom__component", "artifacts__document__component")
                .get(pk=release_id, product=product)
            )
        except (Product.DoesNotExist, Release.DoesNotExist):
            return error_response(request, HttpResponseNotFound("Release not found"))

        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

        has_crud_permissions = verify_item_access(request, product, ["owner", "admin"])

        has_downloadable_content = release.artifacts.filter(sbom__isnull=False).exists()

        return render(
            request,
            "core/release_details_private.html.j2",
            {
                "product": product,
                "release": release,
                "has_crud_permissions": has_crud_permissions,
                "has_downloadable_content": has_downloadable_content,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": request.session.get("current_team", {}),
            },
        )
