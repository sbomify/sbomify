from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

    # Create controls from catalog data in bulk
    controls_to_create: list[Control] = []
    sort_order = 0
    for group in data.get("groups", []):
        for ctrl in group.get("controls", []):
            controls_to_create.append(
                Control(
                    catalog=catalog,
                    group=group["name"],
                    control_id=ctrl["control_id"],
                    title=ctrl["title"],
                    description=ctrl.get("description", ""),
                    sort_order=sort_order,
                )
            )
            sort_order += 1

    Control.objects.bulk_create(controls_to_create)
    logger.info("Activated catalog %s for team %s (%d controls)", catalog.name, team.key, len(controls_to_create))
    return ServiceResult.success(catalog)


def import_oscal_catalog(team: Team, oscal_json: dict[str, Any]) -> ServiceResult[ControlCatalog]:
    """Import an OSCAL catalog JSON into the controls system.

    Accepts standard OSCAL catalog format (NIST SP 800-53, ISO 27001, etc.)
    with the structure: catalog.metadata, catalog.groups[].controls[].

    Args:
        team: The team to import the catalog for.
        oscal_json: Parsed OSCAL catalog JSON dict.

    Returns:
        ServiceResult with the created ControlCatalog.
    """
    # Validate root structure
    catalog_data = oscal_json.get("catalog")
    if not catalog_data or not isinstance(catalog_data, dict):
        return ServiceResult.failure("Invalid OSCAL format: missing 'catalog' root key", status_code=400)

    metadata = catalog_data.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return ServiceResult.failure("Invalid OSCAL format: missing 'catalog.metadata'", status_code=400)

    title = metadata.get("title", "").strip()
    if not title:
        return ServiceResult.failure("Invalid OSCAL format: missing 'catalog.metadata.title'", status_code=400)

    version = metadata.get("version", "1.0").strip()

    groups = catalog_data.get("groups", [])
    if not isinstance(groups, list) or not groups:
        return ServiceResult.failure("Invalid OSCAL format: 'catalog.groups' is empty or missing", status_code=400)

    # Check for duplicate
    if ControlCatalog.objects.filter(team=team, name=title, version=version).exists():
        return ServiceResult.failure(
            f"Catalog '{title}' version '{version}' already exists for this workspace", status_code=409
        )

    # Create catalog
    catalog = ControlCatalog.objects.create(
        team=team,
        name=title,
        version=version,
        source=ControlCatalog.Source.CUSTOM,
        is_active=True,
    )

    # Parse controls from OSCAL groups
    controls_to_create: list[Control] = []
    sort_order = 0

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_title = str(group.get("title") or group.get("id") or f"Group {sort_order}")

        for ctrl in group.get("controls", []):
            if not isinstance(ctrl, dict):
                continue

            # OSCAL control ID from id field or props label
            control_id = ctrl.get("id", "")
            if not control_id:
                continue

            ctrl_title = str(ctrl.get("title") or control_id)

            # Extract description from parts[].prose where name="statement"
            description = ""
            for part in ctrl.get("parts", []):
                if isinstance(part, dict) and part.get("name") == "statement":
                    description = part.get("prose", "")
                    break

            controls_to_create.append(
                Control(
                    catalog=catalog,
                    group=group_title,
                    control_id=control_id,
                    title=ctrl_title,
                    description=description,
                    sort_order=sort_order,
                )
            )
            sort_order += 1

            # Also import sub-controls (enhancements)
            for sub_ctrl in ctrl.get("controls", []):
                if not isinstance(sub_ctrl, dict):
                    continue
                sub_id = sub_ctrl.get("id", "")
                if not sub_id:
                    continue
                sub_description = ""
                for part in sub_ctrl.get("parts", []):
                    if isinstance(part, dict) and part.get("name") == "statement":
                        sub_description = part.get("prose", "")
                        break
                controls_to_create.append(
                    Control(
                        catalog=catalog,
                        group=group_title,
                        control_id=sub_id,
                        title=str(sub_ctrl.get("title") or sub_id),
                        description=sub_description,
                        sort_order=sort_order,
                    )
                )
                sort_order += 1

    if not controls_to_create:
        catalog.delete()
        return ServiceResult.failure("No controls found in the OSCAL catalog", status_code=400)

    Control.objects.bulk_create(controls_to_create)
    logger.info(
        "Imported OSCAL catalog '%s' v%s for team %s (%d controls)",
        title,
        version,
        team.key,
        len(controls_to_create),
    )
    return ServiceResult.success(catalog)


def get_active_catalogs(team: Team) -> ServiceResult[list[ControlCatalog]]:
    """List active catalogs for a team."""
    catalogs = list(ControlCatalog.objects.filter(team=team, is_active=True))
    return ServiceResult.success(catalogs)


def get_all_catalogs(team: Team) -> ServiceResult[list[ControlCatalog]]:
    """List all catalogs for a team (active and inactive)."""
    catalogs = list(ControlCatalog.objects.filter(team=team))
    return ServiceResult.success(catalogs)


def deactivate_catalog(catalog_id: str, team: Team) -> ServiceResult[None]:
    """Deactivate a catalog (keeps data, just hides from trust center)."""
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return ServiceResult.failure("Catalog not found", status_code=404)

    catalog.is_active = False
    catalog.save(update_fields=["is_active", "updated_at"])
    return ServiceResult.success(None)


def delete_catalog(catalog_id: str, team: Team) -> ServiceResult[None]:
    """Delete a catalog and all its controls/statuses."""
    try:
        catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
    except ControlCatalog.DoesNotExist:
        return ServiceResult.failure("Catalog not found", status_code=404)

    catalog.delete()
    return ServiceResult.success(None)
