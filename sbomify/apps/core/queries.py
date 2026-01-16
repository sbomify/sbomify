from __future__ import annotations

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.core.services.querysets import (
    optimize_component_queryset,
    optimize_product_queryset,
    optimize_project_queryset,
)


def get_team_asset_counts(team_id: str) -> dict[str, int]:
    return {
        "products": Product.objects.filter(team_id=team_id).count(),
        "projects": Project.objects.filter(team_id=team_id).count(),
        "components": Component.objects.filter(team_id=team_id).count(),
    }


def get_team_asset_count(team_id: str, resource_type: str) -> int:
    if resource_type == "product":
        return Product.objects.filter(team_id=team_id).count()
    if resource_type == "project":
        return Project.objects.filter(team_id=team_id).count()
    if resource_type == "component":
        return Component.objects.filter(team_id=team_id).count()
    raise ValueError(f"Unknown resource_type: {resource_type}")


__all__ = [
    "get_team_asset_counts",
    "get_team_asset_count",
    "optimize_component_queryset",
    "optimize_product_queryset",
    "optimize_project_queryset",
]
