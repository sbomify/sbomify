from __future__ import annotations

from django.db.models import QuerySet

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.services.querysets import (
    optimize_component_queryset,
    optimize_product_queryset,
)
from sbomify.apps.teams.queries import get_team_user_counts


def _billable_components(team_id: str) -> QuerySet[Component]:
    """Components a plan's limit counts. A TEA subscription references another server's component and is free."""
    return Component.objects.filter(team_id=int(team_id)).exclude(
        component_type=Component.ComponentType.TEA_SUBSCRIPTION
    )


def get_team_asset_counts(team_id: str) -> dict[str, int]:
    return {
        "products": Product.objects.filter(team_id=int(team_id)).count(),
        "components": _billable_components(team_id).count(),
    }


def get_team_asset_count(team_id: str, resource_type: str) -> int:
    if resource_type == "product":
        return Product.objects.filter(team_id=int(team_id)).count()
    if resource_type == "component":
        return _billable_components(team_id).count()
    if resource_type == "user":
        # A pending invitation holds its seat until it expires.
        return get_team_user_counts(team_id)[2]
    raise ValueError(f"Unknown resource_type: {resource_type}")


__all__ = [
    "get_team_asset_counts",
    "get_team_asset_count",
    "optimize_component_queryset",
    "optimize_product_queryset",
]
