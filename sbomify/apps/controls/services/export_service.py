from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any

from sbomify.apps.controls.models import ControlCatalog, ControlStatus
from sbomify.apps.controls.services.status_service import get_controls_detail, get_controls_summary
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.core.models import Product
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)


def export_controls_csv(
    team: Team,
    catalog: ControlCatalog,
    product: Product | None = None,
) -> ServiceResult[str]:
    """Export all controls with their statuses as a CSV string.

    Columns: Control ID, Title, Category, Status, Notes, Last Updated
    """
    detail_result = get_controls_detail(catalog, product)
    if not detail_result.ok:
        return ServiceResult.failure(detail_result.error or "Failed to get controls detail")

    groups: list[dict[str, Any]] = detail_result.value or []

    # Build a lookup of control PK -> updated_at from ControlStatus
    control_ids = []
    for group in groups:
        for ctrl in group.get("controls", []):
            control_ids.append(ctrl["id"])

    updated_at_map: dict[str, str] = {}
    if control_ids:
        statuses_qs = ControlStatus.objects.filter(control_id__in=control_ids)
        if product is not None:
            # Product-specific first, then global fallback
            product_statuses = statuses_qs.filter(product=product)
            global_statuses = statuses_qs.filter(product__isnull=True)
            for cs in product_statuses:
                updated_at_map[cs.control_id] = cs.updated_at.isoformat() if cs.updated_at else ""
            for cs in global_statuses:
                if cs.control_id not in updated_at_map:
                    updated_at_map[cs.control_id] = cs.updated_at.isoformat() if cs.updated_at else ""
        else:
            for cs in statuses_qs.filter(product__isnull=True):
                updated_at_map[cs.control_id] = cs.updated_at.isoformat() if cs.updated_at else ""

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Control ID", "Title", "Category", "Status", "Notes", "Last Updated"])

    for group in groups:
        group_name = group["name"]
        for ctrl in group.get("controls", []):
            writer.writerow(
                [
                    ctrl["control_id"],
                    ctrl["title"],
                    group_name,
                    ctrl.get("status", "not_implemented"),
                    ctrl.get("notes", ""),
                    updated_at_map.get(ctrl["id"], ""),
                ]
            )

    return ServiceResult.success(output.getvalue())


def export_controls_summary_csv(team: Team, product: Product | None = None) -> ServiceResult[str]:
    """Export category-level compliance summary as a CSV string.

    Columns: Category, Total, Compliant, Partial, Not Met, N/A, Percentage
    """
    summary_result = get_controls_summary(team, product)
    if not summary_result.ok:
        return ServiceResult.failure(summary_result.error or "Failed to get controls summary")

    summary: dict[str, Any] = summary_result.value or {}
    categories: list[dict[str, Any]] = summary.get("categories", [])

    if not categories:
        return ServiceResult.success("Category,Total,Compliant,Partial,Not Met,N/A,Percentage\r\n")

    # We need per-category status breakdowns. get_controls_summary gives us totals
    # but not per-status counts per category. We need to compute them.
    # Re-fetch the detail to compute per-category status counts.
    active_catalogs = ControlCatalog.objects.filter(team=team, is_active=True)
    if not active_catalogs.exists():
        return ServiceResult.success("Category,Total,Compliant,Partial,Not Met,N/A,Percentage\r\n")

    catalog = active_catalogs.first()
    assert catalog is not None
    detail_result = get_controls_detail(catalog, product)
    if not detail_result.ok:
        return ServiceResult.failure(detail_result.error or "Failed to get controls detail")

    groups: list[dict[str, Any]] = detail_result.value or []

    # Build per-category status counts
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Category", "Total", "Compliant", "Partial", "Not Met", "N/A", "Percentage"])

    for group in groups:
        group_name = group["name"]
        controls = group.get("controls", [])

        status_counts: dict[str, int] = {
            ControlStatus.Status.COMPLIANT: 0,
            ControlStatus.Status.PARTIAL: 0,
            ControlStatus.Status.NOT_IMPLEMENTED: 0,
            ControlStatus.Status.NOT_APPLICABLE: 0,
        }
        for ctrl in controls:
            status = ctrl.get("status", ControlStatus.Status.NOT_IMPLEMENTED)
            status_counts[status] = status_counts.get(status, 0) + 1

        na_count = status_counts[ControlStatus.Status.NOT_APPLICABLE]
        total = len(controls) - na_count
        compliant_count = status_counts[ControlStatus.Status.COMPLIANT]
        partial_count = status_counts[ControlStatus.Status.PARTIAL]
        addressed = compliant_count + (partial_count * 0.5)
        percentage = round((addressed / total) * 100, 1) if total > 0 else 0.0

        writer.writerow(
            [
                group_name,
                total,
                compliant_count,
                partial_count,
                status_counts[ControlStatus.Status.NOT_IMPLEMENTED],
                na_count,
                percentage,
            ]
        )

    return ServiceResult.success(output.getvalue())
