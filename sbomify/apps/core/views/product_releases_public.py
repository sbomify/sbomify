from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_product, list_all_releases
from sbomify.apps.core.errors import error_response


class ProductReleasesPublicView(View):
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
        brand = current_team.get("branding_info")

        return render(
            request,
            "core/product_releases_public.html.j2",
            {
                "product": product,
                "releases": releases.items,
                "brand": brand,
            },
        )
