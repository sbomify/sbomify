from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.schemas import BrandingInfo


class ProductDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        try:
            product: Product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Product not found"))

        if not product.is_public:
            return error_response(request, HttpResponseNotFound("Product not found"))

        has_downloadable_content = SBOM.objects.filter(component__projects__products=product).exists()

        branding_info = BrandingInfo(**product.team.branding_info)

        return render(
            request,
            "core/product_details_public.html.j2",
            {
                "product": product,
                "brand": branding_info,
                "has_downloadable_content": has_downloadable_content,
            },
        )
