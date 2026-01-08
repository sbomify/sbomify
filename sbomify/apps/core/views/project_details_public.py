from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.urls import reverse
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    build_custom_domain_url,
    resolve_project_identifier,
)
from sbomify.apps.teams.models import Team


class ProjectDetailsPublicView(View):
    """
    Redirect project public pages to the parent product page.

    Projects are now shown as sections within the product page,
    so standalone project pages redirect to maintain old URLs.
    """

    def get(self, request: HttpRequest, project_id: str) -> HttpResponse:
        # Resolve project by slug (on custom domains) or ID (on main app)
        project_obj = resolve_project_identifier(request, project_id)
        if not project_obj:
            return error_response(request, HttpResponseNotFound("Project not found"))

        # Find a public product that contains this project
        public_products = project_obj.products.filter(is_public=True)
        if not public_products.exists():
            # No public product - return 404
            return error_response(request, HttpResponseNotFound("Project not available"))

        # Get the first public product
        product = public_products.first()
        team = Team.objects.filter(pk=project_obj.team_id).first()

        # Build the redirect URL
        is_custom_domain = getattr(request, "is_custom_domain", False)
        if is_custom_domain and team:
            path = f"/product/{product.slug or product.id}/"
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))
        else:
            redirect_url = reverse("core:product_details_public", kwargs={"product_id": product.id})
            return HttpResponseRedirect(redirect_url)
