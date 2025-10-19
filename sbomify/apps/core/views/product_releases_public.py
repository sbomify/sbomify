from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product, Release
from sbomify.apps.teams.schemas import BrandingInfo


class ProductReleasesPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        try:
            product: Product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Product not found"))

        if not product.is_public:
            return error_response(request, HttpResponseNotFound("Product not found"))

        releases = Release.objects.filter(product=product).order_by("-created_at")
        branding_info = BrandingInfo(**product.team.branding_info)

        return render(
            request,
            "core/product_releases_public.html.j2",
            {
                "product": product,
                "releases": releases,
                "brand": branding_info,
            },
        )
