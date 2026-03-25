from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sbomify.apps.controls.models import Control, ControlCatalog
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def activate_builtin_catalog(team: Team, catalog_name: str) -> ServiceResult[ControlCatalog]:
    """Activate a built-in catalog for a team. Idempotent."""
    import re as _re

    if not _re.fullmatch(r"[a-z0-9\-]+", catalog_name):
        return ServiceResult.failure("Invalid catalog name", status_code=400)

    catalog_path = (_DATA_DIR / f"{catalog_name}.json").resolve()
    if not str(catalog_path).startswith(str(_DATA_DIR.resolve())):
        return ServiceResult.failure("Invalid catalog name", status_code=400)
    if not catalog_path.exists():
        return ServiceResult.failure(f"Unknown catalog: {catalog_name}", status_code=404)

    data = json.loads(catalog_path.read_text(encoding="utf-8"))

    catalog, created = ControlCatalog.objects.get_or_create(
        team=team,
        name=data["name"],
        version=data["version"],
        defaults={"source": ControlCatalog.Source.BUILTIN, "is_active": True},
    )

    if not created:
        if not catalog.is_active:
            catalog.is_active = True
            catalog.save(update_fields=["is_active", "updated_at"])
        return ServiceResult.success(catalog)

    # Create controls from catalog data
    sort_order = 0
    for group in data.get("groups", []):
        for ctrl in group.get("controls", []):
            Control.objects.create(
                catalog=catalog,
                group=group["name"],
                control_id=ctrl["control_id"],
                title=ctrl["title"],
                description=ctrl.get("description", ""),
                sort_order=sort_order,
            )
            sort_order += 1

    logger.info("Activated catalog %s for team %s (%d controls)", catalog.name, team.key, sort_order)
    return ServiceResult.success(catalog)


def get_active_catalogs(team: Team) -> ServiceResult[list[ControlCatalog]]:
    """List active catalogs for a team."""
    catalogs = list(ControlCatalog.objects.filter(team=team, is_active=True))
    return ServiceResult.success(catalogs)


def delete_catalog(catalog_id: str, team: Team) -> ServiceResult[None]:
    """Delete a catalog and all its controls/statuses."""
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return ServiceResult.failure("Catalog not found", status_code=404)

    catalog.delete()
    return ServiceResult.success(None)
