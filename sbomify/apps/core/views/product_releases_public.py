from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_product, list_all_releases
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import add_custom_domain_to_context, resolve_product_identifier
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ProductReleasesPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        # Resolve product by slug (on custom domains) or ID (on main app)
        product_obj = resolve_product_identifier(request, product_id)
        if not product_obj:
            return error_response(request, HttpResponseNotFound("Product not found"))

        # Use the resolved product's ID for API calls
        resolved_id = product_obj.id

        status_code, product = get_product(request, resolved_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        status_code, releases = list_all_releases(request, product_id=resolved_id, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=releases.get("detail", "Unknown error"))
            )

        team = Team.objects.filter(pk=product.get("team_id")).first()

        brand = build_branding_context(team)

        context = {
            "product": product,
            "releases": releases.get("items"),
            "brand": brand,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/product_releases_public.html.j2", context)
