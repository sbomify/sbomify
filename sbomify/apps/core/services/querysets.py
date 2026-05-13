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

    # Explicit `.order_by("name", "id")` so pagination is deterministic
    # across requests. `Product.Meta.ordering = ["name"]` is in effect, but
    # `.annotate(...)` resets the implicit Meta ordering in Django's ORM.
    # `id` is the stable tie-breaker: Product names are unique within a
    # team, but the public listing (`is_public=True`) is NOT team-scoped,
    # so the same product name can appear across multiple teams. Without
    # the tie-breaker, two products with the same name could swap positions
    # between adjacent pages.
    return (
        queryset.select_related("team")
        .prefetch_related(
            Prefetch("projects", queryset=project_qs),
            Prefetch("identifiers", queryset=identifier_qs),
            Prefetch("links", queryset=link_qs),
        )
        .annotate(project_count=Count("projects", distinct=True))
        .order_by("name", "id")
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
        .order_by("name")
    )


def optimize_component_queryset(queryset: QuerySet[Component]) -> QuerySet[Component]:
    # Explicit ``.order_by("name", "id")`` so paginated component list
    # endpoints are deterministic. ``Component.Meta.ordering = ["name"]``
    # would normally cover this, but ``.annotate(...)`` resets the implicit
    # Meta ordering. ``id`` is the stable tie-breaker: component names are
    # unique within a team, but public-component listings are not team-
    # scoped, so the same name can appear across teams.
    return (
        queryset.select_related("team")
        .annotate(
            sbom_count=Count("sbom", distinct=True),
            document_count=Count("document", distinct=True),
        )
        .order_by("name", "id")
    )
