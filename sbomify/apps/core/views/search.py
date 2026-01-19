from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views import View

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.core.utils import get_team_id_from_session
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class SearchView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Search endpoint for products, projects, and components."""

    def get(self, request: HttpRequest) -> JsonResponse:
        query = request.GET.get("q", "").strip()
        try:
            limit = max(1, min(int(request.GET.get("limit", 10)), 50))
        except (ValueError, TypeError):
            limit = 10

        if not query or len(query) < 2:
            return JsonResponse(
                {
                    "products": [],
                    "projects": [],
                    "components": [],
                }
            )

        team_id = get_team_id_from_session(request)
        if not team_id:
            return JsonResponse(
                {
                    "products": [],
                    "projects": [],
                    "components": [],
                }
            )

        # Build search query - search in name and description (Product has description, Project and Component don't)
        product_search_filter = Q(name__icontains=query) | Q(description__icontains=query)
        name_search_filter = Q(name__icontains=query)

        # Search Products (has description field)
        products = Product.objects.filter(team_id=team_id).filter(product_search_filter).order_by("name")[:limit]
        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "is_public": p.is_public,
            }
            for p in products
        ]

        # Search Projects (no description field)
        projects = Project.objects.filter(team_id=team_id).filter(name_search_filter).order_by("name")[:limit]
        projects_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": "",
                "is_public": p.is_public,
            }
            for p in projects
        ]

        # Search Components (no description field)
        components = Component.objects.filter(team_id=team_id).filter(name_search_filter).order_by("name")[:limit]
        components_data = [
            {
                "id": c.id,
                "name": c.name,
                "description": "",
                "is_public": c.is_public,
                "component_type": c.component_type or "",
            }
            for c in components
        ]

        return JsonResponse(
            {
                "products": products_data,
                "projects": projects_data,
                "components": components_data,
            }
        )
