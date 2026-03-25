from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus, ControlStatusLog
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.core.models import Product, User
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)

_VALID_STATUSES = {choice[0] for choice in ControlStatus.Status.choices}

# Map group names to icons (loaded from catalog JSON, but we keep a fallback map)
_GROUP_ICONS: dict[str, str] = {
    "Security": "fa-lock",
    "Availability": "fa-server",
    "Processing Integrity": "fa-check-double",
    "Confidentiality": "fa-shield-halved",
    "Privacy": "fa-user-shield",
}


def upsert_status(
    control: Control,
    product: Product | None,
    status: str,
    user: User,
    notes: str = "",
) -> ServiceResult[ControlStatus]:
    """Create or update a ControlStatus for a control (global or product-specific)."""
    if status not in _VALID_STATUSES:
        return ServiceResult.failure(
            f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
            status_code=400,
        )

    # Capture old status before the upsert
    old_status = ""
    try:
        existing = ControlStatus.objects.get(control=control, product=product)
        old_status = existing.status
    except ControlStatus.DoesNotExist:
        pass

    control_status, _created = ControlStatus.objects.update_or_create(
        control=control,
        product=product,
        defaults={
            "status": status,
            "notes": notes,
            "updated_by": user,
        },
    )

    # Log only when the status actually changed
    if old_status != status:
        ControlStatusLog.objects.create(
            control=control,
            product=product,
            old_status=old_status,
            new_status=status,
            changed_by=user,
        )

    return ServiceResult.success(control_status)


def bulk_update_statuses(updates: list[dict[str, Any]], user: User, team: Team | None = None) -> ServiceResult[int]:
    """Atomically update multiple control statuses.

    Each dict must have: control_id (str), status (str).
    Optional: product_id (str|None), notes (str).
    """
    # Validate all statuses upfront before touching the DB
    for i, update in enumerate(updates):
        status = update.get("status", "")
        if status not in _VALID_STATUSES:
            return ServiceResult.failure(
                f"Invalid status '{status}' at index {i}. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                status_code=400,
            )
        if "control_id" not in update:
            return ServiceResult.failure(f"Missing 'control_id' at index {i}", status_code=400)

    count = 0
    try:
        with transaction.atomic():
            for update in updates:
                try:
                    filter_kwargs: dict[str, Any] = {"id": update["control_id"]}
                    if team:
                        filter_kwargs["catalog__team"] = team
                    control = Control.objects.get(**filter_kwargs)
                except Control.DoesNotExist:
                    raise ValueError(f"Control '{update['control_id']}' not found")

                product = None
                product_id = update.get("product_id")
                if product_id:
                    from sbomify.apps.core.models import Product

                    try:
                        filter_kwargs_p: dict[str, Any] = {"id": product_id}
                        if team:
                            filter_kwargs_p["team"] = team
                        product = Product.objects.get(**filter_kwargs_p)
                    except Product.DoesNotExist:
                        raise ValueError(f"Product '{product_id}' not found")

                # Capture old status before the upsert
                old_status = ""
                try:
                    existing = ControlStatus.objects.get(control=control, product=product)
                    old_status = existing.status
                except ControlStatus.DoesNotExist:
                    pass

                new_status = update["status"]
                ControlStatus.objects.update_or_create(
                    control=control,
                    product=product,
                    defaults={
                        "status": new_status,
                        "notes": update.get("notes", ""),
                        "updated_by": user,
                    },
                )

                # Log only when the status actually changed
                if old_status != new_status:
                    ControlStatusLog.objects.create(
                        control=control,
                        product=product,
                        old_status=old_status,
                        new_status=new_status,
                        changed_by=user,
                    )

                count += 1
    except ValueError as e:
        return ServiceResult.failure(str(e), status_code=400)

    return ServiceResult.success(count)


def get_controls_summary(team: Team, product: Product | None = None) -> ServiceResult[dict[str, Any]]:
    """Calculate compliance summary for a team's active catalog.

    Returns dict with: total, addressed, percentage, by_status, categories.
    Scoring: compliant=1, partial=0.5, not_applicable excluded from total.
    """
    active_catalogs = ControlCatalog.objects.filter(team=team, is_active=True)
    if not active_catalogs.exists():
        return ServiceResult.success(
            {
                "total": 0,
                "addressed": 0.0,
                "percentage": 0.0,
                "by_status": {},
                "categories": [],
            }
        )

    catalog = active_catalogs.first()
    controls = Control.objects.filter(catalog=catalog).select_related("catalog")

    # Build a map of control -> effective status
    status_map = _build_status_map(controls, product)

    return ServiceResult.success(_compute_summary(controls, status_map))


def get_controls_detail(catalog: ControlCatalog, product: Product | None = None) -> ServiceResult[list[dict[str, Any]]]:
    """Return controls grouped by category with their statuses."""
    controls = Control.objects.filter(catalog=catalog).order_by("sort_order", "control_id")
    status_map = _build_status_map(controls, product)

    groups: dict[str, list[dict[str, Any]]] = {}
    for control in controls:
        status_info = status_map.get(control.id)
        control_data: dict[str, Any] = {
            "id": control.id,
            "control_id": control.control_id,
            "title": control.title,
            "description": control.description,
            "group": control.group,
            "status": status_info["status"] if status_info else ControlStatus.Status.NOT_IMPLEMENTED,
            "notes": status_info["notes"] if status_info else "",
            "is_product_specific": status_info["is_product_specific"] if status_info else False,
        }
        groups.setdefault(control.group, []).append(control_data)

    result = []
    for group_name, group_controls in groups.items():
        result.append(
            {
                "name": group_name,
                "icon": _GROUP_ICONS.get(group_name, "fa-circle"),
                "controls": group_controls,
            }
        )

    return ServiceResult.success(result)


def _build_status_map(controls: Any, product: Product | None = None) -> dict[str, dict[str, Any]]:
    """Build a map of control PK -> effective status dict.

    For product views: prefer product-specific status, fall back to global.
    For global views: use only global statuses (product=None).
    """
    control_ids = [c.id for c in controls]

    if product is not None:
        # Get product-specific statuses
        product_statuses = {
            cs.control_id: {"status": cs.status, "notes": cs.notes, "is_product_specific": True}
            for cs in ControlStatus.objects.filter(control_id__in=control_ids, product=product)
        }
        # Get global statuses as fallback
        global_statuses = {
            cs.control_id: {"status": cs.status, "notes": cs.notes, "is_product_specific": False}
            for cs in ControlStatus.objects.filter(control_id__in=control_ids, product__isnull=True)
        }
        # Merge: product overrides global
        merged = {}
        for cid in control_ids:
            if cid in product_statuses:
                merged[cid] = product_statuses[cid]
            elif cid in global_statuses:
                merged[cid] = global_statuses[cid]
        return merged
    else:
        return {
            cs.control_id: {"status": cs.status, "notes": cs.notes, "is_product_specific": False}
            for cs in ControlStatus.objects.filter(control_id__in=control_ids, product__isnull=True)
        }


def _compute_summary(controls: Any, status_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute scoring from a controls queryset and a status map.

    Scoring: compliant=1, partial=0.5, not_applicable excluded from total.
    """
    by_status: dict[str, int] = {}
    for status_info in status_map.values():
        status_val = status_info["status"]
        by_status[status_val] = by_status.get(status_val, 0) + 1

    # Count controls without explicit status as not_implemented
    controls_list = list(controls)
    statused_count = len(status_map)
    unstatused = len(controls_list) - statused_count
    if unstatused > 0:
        by_status[ControlStatus.Status.NOT_IMPLEMENTED] = (
            by_status.get(ControlStatus.Status.NOT_IMPLEMENTED, 0) + unstatused
        )

    na_count = by_status.get(ControlStatus.Status.NOT_APPLICABLE, 0)
    total = len(controls_list) - na_count
    compliant_count = by_status.get(ControlStatus.Status.COMPLIANT, 0)
    partial_count = by_status.get(ControlStatus.Status.PARTIAL, 0)
    addressed = compliant_count + (partial_count * 0.5)
    percentage = round((addressed / total) * 100, 1) if total > 0 else 0.0

    # Categories breakdown
    groups: dict[str, list[Any]] = {}
    for control in controls_list:
        groups.setdefault(control.group, []).append(control)

    categories = []
    for group_name, group_controls in groups.items():
        cat_by_status: dict[str, int] = {}
        for c in group_controls:
            cat_info: dict[str, Any] | None = status_map.get(c.id)
            cat_status: str = cat_info["status"] if cat_info else ControlStatus.Status.NOT_IMPLEMENTED
            cat_by_status[cat_status] = cat_by_status.get(cat_status, 0) + 1

        cat_na = cat_by_status.get(ControlStatus.Status.NOT_APPLICABLE, 0)
        cat_total = len(group_controls) - cat_na
        cat_compliant = cat_by_status.get(ControlStatus.Status.COMPLIANT, 0)
        cat_partial = cat_by_status.get(ControlStatus.Status.PARTIAL, 0)
        cat_addressed = cat_compliant + (cat_partial * 0.5)
        cat_percentage = round((cat_addressed / cat_total) * 100, 1) if cat_total > 0 else 0.0

        categories.append(
            {
                "name": group_name,
                "total": cat_total,
                "addressed": cat_addressed,
                "percentage": cat_percentage,
                "icon": _GROUP_ICONS.get(group_name, "fa-circle"),
            }
        )

    return {
        "total": total,
        "addressed": addressed,
        "percentage": percentage,
        "by_status": by_status,
        "categories": categories,
    }
