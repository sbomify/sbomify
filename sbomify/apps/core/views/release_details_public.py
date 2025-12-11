from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_release
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    resolve_product_identifier,
    resolve_release_identifier,
    should_redirect_to_custom_domain,
)
from sbomify.apps.teams.branding import build_branding_context


class ReleaseDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        # First resolve the product by slug (on custom domains) or ID (on main app)
        product_obj = resolve_product_identifier(request, product_id)
        if not product_obj:
            return error_response(request, HttpResponseNotFound("Product not found"))

        # Then resolve the release by slug (on custom domains) or ID (on main app)
        release_obj = resolve_release_identifier(request, product_obj, release_id)
        if not release_obj:
            return error_response(request, HttpResponseNotFound("Release not found"))

        # Use the resolved release's ID for API calls
        resolved_release_id = release_obj.id

        status_code, release = get_release(request, resolved_release_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=release.get("detail", "Unknown error"))
            )

        product = Product.objects.select_related("team").filter(pk=release.get("product_id")).first()
        team = getattr(product, "team", None)

        # Redirect to custom domain if team has a verified one and we're not already on it
        if team and should_redirect_to_custom_domain(request, team):
            path = get_public_path(
                "release",
                resolved_release_id,
                is_custom_domain=True,
                product_id=product_obj.id,
                product_slug=product_obj.slug,
                release_slug=release_obj.slug,
            )
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        brand = build_branding_context(team)

        context = {
            "brand": brand,
            "release": release,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/release_details_public.html.j2", context)
