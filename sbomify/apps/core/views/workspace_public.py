from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.schemas import BrandingInfo


class WorkspacePublicView(View):
    """Public workspace landing page showing products and global artifacts."""

    def get(self, request: HttpRequest, workspace_key: str | None = None) -> HttpResponse:
        team = self._resolve_team(request, workspace_key)
        if not team:
            return error_response(request, HttpResponseNotFound("Workspace not found"))

        branding_info = BrandingInfo(**team.branding_info)
        brand = {
            **team.branding_info,
            "brand_image": branding_info.brand_image,
            "brand_color": branding_info.brand_color,
            "accent_color": branding_info.accent_color,
        }

        products = Product.objects.filter(team=team, is_public=True).prefetch_related("projects").order_by("name")
        global_components = Component.objects.filter(team=team, is_public=True, is_global=True).order_by("name")

        products_data = [
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "project_count": product.projects.filter(is_public=True).count(),
            }
            for product in products
        ]
        global_artifacts_data = [
            {
                "id": component.id,
                "name": component.name,
                "component_type": component.component_type,
                "component_type_display": component.get_component_type_display(),
            }
            for component in global_components
        ]

        return render(
            request,
            "core/workspace_public.html.j2",
            {
                "brand": brand,
                "workspace": {
                    "name": team.name.replace("Workspace", "").replace("workspace", "").strip().removesuffix("'s"),
                    "key": team.key,
                },
                "products": products_data,
                "global_components": global_artifacts_data,
            },
        )

    def _resolve_team(self, request: HttpRequest, workspace_key: str | None) -> Team | None:
        """Resolve workspace either from URL token or session."""
        if workspace_key:
            # Do not allow plain numeric IDs; require obfuscated token
            if workspace_key.isdigit():
                return None

            # Try to resolve from token (obfuscated ID)
            try:
                team_id = token_to_number(workspace_key)
                team = Team.objects.get(pk=team_id)
                # Ensure the token matches the stored key to prevent forged prefixes
                if team.key == workspace_key:
                    return team
                return None
            except (ValueError, Team.DoesNotExist):
                return None

        # Try to resolve from session
        current_team = request.session.get("current_team") or {}
        team_id = current_team.get("id") or current_team.get("team_id")

        if not team_id and current_team.get("key"):
            try:
                team_id = token_to_number(current_team["key"])
            except (ValueError, TypeError):
                team_id = None

        if team_id:
            try:
                return Team.objects.get(pk=team_id)
            except Team.DoesNotExist:
                return None

        return None
