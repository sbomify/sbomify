from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_product, list_all_releases
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    get_workspace_public_url,
    resolve_product_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ProductReleasesPublicView(View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        # Resolve product by slug (on custom domains) or ID (on main app)
        # require_public=True filters at query level, preventing race conditions
        product_obj = resolve_product_identifier(request, product_id, require_public=True)
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

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path("product_releases", resolved_id, is_custom_domain=True, slug=product_obj.slug)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        brand = build_branding_context(team)

        # Get workspace public URL for breadcrumbs
        workspace_public_url = get_workspace_public_url(request, team)

        context = {
            "product": product,
            "releases": releases.get("items"),
            "brand": brand,
            "workspace_public_url": workspace_public_url,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/product_releases_public.html.j2", context)
