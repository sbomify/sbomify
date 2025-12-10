from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_product
from sbomify.apps.core.errors import error_response
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ProductDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        # Check if this is a custom domain request
        is_custom_domain = getattr(request, "is_custom_domain", False)

        # If on custom domain, verify the product belongs to this workspace
        if is_custom_domain and hasattr(request, "custom_domain_team"):
            from sbomify.apps.core.models import Product

            try:
                product_obj = Product.objects.get(id=product_id)
                if product_obj.team != request.custom_domain_team:
                    return error_response(request, HttpResponseNotFound("Product not found"))
            except Product.DoesNotExist:
                return error_response(request, HttpResponseNotFound("Product not found"))

        status_code, product = get_product(request, product_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        has_downloadable_content = SBOM.objects.filter(component__projects__products__id=product_id).exists()
        team = Team.objects.filter(pk=product.get("team_id")).first()

        # Don't redirect - always show public content on whichever domain the user is on
        # Public pages should be accessible on both main domain and custom domain

        brand = build_branding_context(team)

        return render(
            request,
            "core/product_details_public.html.j2",
            {
                "brand": brand,
                "has_downloadable_content": has_downloadable_content,
                "product": product,
                "is_custom_domain": is_custom_domain,
                "custom_domain": team.custom_domain if is_custom_domain else None,
            },
        )
