from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_back_url_from_referrer,
    get_public_path,
    get_workspace_public_url,
    resolve_project_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


def _prepare_public_components(project, is_custom_domain: bool) -> list:
    """Prepare component data for display on the project page."""
    from sbomify.apps.sboms.models import Component

    public_components = []
    # Include both public and gated components (visible to public)
    for component in project.components.filter(
        visibility__in=(Component.Visibility.PUBLIC, Component.Visibility.GATED)
    ).order_by("name"):
        component_data = {
            "id": component.id,
            "name": component.name,
            "slug": component.slug,
            "component_type": component.component_type,
            "component_type_display": component.get_component_type_display(),
        }
        component_data["public_url"] = get_public_path(
            "component", component.id, is_custom_domain=is_custom_domain, slug=component.slug
        )
        public_components.append(component_data)
    return public_components


class ProjectDetailsPublicView(View):
    """
    Public project page view.

    If the project is associated with a public product, redirect to that product page.
    If the project is standalone (no products), show the project page directly.
    """

    def get(self, request: HttpRequest, project_id: str) -> HttpResponse:
        # Resolve project by slug (on custom domains) or ID (on main app)
        # require_public=True filters at query level, preventing race conditions
        project_obj = resolve_project_identifier(request, project_id, require_public=True)
        if not project_obj:
            return error_response(request, HttpResponseNotFound("Project not found"))

        team = Team.objects.filter(pk=project_obj.team_id).first()
        is_custom_domain = getattr(request, "is_custom_domain", False)

        # Check if project has any public products - if so, redirect to product page
        public_products = project_obj.products.filter(is_public=True)
        if public_products.exists():
            product = public_products.first()

            # Redirect to custom domain if needed
            if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
                path = f"/product/{product.slug or product.id}/"
                return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

            redirect_url = reverse("core:product_details_public", kwargs={"product_id": product.id})
            return HttpResponseRedirect(redirect_url)

        # Standalone project (no products) - render project page directly
        # Redirect to custom domain if needed
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path("project", project_obj.id, is_custom_domain=True, slug=project_obj.slug)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        brand = build_branding_context(team)
        workspace_public_url = get_workspace_public_url(request, team)
        public_components = _prepare_public_components(project_obj, is_custom_domain)

        # Get back URL from referrer, with fallback to workspace
        back_url = get_back_url_from_referrer(request, team, workspace_public_url)

        context = {
            "brand": brand,
            "project": {
                "id": project_obj.id,
                "name": project_obj.name,
                "slug": project_obj.slug,
            },
            "public_components": public_components,
            "workspace_public_url": workspace_public_url,
            "back_url": back_url,
            "fallback_url": workspace_public_url,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/project_details_public.html.j2", context)
