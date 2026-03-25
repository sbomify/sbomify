from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sbomify.apps.controls.models import ControlCatalog
from sbomify.apps.controls.services.status_service import get_controls_detail, get_controls_summary
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.core.models import Product
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)


def get_public_controls(team: Team) -> ServiceResult[dict[str, Any]]:
    """Get public compliance controls summary for a team's active catalog.

    Returns failure if no active catalog exists.
    Includes individual controls per category for the expandable accordion.
    """
    active_catalogs = ControlCatalog.objects.filter(team=team, is_active=True)
    if not active_catalogs.exists():
        return ServiceResult.failure("No active catalog", status_code=404)

    # We checked exists() above, so first() is guaranteed non-None
    catalog = active_catalogs[0]
    summary_result = get_controls_summary(team)
    if not summary_result.ok:
        return summary_result

    assert summary_result.value is not None
    data = {
        "catalog": {
            "name": catalog.name,
            "version": catalog.version,
        },
        **summary_result.value,
    }

    # Enrich categories with individual controls for the public accordion
    detail_result = get_controls_detail(catalog)
    if detail_result.ok and detail_result.value:
        _merge_controls_into_categories(data["categories"], detail_result.value)

    return ServiceResult.success(data)


def get_public_product_controls(product: Product) -> ServiceResult[dict[str, Any]]:
    """Get public compliance controls for a product, falling back to global statuses.

    For each control: uses product-specific ControlStatus if it exists,
    otherwise falls back to the global (product=None) ControlStatus.
    Includes individual controls per category for the expandable accordion.
    """
    team = product.team
    active_catalogs = ControlCatalog.objects.filter(team=team, is_active=True)
    if not active_catalogs.exists():
        return ServiceResult.failure("No active catalog", status_code=404)

    # We checked exists() above, so index access is safe
    catalog = active_catalogs[0]
    summary_result = get_controls_summary(team, product=product)
    if not summary_result.ok:
        return summary_result

    assert summary_result.value is not None
    data = {
        "catalog": {
            "name": catalog.name,
            "version": catalog.version,
        },
        "product": {
            "id": product.id,
            "name": product.name,
        },
        **summary_result.value,
    }

    # Enrich categories with individual controls for the public accordion
    detail_result = get_controls_detail(catalog, product=product)
    if detail_result.ok and detail_result.value:
        _merge_controls_into_categories(data["categories"], detail_result.value)

    return ServiceResult.success(data)


def _merge_controls_into_categories(categories: list[dict[str, Any]], detail_groups: list[dict[str, Any]]) -> None:
    """Merge individual control data from detail groups into summary categories.

    Modifies categories in-place, adding a 'controls' list to each category
    with control_id, title, and status for the public accordion display.
    """
    # Build a lookup from group name to controls list
    detail_by_name: dict[str, list[dict[str, Any]]] = {}
    for group in detail_groups:
        detail_by_name[group["name"]] = [
            {
                "control_id": c["control_id"],
                "title": c["title"],
                "status": c["status"],
            }
            for c in group["controls"]
        ]

    for category in categories:
        category["controls"] = detail_by_name.get(category["name"], [])
