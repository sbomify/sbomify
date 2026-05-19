from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views import View

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.utils import get_team_id_from_session
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class SearchView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Search endpoint for products and components."""

    def get(self, request: HttpRequest) -> JsonResponse:
        query = request.GET.get("q", "").strip()
        try:
            limit = max(1, min(int(request.GET.get("limit", 10)), 50))
        except (ValueError, TypeError):
            limit = 10

        if not query or len(query) < 2:
            return JsonResponse({"products": [], "components": []})

        team_id = get_team_id_from_session(request)
        if not team_id:
            return JsonResponse({"products": [], "components": []})

        product_search_filter = Q(name__icontains=query) | Q(description__icontains=query)
        name_search_filter = Q(name__icontains=query)

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

        components = Component.objects.filter(team_id=team_id).filter(name_search_filter).order_by("name")[:limit]
        components_data = [
            {
                "id": c.id,
                "name": c.name,
                "description": "",
                "visibility": c.visibility,
                "component_type": c.component_type or "",
            }
            for c in components
        ]

        # Empty team_key here means the session is missing the
        # ``current_team`` shape; ``capture_for_request`` will skip the
        # event entirely rather than mis-attribute it to a user PK (see
        # the empty-string branch in posthog_service.capture_for_request).
        # This is preferred over silently turning a workspace-scoped
        # event into a user-scoped one.
        team_key = (request.session.get("current_team") or {}).get("key", "")
        result_count = len(products_data) + len(components_data)
        # NEVER include the raw ``query`` string in the event payload — it can
        # contain customer identifiers, internal component names, or secrets
        # users accidentally paste into the search bar. Ship the length and
        # result count only; if someone wants per-query analytics, that's a
        # separate consent-gated funnel, not a property on this event.
        capture_for_request(
            request,
            "search:performed",
            {"query_length": len(query), "result_count": result_count},
            team_key=team_key,
        )

        return JsonResponse({"products": products_data, "components": components_data})
