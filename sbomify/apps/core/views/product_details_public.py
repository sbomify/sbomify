from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_product
from sbomify.apps.core.errors import error_response
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ProductDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        status_code, product = get_product(request, product_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        has_downloadable_content = SBOM.objects.filter(component__projects__products__id=product_id).exists()
        team = Team.objects.filter(pk=product.get("team_id")).first()
        brand = build_branding_context(team)

        return render(
            request,
            "core/product_details_public.html.j2",
            {
                "brand": brand,
                "has_downloadable_content": has_downloadable_content,
                "product": product,
            },
        )
