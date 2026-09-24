"""The dashboard's security picture: the needs-attention digest.

The digest reuses the component drill-down's pipeline (provider-latest runs
merged by advisory alias, VEX-aware), so a finding reads identically on the
dashboard, the component page, and the product page — suppressed findings
never appear here.
"""

from __future__ import annotations

from typing import Any, cast

from django.core.cache import cache as django_cache

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.services.security_snapshot import build_component_security_picture
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team

_CACHE_TTL_SECONDS = 60
_DIGEST_LIMIT = 4


def get_first_component(team_id: int) -> ServiceResult[Component]:
    """Uncached on purpose: the digest cache may lag a just-created component,
    and the onboarding hero must reflect it immediately."""
    return ServiceResult.success(
        Component.objects.filter(team_id=team_id, component_type=Component.ComponentType.BOM).first()
    )


def get_dashboard_workspace(workspace_key: str | None) -> ServiceResult[Team]:
    if not workspace_key:
        return ServiceResult.success()
    workspace = Team.objects.filter(key=workspace_key).first()
    if workspace is None:
        return ServiceResult.failure("Workspace not found", status_code=404)
    return ServiceResult.success(workspace)


def build_dashboard_context(team_id: int) -> ServiceResult[dict[str, Any]]:
    """One workspace snapshot for the overview, without per-product scan reads."""
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.freshness import freshness_state

    cache_key = f"dashboard-page:v3:{team_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return ServiceResult.success(cast("dict[str, Any]", cached))

    workspace = Team.objects.filter(id=team_id).first()
    if workspace is None:
        return ServiceResult.failure("Workspace not found", status_code=404)

    components = list(
        Component.objects.filter(team_id=team_id, component_type=Component.ComponentType.BOM).values(
            "id", "name", "sbom_freshness_days"
        )
    )
    component_names = {component["id"]: component["name"] for component in components}
    picture = build_component_security_picture(list(component_names), component_names, workspace.patch_sla_days or {})
    has_artifacts = (
        SBOM.objects.filter(component__team_id=team_id).exists()
        or Document.objects.filter(component__team_id=team_id).exists()
    )
    stale_components: set[str] = set()
    without_policy: set[str] = set()
    for component in components:
        latest = picture["latest_sboms"].get(component["id"])
        override = component["sbom_freshness_days"]
        window = override if override is not None else workspace.sbom_freshness_days
        freshness = freshness_state(latest["created_at"] if latest else None, window)
        if freshness and freshness["is_stale"]:
            stale_components.add(component["id"])
        if latest and window is None:
            without_policy.add(component["id"])

    products: list[dict[str, Any]] = []
    product_names_by_component: dict[str, list[str]] = {}
    overdue_by_component: dict[str, int] = {}
    for finding in picture["findings"]:
        if finding["sla"]["overdue"]:
            component_id = finding["component_id"]
            overdue_by_component[component_id] = overdue_by_component.get(component_id, 0) + 1
    # The prefetched join is tenant-scoped on both sides.
    from django.db.models import Prefetch

    for product in (
        Product.objects.filter(team_id=team_id)
        .order_by("name")
        .prefetch_related(Prefetch("components", queryset=Component.objects.filter(team_id=team_id).only("id")))
    ):
        component_ids = {component.id for component in product.components.all()}
        security_ids = component_ids & component_names.keys()
        for component_id in component_ids:
            product_names_by_component.setdefault(component_id, []).append(product.name)
        counts = {
            key: sum(picture["counts"].get(component_id, {}).get(key, 0) for component_id in security_ids)
            for key in ("total", "critical", "high", "medium", "low")
        }
        counts["other"] = counts["total"] - counts["critical"] - counts["high"]
        counts["unknown"] = counts["other"] - counts["medium"] - counts["low"]
        products.append(
            {
                "id": product.id,
                "name": product.name,
                "component_count": len(component_ids),
                "security_component_count": len(security_ids),
                "counts": counts,
                "unassessed": len(security_ids & picture["unassessed"]),
                "stale": len(security_ids & stale_components),
                "missing_sboms": len(security_ids - picture["latest_sboms"].keys()),
                "no_policy": len(security_ids & without_policy),
                "past_sla": sum(overdue_by_component.get(component_id, 0) for component_id in security_ids),
            }
        )
    products.sort(
        key=lambda row: (
            -row["counts"]["critical"],
            -row["counts"]["high"],
            -row["counts"]["total"],
            row["name"].lower(),
        )
    )
    counts = picture["counts"]
    for finding in picture["findings"]:
        finding["products"] = product_names_by_component.get(finding["component_id"], [])
    context = {
        "is_first_visit": not has_artifacts,
        "needs_attention": picture["findings"][:_DIGEST_LIMIT],
        "metrics": {
            "open": sum(count["total"] for count in counts.values()),
            "critical_high": sum(count["critical"] + count["high"] for count in counts.values()),
            "past_sla": sum(overdue_by_component.values()),
            "sla_unknown": sum(count["total"] for count in counts.values())
            - len(picture["findings"])
            + sum(finding["sla"]["label"] == "Awaiting history" for finding in picture["findings"]),
            "known_exploited": sum(bool(finding["kev"]) for finding in picture["findings"]),
            "stale": len(stale_components),
        },
        "unassessed": len(picture["unassessed"]),
        "products": products[:8],
        "product_count": len(products),
    }
    # The first upload must replace setup immediately, without waiting for a
    # cached empty snapshot to expire.
    if has_artifacts:
        django_cache.set(cache_key, context, _CACHE_TTL_SECONDS)
    return ServiceResult.success(context)
