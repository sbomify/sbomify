from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sbomify.apps.controls.models import ControlCatalog
from sbomify.apps.controls.services.status_service import get_controls_summary
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.core.models import Product
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)


def get_public_controls(team: Team) -> ServiceResult[dict[str, Any]]:
    """Get public compliance controls summary for a team's active catalog.

    Returns failure if no active catalog exists.
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
    return ServiceResult.success(
        {
            "catalog": {
                "name": catalog.name,
                "version": catalog.version,
            },
            **summary_result.value,
        }
    )


def get_public_product_controls(product: Product) -> ServiceResult[dict[str, Any]]:
    """Get public compliance controls for a product, falling back to global statuses.

    For each control: uses product-specific ControlStatus if it exists,
    otherwise falls back to the global (product=None) ControlStatus.
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
    return ServiceResult.success(
        {
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
    )
