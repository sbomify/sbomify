"""Service layer for Common Lifecycle Enumeration (CLE) management.

Handles creation of CLE events and support definitions, lifecycle date
recomputation, and conversion to libtea CLE documents for TEA API export.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from libtea.models import (
    CLE,
    CLEDefinitions,
    CLEEventType,
    CLEVersionSpecifier,
    Identifier,
)
from libtea.models import (
    CLEEvent as TeaCLEEvent,
)
from libtea.models import (
    CLESupportDefinition as TeaCLESupportDefinition,
)

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import (
    BaseCLEEvent,
    BaseCLESupportDefinition,
    ComponentCLEEvent,
    ComponentCLESupportDefinition,
    ComponentReleaseCLEEvent,
    ComponentReleaseCLESupportDefinition,
    ProductCLEEvent,
    ProductCLESupportDefinition,
    ReleaseCLEEvent,
    ReleaseCLESupportDefinition,
)

if TYPE_CHECKING:
    from django.db import models as django_models

    from sbomify.apps.core.models import Component, ComponentRelease, Release
    from sbomify.apps.sboms.models import Product

logger = logging.getLogger(__name__)

# Event types that require a non-empty `versions` list.
_VERSIONS_REQUIRED = frozenset(
    {
        CLEEventType.END_OF_DEVELOPMENT,
        CLEEventType.END_OF_SUPPORT,
        CLEEventType.END_OF_LIFE,
        CLEEventType.END_OF_DISTRIBUTION,
        CLEEventType.END_OF_MARKETING,
    }
)

# Event types where `support_id`, if provided, must reference an existing definition.
_SUPPORT_ID_CHECKED = frozenset(
    {
        CLEEventType.END_OF_DEVELOPMENT,
        CLEEventType.END_OF_SUPPORT,
    }
)

# Maximum items allowed in list fields for safety.
_MAX_VERSIONS = 100
_MAX_IDENTIFIERS = 100
_MAX_REFERENCES = 100


def _validate_json_fields(
    versions: list[dict[str, Any]],
    identifiers: list[dict[str, Any]],
    references: list[str],
) -> str | None:
    """Validate structural integrity of JSON list fields.

    Returns an error message if validation fails, else None.
    """
    if len(versions) > _MAX_VERSIONS:
        return f"versions list exceeds maximum of {_MAX_VERSIONS} entries"
    for i, v in enumerate(versions):
        if not isinstance(v, dict):
            return f"versions[{i}] must be a dict, got {type(v).__name__}"
        if not v.get("version") and not v.get("range"):
            return f"versions[{i}] must contain 'version' and/or 'range'"
        if v.get("version") is not None and not isinstance(v["version"], str):
            return f"versions[{i}].version must be a string, got {type(v['version']).__name__}"
        if v.get("range") is not None and not isinstance(v["range"], str):
            return f"versions[{i}].range must be a string, got {type(v['range']).__name__}"

    if len(identifiers) > _MAX_IDENTIFIERS:
        return f"identifiers list exceeds maximum of {_MAX_IDENTIFIERS} entries"
    for i, ident in enumerate(identifiers):
        if not isinstance(ident, dict):
            return f"identifiers[{i}] must be a dict, got {type(ident).__name__}"
        if not ident.get("type") or not ident.get("value"):
            return f"identifiers[{i}] must contain non-empty 'type' and 'value'"
        if not isinstance(ident["type"], str):
            return f"identifiers[{i}].type must be a string, got {type(ident['type']).__name__}"
        if not isinstance(ident["value"], str):
            return f"identifiers[{i}].value must be a string, got {type(ident['value']).__name__}"

    if len(references) > _MAX_REFERENCES:
        return f"references list exceeds maximum of {_MAX_REFERENCES} entries"
    for i, ref in enumerate(references):
        if not isinstance(ref, str):
            return f"references[{i}] must be a string, got {type(ref).__name__}"

    return None


def create_cle_event_generic(
    entity: django_models.Model,
    entity_fk_field: str,
    event_model: type[BaseCLEEvent],
    support_def_model: type[BaseCLESupportDefinition],
    event_type: str,
    effective: datetime,
    *,
    entity_label: str = "entity",
    recompute_fn: Any | None = None,
    version: str = "",
    versions: list[dict[str, Any]] | None = None,
    support_id: str = "",
    license: str = "",
    superseded_by_version: str = "",
    identifiers: list[dict[str, Any]] | None = None,
    withdrawn_event_id: int | None = None,
    reason: str = "",
    description: str = "",
    references: list[str] | None = None,
) -> ServiceResult[Any]:
    """Create a CLE lifecycle event for any entity level.

    Generic implementation that accepts the entity instance, the FK field name
    on the event/support-def model (e.g. ``"product"``, ``"component"``), and
    the concrete event and support-definition model classes.

    ``entity_label`` is used in human-readable error messages (e.g. "product",
    "component").  ``recompute_fn``, when provided, is called with the locked
    entity after the event is created (used for product lifecycle date caching).
    """
    versions = versions or []
    identifiers = identifiers or []
    references = references or []

    # Validate event_type
    valid_types = {choice.value for choice in CLEEventType}
    if event_type not in valid_types:
        return ServiceResult.failure(f"Invalid event type: {event_type}", status_code=400)

    # Validate JSON field structure (stateless — safe before lock)
    json_error = _validate_json_fields(versions, identifiers, references)
    if json_error is not None:
        return ServiceResult.failure(json_error, status_code=400)

    with transaction.atomic():
        # Lock the entity row first to serialize concurrent event creation.
        # DB-dependent validation runs under the lock to prevent races (e.g.
        # a concurrent withdrawn event referencing an event being created).
        locked_entity = type(entity).objects.select_for_update().filter(pk=entity.pk).first()  # type: ignore[attr-defined]
        if locked_entity is None:
            return ServiceResult.failure(f"{entity_label.capitalize()} no longer exists", status_code=404)

        # Per-type validation (may query DB — must run under lock)
        fields = {
            "version": version,
            "versions": versions,
            "support_id": support_id,
            "superseded_by_version": superseded_by_version,
            "identifiers": identifiers,
            "withdrawn_event_id": withdrawn_event_id,
        }
        validation_error = _validate_event_fields_generic(
            entity, entity_fk_field, event_model, support_def_model, event_type, fields, entity_label
        )
        if validation_error is not None:
            return ServiceResult.failure(validation_error, status_code=400)

        # Auto-assign next event_id
        filter_kwargs = {entity_fk_field: entity}
        max_id = event_model.objects.filter(**filter_kwargs).aggregate(Max("event_id"))["event_id__max"]  # type: ignore[attr-defined]
        next_id: int = (max_id or 0) + 1

        create_kwargs = {
            entity_fk_field: entity,
            "event_id": next_id,
            "event_type": event_type,
            "effective": effective,
            "version": version,
            "versions": versions,
            "support_id": support_id,
            "license": license,
            "superseded_by_version": superseded_by_version,
            "identifiers": identifiers,
            "withdrawn_event_id": withdrawn_event_id,
            "reason": reason,
            "description": description,
            "references": references,
        }
        event = event_model.objects.create(**create_kwargs)  # type: ignore[attr-defined]

        if recompute_fn is not None:
            recompute_fn(locked_entity)

    return ServiceResult.success(event)


def _validate_event_fields_generic(
    entity: django_models.Model,
    entity_fk_field: str,
    event_model: type[BaseCLEEvent],
    support_def_model: type[BaseCLESupportDefinition],
    event_type: str,
    fields: dict[str, Any],
    entity_label: str,
) -> str | None:
    """Return an error message if required fields are missing, else None.

    Works for any entity level by using the FK field name to build filter kwargs.
    """
    filter_kwargs = {entity_fk_field: entity}

    if event_type == CLEEventType.RELEASED:
        pass  # version is recommended but not enforced

    elif event_type in _VERSIONS_REQUIRED:
        versions = fields.get("versions")
        if not versions:
            return f"{event_type} events require a non-empty 'versions' list"

        if event_type in _SUPPORT_ID_CHECKED:
            sid = fields.get("support_id")
            if sid and not support_def_model.objects.filter(**filter_kwargs, support_id=sid).exists():  # type: ignore[attr-defined]
                return f"Support definition '{sid}' does not exist for this {entity_label}"

    elif event_type == CLEEventType.SUPERSEDED_BY:
        if not fields.get("superseded_by_version"):
            return "supersededBy events require a non-empty 'superseded_by_version'"

    elif event_type == CLEEventType.COMPONENT_RENAMED:
        if not fields.get("identifiers"):
            return "componentRenamed events require a non-empty 'identifiers' list"

    elif event_type == CLEEventType.WITHDRAWN:
        withdrawn_event_id = fields.get("withdrawn_event_id")
        if withdrawn_event_id is None:
            return "withdrawn events require 'withdrawn_event_id'"
        if not event_model.objects.filter(**filter_kwargs, event_id=withdrawn_event_id).exists():  # type: ignore[attr-defined]
            return f"Referenced event_id {withdrawn_event_id} does not exist for this {entity_label}"

    return None


def create_support_definition_generic(
    entity: django_models.Model,
    entity_fk_field: str,
    support_def_model: type[BaseCLESupportDefinition],
    support_id: str,
    description: str,
    url: str = "",
    *,
    entity_label: str = "entity",
) -> ServiceResult[Any]:
    """Create a named support tier definition for any entity level."""
    try:
        with transaction.atomic():
            create_kwargs = {
                entity_fk_field: entity,
                "support_id": support_id,
                "description": description,
                "url": url,
            }
            definition = support_def_model.objects.create(**create_kwargs)  # type: ignore[attr-defined]
    except IntegrityError:
        return ServiceResult.failure(
            f"Support definition '{support_id}' already exists for this {entity_label}",
            status_code=409,
        )

    return ServiceResult.success(definition)


# ---------------------------------------------------------------------------
# Product-level convenience wrappers (backward compatible)
# ---------------------------------------------------------------------------


def create_cle_event(
    product: Product,
    event_type: str,
    effective: datetime,
    *,
    version: str = "",
    versions: list[dict[str, Any]] | None = None,
    support_id: str = "",
    license: str = "",
    superseded_by_version: str = "",
    identifiers: list[dict[str, Any]] | None = None,
    withdrawn_event_id: int | None = None,
    reason: str = "",
    description: str = "",
    references: list[str] | None = None,
) -> ServiceResult[ProductCLEEvent]:
    """Create a new CLE lifecycle event for a product.

    Validates required fields per event type, auto-assigns the next event_id,
    and recomputes cached lifecycle dates on the product.
    """
    return create_cle_event_generic(
        entity=product,
        entity_fk_field="product",
        event_model=ProductCLEEvent,
        support_def_model=ProductCLESupportDefinition,
        event_type=event_type,
        effective=effective,
        entity_label="product",
        recompute_fn=recompute_lifecycle_dates,
        version=version,
        versions=versions,
        support_id=support_id,
        license=license,
        superseded_by_version=superseded_by_version,
        identifiers=identifiers,
        withdrawn_event_id=withdrawn_event_id,
        reason=reason,
        description=description,
        references=references,
    )


def create_support_definition(
    product: Product,
    support_id: str,
    description: str,
    url: str = "",
) -> ServiceResult[ProductCLESupportDefinition]:
    """Create a named support tier definition for a product."""
    return create_support_definition_generic(
        entity=product,
        entity_fk_field="product",
        support_def_model=ProductCLESupportDefinition,
        support_id=support_id,
        description=description,
        url=url,
        entity_label="product",
    )


# ---------------------------------------------------------------------------
# Component-level convenience wrappers
# ---------------------------------------------------------------------------


def create_component_cle_event(
    component: Component,
    event_type: str,
    effective: datetime,
    *,
    version: str = "",
    versions: list[dict[str, Any]] | None = None,
    support_id: str = "",
    license: str = "",
    superseded_by_version: str = "",
    identifiers: list[dict[str, Any]] | None = None,
    withdrawn_event_id: int | None = None,
    reason: str = "",
    description: str = "",
    references: list[str] | None = None,
) -> ServiceResult[ComponentCLEEvent]:
    """Create a new CLE lifecycle event for a component."""
    return create_cle_event_generic(
        entity=component,
        entity_fk_field="component",
        event_model=ComponentCLEEvent,
        support_def_model=ComponentCLESupportDefinition,
        event_type=event_type,
        effective=effective,
        entity_label="component",
        version=version,
        versions=versions,
        support_id=support_id,
        license=license,
        superseded_by_version=superseded_by_version,
        identifiers=identifiers,
        withdrawn_event_id=withdrawn_event_id,
        reason=reason,
        description=description,
        references=references,
    )


def create_component_support_definition(
    component: Component,
    support_id: str,
    description: str,
    url: str = "",
) -> ServiceResult[ComponentCLESupportDefinition]:
    """Create a named support tier definition for a component."""
    return create_support_definition_generic(
        entity=component,
        entity_fk_field="component",
        support_def_model=ComponentCLESupportDefinition,
        support_id=support_id,
        description=description,
        url=url,
        entity_label="component",
    )


# ---------------------------------------------------------------------------
# Release-level convenience wrappers
# ---------------------------------------------------------------------------


def create_release_cle_event(
    release: Release,
    event_type: str,
    effective: datetime,
    *,
    version: str = "",
    versions: list[dict[str, Any]] | None = None,
    support_id: str = "",
    license: str = "",
    superseded_by_version: str = "",
    identifiers: list[dict[str, Any]] | None = None,
    withdrawn_event_id: int | None = None,
    reason: str = "",
    description: str = "",
    references: list[str] | None = None,
) -> ServiceResult[ReleaseCLEEvent]:
    """Create a new CLE lifecycle event for a release."""
    return create_cle_event_generic(
        entity=release,
        entity_fk_field="release",
        event_model=ReleaseCLEEvent,
        support_def_model=ReleaseCLESupportDefinition,
        event_type=event_type,
        effective=effective,
        entity_label="release",
        version=version,
        versions=versions,
        support_id=support_id,
        license=license,
        superseded_by_version=superseded_by_version,
        identifiers=identifiers,
        withdrawn_event_id=withdrawn_event_id,
        reason=reason,
        description=description,
        references=references,
    )


def create_release_support_definition(
    release: Release,
    support_id: str,
    description: str,
    url: str = "",
) -> ServiceResult[ReleaseCLESupportDefinition]:
    """Create a named support tier definition for a release."""
    return create_support_definition_generic(
        entity=release,
        entity_fk_field="release",
        support_def_model=ReleaseCLESupportDefinition,
        support_id=support_id,
        description=description,
        url=url,
        entity_label="release",
    )


# ---------------------------------------------------------------------------
# ComponentRelease-level convenience wrappers
# ---------------------------------------------------------------------------


def create_component_release_cle_event(
    component_release: ComponentRelease,
    event_type: str,
    effective: datetime,
    *,
    version: str = "",
    versions: list[dict[str, Any]] | None = None,
    support_id: str = "",
    license: str = "",
    superseded_by_version: str = "",
    identifiers: list[dict[str, Any]] | None = None,
    withdrawn_event_id: int | None = None,
    reason: str = "",
    description: str = "",
    references: list[str] | None = None,
) -> ServiceResult[ComponentReleaseCLEEvent]:
    """Create a new CLE lifecycle event for a component release."""
    return create_cle_event_generic(
        entity=component_release,
        entity_fk_field="component_release",
        event_model=ComponentReleaseCLEEvent,
        support_def_model=ComponentReleaseCLESupportDefinition,
        event_type=event_type,
        effective=effective,
        entity_label="component release",
        version=version,
        versions=versions,
        support_id=support_id,
        license=license,
        superseded_by_version=superseded_by_version,
        identifiers=identifiers,
        withdrawn_event_id=withdrawn_event_id,
        reason=reason,
        description=description,
        references=references,
    )


def create_component_release_support_definition(
    component_release: ComponentRelease,
    support_id: str,
    description: str,
    url: str = "",
) -> ServiceResult[ComponentReleaseCLESupportDefinition]:
    """Create a named support tier definition for a component release."""
    return create_support_definition_generic(
        entity=component_release,
        entity_fk_field="component_release",
        support_def_model=ComponentReleaseCLESupportDefinition,
        support_id=support_id,
        description=description,
        url=url,
        entity_label="component release",
    )


def recompute_lifecycle_dates(product: Product) -> None:
    """Recompute cached lifecycle date fields on the product from CLE events.

    Iterates all events in event_id order, skips withdrawn events, and sets
    ``release_date``, ``end_of_support``, and ``end_of_life`` on the product.

    Should be called within a ``transaction.atomic()`` block when used alongside
    event creation to ensure consistency.
    """
    events = list(ProductCLEEvent.objects.filter(product=product).order_by("event_id"))

    # Collect IDs of events that have been withdrawn.
    withdrawn_ids: set[int] = {
        event.withdrawn_event_id
        for event in events
        if event.event_type == ProductCLEEvent.EventType.WITHDRAWN and event.withdrawn_event_id is not None
    }

    release_date: date | None = None
    end_of_support: date | None = None
    end_of_life: date | None = None

    for event in events:
        if event.event_id in withdrawn_ids:
            continue

        if event.event_type == ProductCLEEvent.EventType.RELEASED:
            release_date = event.effective.date()
        elif event.event_type == ProductCLEEvent.EventType.END_OF_SUPPORT:
            end_of_support = event.effective.date()
        elif event.event_type == ProductCLEEvent.EventType.END_OF_LIFE:
            end_of_life = event.effective.date()

    product.release_date = release_date
    product.end_of_support = end_of_support
    product.end_of_life = end_of_life
    product.save(update_fields=["release_date", "end_of_support", "end_of_life"])


def _get_cle_document_generic(
    event_model: type[BaseCLEEvent],
    support_def_model: type[BaseCLESupportDefinition],
    entity_fk_field: str,
    entity: django_models.Model,
) -> ServiceResult[CLE]:
    """Build a libtea CLE document from events and definitions for any entity level."""
    filter_kwargs = {entity_fk_field: entity}
    events = event_model.objects.filter(**filter_kwargs).order_by("-event_id")  # type: ignore[attr-defined]

    if not events.exists():
        return ServiceResult.failure("No CLE events", status_code=404)

    try:
        tea_events = tuple(_to_libtea_event(e) for e in events)
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Failed to convert CLE events to libtea format for %s %s", entity_fk_field, entity.pk)
        return ServiceResult.failure(f"CLE conversion error: {exc}", status_code=500)

    definitions: CLEDefinitions | None = None
    support_defs = support_def_model.objects.filter(**filter_kwargs)  # type: ignore[attr-defined]
    if support_defs.exists():
        definitions = CLEDefinitions(
            support=tuple(
                TeaCLESupportDefinition(
                    id=sd.support_id,
                    description=sd.description,
                    url=sd.url or None,
                )
                for sd in support_defs
            ),
        )

    return ServiceResult.success(CLE(events=tea_events, definitions=definitions))


def get_cle_document(product: Product) -> ServiceResult[CLE]:
    """Build a libtea CLE document from a product's CLE events and definitions."""
    return _get_cle_document_generic(ProductCLEEvent, ProductCLESupportDefinition, "product", product)


def get_component_cle_document(component: Component) -> ServiceResult[CLE]:
    """Build a libtea CLE document from a component's CLE events and definitions."""
    return _get_cle_document_generic(ComponentCLEEvent, ComponentCLESupportDefinition, "component", component)


def get_release_cle_document(release: Release) -> ServiceResult[CLE]:
    """Build a libtea CLE document from a release's CLE events and definitions."""
    return _get_cle_document_generic(ReleaseCLEEvent, ReleaseCLESupportDefinition, "release", release)


def get_component_release_cle_document(component_release: ComponentRelease) -> ServiceResult[CLE]:
    """Build a libtea CLE document from a component release's CLE events and definitions."""
    return _get_cle_document_generic(
        ComponentReleaseCLEEvent, ComponentReleaseCLESupportDefinition, "component_release", component_release
    )


def _to_libtea_event(event: BaseCLEEvent) -> TeaCLEEvent:
    """Convert a Django CLE event model instance to a libtea CLEEvent."""
    versions: tuple[CLEVersionSpecifier, ...] | None = None
    if event.versions:
        invalid_ver = next((v for v in event.versions if not isinstance(v, dict)), None)
        if invalid_ver is not None:
            msg = f"CLE event versions must contain only objects, got {type(invalid_ver).__name__}"
            raise ValueError(msg)
        versions = tuple(CLEVersionSpecifier(version=v.get("version"), range=v.get("range")) for v in event.versions)

    identifiers: tuple[Identifier, ...] | None = None
    if event.identifiers:
        invalid_ident = next((i for i in event.identifiers if not isinstance(i, dict)), None)
        if invalid_ident is not None:
            msg = f"CLE event identifiers must contain only objects, got {type(invalid_ident).__name__}"
            raise ValueError(msg)
        identifiers = tuple(
            Identifier(id_type=i.get("type", ""), id_value=i.get("value", "")) for i in event.identifiers
        )

    references: tuple[str, ...] | None = None
    if event.references:
        invalid_ref = next((r for r in event.references if not isinstance(r, str)), None)
        if invalid_ref is not None:
            msg = f"CLE event references must contain only strings, got {type(invalid_ref).__name__}"
            raise ValueError(msg)
        references = tuple(event.references)

    try:
        event_type = CLEEventType(event.event_type)
    except ValueError:
        logger.warning(
            "Unknown CLE event type '%s' in event %s; conversion cannot continue",
            event.event_type,
            event.event_id,
        )
        raise

    return TeaCLEEvent(
        id=event.event_id,
        type=event_type,
        effective=event.effective,
        published=event.published,
        version=event.version or None,
        versions=versions,
        support_id=event.support_id or None,
        license=event.license or None,
        superseded_by_version=event.superseded_by_version or None,
        identifiers=identifiers,
        # libtea's event_id field is the ECMA-428 "withdrawn" event reference, not the sequence number
        event_id=event.withdrawn_event_id,
        reason=event.reason or None,
        description=event.description or None,
        references=references,
    )
