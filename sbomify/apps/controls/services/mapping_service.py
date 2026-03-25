from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError
from django.db.models import Q

from sbomify.apps.controls.models import Control, ControlMapping
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)


def create_mapping(
    source_control: Control,
    target_control: Control,
    relation_type: str,
    notes: str = "",
) -> ServiceResult[ControlMapping]:
    """Create a mapping between two controls from different catalogs."""
    if source_control.id == target_control.id:
        return ServiceResult.failure("Cannot map a control to itself", status_code=400)

    if source_control.catalog_id == target_control.catalog_id:
        return ServiceResult.failure("Cannot map controls within the same catalog", status_code=400)

    valid_types = {choice[0] for choice in ControlMapping.RelationType.choices}
    if relation_type not in valid_types:
        return ServiceResult.failure(
            f"Invalid relation type: {relation_type}. Must be one of: {', '.join(sorted(valid_types))}",
            status_code=400,
        )

    from django.db import transaction

    try:
        with transaction.atomic():
            mapping = ControlMapping.objects.create(
                source_control=source_control,
                target_control=target_control,
                relation_type=relation_type,
                notes=notes,
            )
    except IntegrityError:
        return ServiceResult.failure("Mapping between these controls already exists", status_code=409)

    logger.info(
        "Created mapping %s -> %s (%s)",
        source_control.control_id,
        target_control.control_id,
        relation_type,
    )
    return ServiceResult.success(mapping)


def get_mappings_for_control(control: Control) -> ServiceResult[list[ControlMapping]]:
    """Return all mappings where the given control is either source or target."""
    mappings = list(
        ControlMapping.objects.filter(Q(source_control=control) | Q(target_control=control))
        .select_related("source_control", "target_control", "source_control__catalog", "target_control__catalog")
        .order_by("created_at")
    )
    return ServiceResult.success(mappings)


def import_mappings_bulk(mappings: list[dict[str, str]], team: Team) -> ServiceResult[int]:
    """Bulk import control mappings.

    Each item in *mappings* must have keys:
    - source_control_id: PK of the source Control
    - target_control_id: PK of the target Control
    - relation_type: one of ControlMapping.RelationType values
    - notes (optional): descriptive text

    Only controls belonging to the given team are accepted.
    Duplicate mappings are silently skipped.
    """
    if not mappings:
        return ServiceResult.failure("No mappings provided", status_code=400)

    if len(mappings) > 500:
        return ServiceResult.failure("Maximum 500 mappings per bulk import", status_code=400)

    # Collect all referenced control IDs for a single query
    control_ids: set[str] = set()
    for item in mappings:
        src = item.get("source_control_id", "")
        tgt = item.get("target_control_id", "")
        if src:
            control_ids.add(src)
        if tgt:
            control_ids.add(tgt)

    # Fetch all referenced controls that belong to this team
    controls_by_id = {
        c.id: c for c in Control.objects.filter(id__in=control_ids, catalog__team=team).select_related("catalog")
    }

    valid_types = {choice[0] for choice in ControlMapping.RelationType.choices}
    objects_to_create: list[ControlMapping] = []
    errors: list[str] = []

    for idx, item in enumerate(mappings):
        src_id = item.get("source_control_id", "")
        tgt_id = item.get("target_control_id", "")
        rel_type = item.get("relation_type", "")
        notes = item.get("notes", "")

        if not src_id or not tgt_id:
            errors.append(f"Item {idx}: source_control_id and target_control_id are required")
            continue

        if src_id == tgt_id:
            errors.append(f"Item {idx}: cannot map a control to itself")
            continue

        if rel_type not in valid_types:
            errors.append(f"Item {idx}: invalid relation_type '{rel_type}'")
            continue

        source = controls_by_id.get(src_id)
        target = controls_by_id.get(tgt_id)

        if not source:
            errors.append(f"Item {idx}: source control '{src_id}' not found in this workspace")
            continue
        if not target:
            errors.append(f"Item {idx}: target control '{tgt_id}' not found in this workspace")
            continue

        if source.catalog_id == target.catalog_id:
            errors.append(f"Item {idx}: cannot map controls within the same catalog")
            continue

        objects_to_create.append(
            ControlMapping(
                source_control=source,
                target_control=target,
                relation_type=rel_type,
                notes=notes,
            )
        )

    if errors and not objects_to_create:
        return ServiceResult.failure("; ".join(errors), status_code=400)

    created = ControlMapping.objects.bulk_create(objects_to_create, ignore_conflicts=True)
    count = len(created)

    logger.info("Bulk imported %d control mappings for team %s", count, team.key)

    if errors:
        logger.warning("Bulk mapping import had %d skipped items: %s", len(errors), "; ".join(errors))

    return ServiceResult.success(count)
