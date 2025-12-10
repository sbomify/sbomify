from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_release
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product
from sbomify.apps.core.url_utils import add_custom_domain_to_context
from sbomify.apps.teams.branding import build_branding_context


class ReleaseDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        status_code, release = get_release(request, release_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=release.get("detail", "Unknown error"))
            )

        product = Product.objects.select_related("team").filter(pk=release.get("product_id")).first()
        team = getattr(product, "team", None)

        # If on custom domain, verify the product belongs to this workspace
        is_custom_domain = getattr(request, "is_custom_domain", False)
        if is_custom_domain and hasattr(request, "custom_domain_team"):
            if product and product.team != request.custom_domain_team:
                return error_response(request, HttpResponseNotFound("Release not found"))

        brand = build_branding_context(team)

        context = {
            "brand": brand,
            "release": release,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/release_details_public.html.j2", context)
