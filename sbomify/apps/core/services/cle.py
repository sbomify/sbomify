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
from sbomify.apps.sboms.models import Product as ProductModel
from sbomify.apps.sboms.models import ProductCLEEvent, ProductCLESupportDefinition

if TYPE_CHECKING:
    from sbomify.apps.sboms.models import Product

logger = logging.getLogger(__name__)

# Event types that require a non-empty `versions` list.
_VERSIONS_REQUIRED = frozenset(
    {
        ProductCLEEvent.EventType.END_OF_DEVELOPMENT,
        ProductCLEEvent.EventType.END_OF_SUPPORT,
        ProductCLEEvent.EventType.END_OF_LIFE,
        ProductCLEEvent.EventType.END_OF_DISTRIBUTION,
        ProductCLEEvent.EventType.END_OF_MARKETING,
    }
)

# Event types that additionally require `support_id`.
_SUPPORT_ID_CHECKED = frozenset(
    {
        ProductCLEEvent.EventType.END_OF_DEVELOPMENT,
        ProductCLEEvent.EventType.END_OF_SUPPORT,
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

    if len(identifiers) > _MAX_IDENTIFIERS:
        return f"identifiers list exceeds maximum of {_MAX_IDENTIFIERS} entries"
    for i, ident in enumerate(identifiers):
        if not isinstance(ident, dict):
            return f"identifiers[{i}] must be a dict, got {type(ident).__name__}"
        if not ident.get("type") or not ident.get("value"):
            return f"identifiers[{i}] must contain non-empty 'type' and 'value'"

    if len(references) > _MAX_REFERENCES:
        return f"references list exceeds maximum of {_MAX_REFERENCES} entries"
    for i, ref in enumerate(references):
        if not isinstance(ref, str):
            return f"references[{i}] must be a string, got {type(ref).__name__}"

    return None


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
    versions = versions or []
    identifiers = identifiers or []
    references = references or []

    # Validate event_type
    valid_types = {choice.value for choice in ProductCLEEvent.EventType}
    if event_type not in valid_types:
        return ServiceResult.failure(f"Invalid event type: {event_type}", status_code=400)

    # Validate JSON field structure
    json_error = _validate_json_fields(versions, identifiers, references)
    if json_error is not None:
        return ServiceResult.failure(json_error, status_code=400)

    # Per-type validation
    fields = {
        "version": version,
        "versions": versions,
        "support_id": support_id,
        "superseded_by_version": superseded_by_version,
        "identifiers": identifiers,
        "withdrawn_event_id": withdrawn_event_id,
    }
    validation_error = _validate_event_fields(product, event_type, fields)
    if validation_error is not None:
        return ServiceResult.failure(validation_error, status_code=400)

    with transaction.atomic():
        # Lock the product row to serialize concurrent event creation
        locked_product = ProductModel.objects.select_for_update().filter(pk=product.pk).first()
        if locked_product is None:
            return ServiceResult.failure("Product no longer exists", status_code=404)

        # Auto-assign next event_id
        max_id = ProductCLEEvent.objects.filter(product=product).aggregate(Max("event_id"))["event_id__max"]
        next_id: int = (max_id or 0) + 1

        event = ProductCLEEvent.objects.create(
            product=product,
            event_id=next_id,
            event_type=event_type,
            effective=effective,
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

        recompute_lifecycle_dates(locked_product)

    return ServiceResult.success(event)


def _validate_event_fields(product: Product, event_type: str, fields: dict[str, Any]) -> str | None:
    """Return an error message if required fields are missing, else None."""
    if event_type == ProductCLEEvent.EventType.RELEASED:
        pass  # version is recommended but not enforced (UI may set date without version)

    elif event_type in _VERSIONS_REQUIRED:
        versions = fields.get("versions")
        if not versions:
            return f"{event_type} events require a non-empty 'versions' list"

        if event_type in _SUPPORT_ID_CHECKED:
            support_id = fields.get("support_id")
            if (
                support_id
                and not ProductCLESupportDefinition.objects.filter(product=product, support_id=support_id).exists()
            ):
                return f"Support definition '{support_id}' does not exist for this product"

    elif event_type == ProductCLEEvent.EventType.SUPERSEDED_BY:
        if not fields.get("superseded_by_version"):
            return "supersededBy events require a non-empty 'superseded_by_version'"

    elif event_type == ProductCLEEvent.EventType.COMPONENT_RENAMED:
        if not fields.get("identifiers"):
            return "componentRenamed events require a non-empty 'identifiers' list"

    elif event_type == ProductCLEEvent.EventType.WITHDRAWN:
        withdrawn_event_id = fields.get("withdrawn_event_id")
        if withdrawn_event_id is None:
            return "withdrawn events require 'withdrawn_event_id'"
        if not ProductCLEEvent.objects.filter(product=product, event_id=withdrawn_event_id).exists():
            return f"Referenced event_id {withdrawn_event_id} does not exist for this product"

    return None


def create_support_definition(
    product: Product,
    support_id: str,
    description: str,
    url: str = "",
) -> ServiceResult[ProductCLESupportDefinition]:
    """Create a named support tier definition for a product."""
    try:
        with transaction.atomic():
            definition = ProductCLESupportDefinition.objects.create(
                product=product,
                support_id=support_id,
                description=description,
                url=url,
            )
    except IntegrityError:
        return ServiceResult.failure(
            f"Support definition '{support_id}' already exists for this product",
            status_code=409,
        )

    return ServiceResult.success(definition)


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


def get_cle_document(product: Product) -> ServiceResult[CLE]:
    """Build a libtea CLE document from a product's CLE events and definitions."""
    events = ProductCLEEvent.objects.filter(product=product).order_by("-event_id")

    if not events.exists():
        return ServiceResult.failure("No CLE events", status_code=404)

    try:
        tea_events = tuple(_to_libtea_event(e) for e in events)
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Failed to convert CLE events to libtea format for product %s", product.pk)
        return ServiceResult.failure(f"CLE conversion error: {exc}", status_code=500)

    definitions: CLEDefinitions | None = None
    support_defs = ProductCLESupportDefinition.objects.filter(product=product)
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


def _to_libtea_event(event: ProductCLEEvent) -> TeaCLEEvent:
    """Convert a Django ProductCLEEvent to a libtea CLEEvent."""
    versions: tuple[CLEVersionSpecifier, ...] | None = None
    if event.versions:
        versions = tuple(
            CLEVersionSpecifier(
                version=v.get("version") if isinstance(v, dict) else None,
                range=v.get("range") if isinstance(v, dict) else None,
            )
            for v in event.versions
            if isinstance(v, dict)
        )

    identifiers: tuple[Identifier, ...] | None = None
    if event.identifiers:
        identifiers = tuple(
            Identifier(
                id_type=i.get("type", "") if isinstance(i, dict) else "",
                id_value=i.get("value", "") if isinstance(i, dict) else "",
            )
            for i in event.identifiers
            if isinstance(i, dict)
        )

    references: tuple[str, ...] | None = None
    if event.references:
        references = tuple(str(r) for r in event.references)

    try:
        event_type = CLEEventType(event.event_type)
    except ValueError:
        logger.warning("Unknown CLE event type '%s' in event %s, skipping", event.event_type, event.event_id)
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
