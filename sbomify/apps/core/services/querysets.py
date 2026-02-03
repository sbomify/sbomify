from __future__ import annotations

from django.db.models import Count, Prefetch, QuerySet

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.sboms.models import ProductIdentifier, ProductLink


def optimize_product_queryset(queryset: QuerySet[Product]) -> QuerySet[Product]:
    project_qs = Project.objects.only("id", "name", "is_public", "team_id").order_by("name")
    identifier_qs = ProductIdentifier.objects.only(
        "id", "identifier_type", "value", "created_at", "product_id"
    ).order_by("identifier_type", "value")
    link_qs = ProductLink.objects.only(
        "id", "link_type", "title", "url", "description", "created_at", "product_id"
    ).order_by("link_type", "title")

    return (
        queryset.select_related("team")
        .prefetch_related(
            Prefetch("projects", queryset=project_qs),
            Prefetch("identifiers", queryset=identifier_qs),
            Prefetch("links", queryset=link_qs),
        )
        .annotate(project_count=Count("projects", distinct=True))
    )


def optimize_project_queryset(queryset: QuerySet[Project]) -> QuerySet[Project]:
    component_qs = Component.objects.only(
        "id",
        "name",
        "visibility",
        "is_global",
        "component_type",
        "team_id",
    ).order_by("name")

    return (
        queryset.select_related("team")
        .prefetch_related(Prefetch("components", queryset=component_qs))
        .annotate(component_count=Count("components", distinct=True))
    )


def optimize_component_queryset(queryset: QuerySet[Component]) -> QuerySet[Component]:
    return queryset.select_related("team").annotate(
        sbom_count=Count("sbom", distinct=True),
        document_count=Count("document", distinct=True),
    )
