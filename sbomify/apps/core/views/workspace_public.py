from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.url_utils import (
    build_custom_domain_url,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


def _fetch_public_team(request: HttpRequest, workspace_key: str | None) -> tuple[int, Team | dict]:
    """
    Resolve a public workspace by explicit key, custom domain, or session fallback.

    On custom domains, the workspace is determined from the domain itself.
    On main app domain, workspace_key parameter or session is used.
    """
    # If on a custom domain, use the team from the custom domain
    if hasattr(request, "is_custom_domain") and request.is_custom_domain:
        if hasattr(request, "custom_domain_team") and request.custom_domain_team:
            team = request.custom_domain_team
            # Still verify it's public
            if not team.is_public:
                return 404, {"detail": "Workspace not found"}
            return 200, team
        # Custom domain but no team found (shouldn't happen due to middleware)
        return 404, {"detail": "Workspace not found"}

    # Standard logic for main app domain
    if workspace_key:
        if workspace_key.isdigit():
            return 404, {"detail": "Workspace not found"}

        try:
            team_id = token_to_number(workspace_key)
        except ValueError:
            return 404, {"detail": "Workspace not found"}

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            return 404, {"detail": "Workspace not found"}

        if team.key != workspace_key or not team.is_public:
            return 404, {"detail": "Workspace not found"}

        return 200, team

    current_team = request.session.get("current_team") or {}
    team_id = current_team.get("id") or current_team.get("team_id")
    if not team_id and current_team.get("key"):
        try:
            team_id = token_to_number(current_team["key"])
        except (ValueError, TypeError):
            team_id = None

    if not team_id:
        return 404, {"detail": "Workspace not found"}

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return 404, {"detail": "Workspace not found"}

    if not team.is_public:
        return 404, {"detail": "Workspace not found"}

    return 200, team


def _list_public_products(team: Team) -> list[dict]:
    """List public products that have at least one public project.

    Includes passing assessments based on the latest SBOM of each component.
    Uses batch query to avoid N+1 database queries.
    """
    from sbomify.apps.plugins.public_assessment_utils import (
        get_products_latest_sbom_assessments_batch,
        passing_assessments_to_dict,
    )

    products = list(
        Product.objects.filter(team=team, is_public=True)
        .annotate(public_project_count=Count("projects", filter=Q(projects__is_public=True), distinct=True))
        .filter(public_project_count__gt=0)  # Only show products with public projects
        .order_by("name")
    )

    # Batch-fetch assessment status for all products at once
    assessments_by_product = get_products_latest_sbom_assessments_batch(products)

    result = []
    for product in products:
        passing_assessments = passing_assessments_to_dict(assessments_by_product.get(str(product.id), []))

        result.append(
            {
                "id": product.id,
                "name": product.name,
                "slug": product.slug,
                "description": product.description,
                "project_count": product.public_project_count,
                "passing_assessments": passing_assessments,
            }
        )

    return result


def _list_public_global_components(team: Team) -> list[dict]:
    components = Component.objects.filter(team=team, is_public=True, is_global=True).order_by("name")
    return [
        {
            "id": component.id,
            "name": component.name,
            "slug": component.slug,
            "component_type": component.component_type,
            "component_type_display": component.get_component_type_display(),
        }
        for component in components
    ]


class WorkspacePublicView(View):
    """Public workspace landing page showing products and global artifacts."""

    def get(self, request: HttpRequest, workspace_key: str | None = None) -> HttpResponse:
        status_code, team_or_error = _fetch_public_team(request, workspace_key)
        if status_code != 200 or not isinstance(team_or_error, Team):
            return error_response(request, HttpResponseNotFound(team_or_error.get("detail", "Workspace not found")))

        team = team_or_error

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request):
            return HttpResponseRedirect(build_custom_domain_url(team, "/", request.is_secure()))

        brand = build_branding_context(team)

        products_data = _list_public_products(team)
        global_artifacts_data = _list_public_global_components(team)

        # Add custom domain context for URL generation in templates
        is_custom_domain = getattr(request, "is_custom_domain", False)

        return render(
            request,
            "core/workspace_public.html.j2",
            {
                "brand": brand,
                "workspace": {
                    "name": team.display_name,
                    "key": team.key,
                },
                "products": products_data,
                "global_components": global_artifacts_data,
                "is_custom_domain": is_custom_domain,
                "custom_domain": team.custom_domain if is_custom_domain else None,
            },
        )
