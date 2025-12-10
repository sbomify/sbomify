from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component, Product
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
    products = (
        Product.objects.filter(team=team, is_public=True)
        .annotate(public_project_count=Count("projects", filter=Q(projects__is_public=True), distinct=True))
        .order_by("name")
    )
    return [
        {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "project_count": product.public_project_count,
        }
        for product in products
    ]


def _list_public_global_components(team: Team) -> list[dict]:
    components = Component.objects.filter(team=team, is_public=True, is_global=True).order_by("name")
    return [
        {
            "id": component.id,
            "name": component.name,
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

        # Don't redirect - always show public content on whichever domain the user is on
        # Public pages should be accessible on both main domain and custom domain

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
