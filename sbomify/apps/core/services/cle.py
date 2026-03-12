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
_SUPPORT_ID_REQUIRED = frozenset(
    {
        ProductCLEEvent.EventType.END_OF_DEVELOPMENT,
        ProductCLEEvent.EventType.END_OF_SUPPORT,
    }
)


def create_cle_event(
    product: Product,
    event_type: str,
    effective: datetime,
    **kwargs: Any,
) -> ServiceResult[ProductCLEEvent]:
    """Create a new CLE lifecycle event for a product.

    Validates required fields per event type, auto-assigns the next event_id,
    and recomputes cached lifecycle dates on the product.
    """
    # Validate event_type
    valid_types = {choice.value for choice in ProductCLEEvent.EventType}
    if event_type not in valid_types:
        return ServiceResult.failure(f"Invalid event type: {event_type}", status_code=400)

    # Per-type validation
    validation_error = _validate_event_fields(product, event_type, kwargs)
    if validation_error is not None:
        return ServiceResult.failure(validation_error, status_code=400)

    # Auto-assign next event_id
    max_id = ProductCLEEvent.objects.filter(product=product).aggregate(Max("event_id"))["event_id__max"]
    next_id: int = (max_id or 0) + 1

    event = ProductCLEEvent.objects.create(
        product=product,
        event_id=next_id,
        event_type=event_type,
        effective=effective,
        version=kwargs.get("version", ""),
        versions=kwargs.get("versions", []),
        support_id=kwargs.get("support_id", ""),
        license=kwargs.get("license", ""),
        superseded_by_version=kwargs.get("superseded_by_version", ""),
        identifiers=kwargs.get("identifiers", []),
        withdrawn_event_id=kwargs.get("withdrawn_event_id"),
        reason=kwargs.get("reason", ""),
        description=kwargs.get("description", ""),
        references=kwargs.get("references", []),
    )

    recompute_lifecycle_dates(product)

    return ServiceResult.success(event)


def _validate_event_fields(product: Product, event_type: str, kwargs: dict[str, Any]) -> str | None:
    """Return an error message if required fields are missing, else None."""
    if event_type == ProductCLEEvent.EventType.RELEASED:
        version = kwargs.get("version")
        if not version:
            return "released events require a non-empty 'version'"

    elif event_type in _VERSIONS_REQUIRED:
        versions = kwargs.get("versions")
        if not versions:
            return f"{event_type} events require a non-empty 'versions' list"

        if event_type in _SUPPORT_ID_REQUIRED:
            support_id = kwargs.get("support_id")
            if not support_id:
                return f"{event_type} events require a non-empty 'support_id'"
            if not ProductCLESupportDefinition.objects.filter(product=product, support_id=support_id).exists():
                return f"Support definition '{support_id}' does not exist for this product"

    elif event_type == ProductCLEEvent.EventType.SUPERSEDED_BY:
        if not kwargs.get("superseded_by_version"):
            return "supersededBy events require a non-empty 'superseded_by_version'"

    elif event_type == ProductCLEEvent.EventType.COMPONENT_RENAMED:
        if not kwargs.get("identifiers"):
            return "componentRenamed events require a non-empty 'identifiers' list"

    elif event_type == ProductCLEEvent.EventType.WITHDRAWN:
        withdrawn_event_id = kwargs.get("withdrawn_event_id")
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
    """
    events = ProductCLEEvent.objects.filter(product=product).order_by("event_id")

    # Collect IDs of events that have been withdrawn.
    withdrawn_ids: set[int] = set()
    for event in events:
        if event.event_type == ProductCLEEvent.EventType.WITHDRAWN and event.withdrawn_event_id is not None:
            withdrawn_ids.add(event.withdrawn_event_id)

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

    tea_events = tuple(_to_libtea_event(e) for e in events)

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
                version=v.get("version"),
                range=v.get("range"),
            )
            for v in event.versions
        )

    identifiers: tuple[Identifier, ...] | None = None
    if event.identifiers:
        identifiers = tuple(
            Identifier(
                id_type=i.get("type", ""),
                id_value=i.get("value", ""),
            )
            for i in event.identifiers
        )

    references: tuple[str, ...] | None = None
    if event.references:
        references = tuple(event.references)

    return TeaCLEEvent(
        id=event.event_id,
        type=CLEEventType(event.event_type),
        effective=event.effective,
        published=event.published,
        version=event.version or None,
        versions=versions,
        support_id=event.support_id or None,
        license=event.license or None,
        superseded_by_version=event.superseded_by_version or None,
        identifiers=identifiers,
        event_id=event.withdrawn_event_id,
        reason=event.reason or None,
        description=event.description or None,
        references=references,
    )
