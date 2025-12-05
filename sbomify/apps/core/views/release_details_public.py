from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_release
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product
from sbomify.apps.teams.branding import build_branding_context


class ReleaseDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        status_code, release = get_release(request, release_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=release.get("detail", "Unknown error"))
            )

        product = Product.objects.select_related("team").filter(pk=release.get("product_id")).first()
        brand = build_branding_context(getattr(product, "team", None))

        return render(
            request,
            "core/release_details_public.html.j2",
            {
                "brand": brand,
                "release": release,
            },
        )
