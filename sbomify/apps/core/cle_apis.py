from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Query, Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.cle_schemas import (
    CLEEventCreateSchema,
    CLEEventResponseSchema,
    CLESupportDefinitionCreateSchema,
    CLESupportDefinitionResponseSchema,
)
from sbomify.apps.core.models import Component, ComponentRelease, Product, Release
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.core.services.cle import (
    create_cle_event,
    create_component_cle_event,
    create_component_release_cle_event,
    create_component_release_support_definition,
    create_component_support_definition,
    create_release_cle_event,
    create_release_support_definition,
    create_support_definition,
)
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import (
    ComponentCLEEvent,
    ComponentCLESupportDefinition,
    ComponentReleaseCLEEvent,
    ComponentReleaseCLESupportDefinition,
    ProductCLEEvent,
    ProductCLESupportDefinition,
    ReleaseCLEEvent,
    ReleaseCLESupportDefinition,
)

# CLE endpoints are append-only by design (ECMA-428 + ADR-004: immutable artifacts).
# Events are never updated or deleted — use the "withdrawn" event type to logically
# void a prior event. No DELETE or PUT endpoints are provided.
router = Router(tags=["CLE"], auth=(PersonalAccessTokenAuth(), django_auth))

_ERROR_CODE_BY_STATUS: dict[int, ErrorCode] = {
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _get_product_or_404(request: HttpRequest, product_id: str) -> Product | tuple[int, dict[str, Any]]:
    """Look up a product and verify owner/admin access.

    Returns the Product on success, or a (status, error_dict) tuple on failure.
    """
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return 404, {"detail": "Product not found", "error_code": ErrorCode.PRODUCT_NOT_FOUND}

    if not verify_item_access(request, product, ["owner", "admin"]):
        return 403, {"detail": "Permission denied", "error_code": ErrorCode.FORBIDDEN}

    return product


def _get_component_or_404(request: HttpRequest, component_id: str) -> Component | tuple[int, dict[str, Any]]:
    """Look up a component and verify owner/admin access.

    Returns the Component on success, or a (status, error_dict) tuple on failure.
    """
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Component not found", "error_code": ErrorCode.COMPONENT_NOT_FOUND}

    if not verify_item_access(request, component, ["owner", "admin"]):
        return 403, {"detail": "Permission denied", "error_code": ErrorCode.FORBIDDEN}

    return component


def _get_release_or_404(request: HttpRequest, release_id: str) -> Release | tuple[int, dict[str, Any]]:
    """Look up a release and verify owner/admin access via its product.

    Returns the Release on success, or a (status, error_dict) tuple on failure.
    """
    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        return 404, {"detail": "Release not found", "error_code": ErrorCode.RELEASE_NOT_FOUND}

    if not verify_item_access(request, release.product, ["owner", "admin"]):
        return 403, {"detail": "Permission denied", "error_code": ErrorCode.FORBIDDEN}

    return release


def _get_component_release_or_404(
    request: HttpRequest, component_release_id: str
) -> ComponentRelease | tuple[int, dict[str, Any]]:
    """Look up a component release and verify owner/admin access via its component.

    Returns the ComponentRelease on success, or a (status, error_dict) tuple on failure.
    """
    try:
        component_release = ComponentRelease.objects.select_related("component").get(pk=component_release_id)
    except ComponentRelease.DoesNotExist:
        return 404, {
            "detail": "Component release not found",
            "error_code": ErrorCode.COMPONENT_RELEASE_NOT_FOUND,
        }

    if not verify_item_access(request, component_release.component, ["owner", "admin"]):
        return 403, {"detail": "Permission denied", "error_code": ErrorCode.FORBIDDEN}

    return component_release


# ===========================================================================
# Product CLE endpoints
# ===========================================================================


@router.get(
    "/products/{product_id}/cle/events",
    response={200: list[CLEEventResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_cle_events(
    request: HttpRequest,
    product_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE events for a product (newest first)."""
    result = _get_product_or_404(request, product_id)
    if not isinstance(result, Product):
        return result

    events = ProductCLEEvent.objects.filter(product=result).order_by("-event_id")
    events = events[page_offset : page_offset + page_size]
    return 200, list(events)


@router.post(
    "/products/{product_id}/cle/events",
    response={201: CLEEventResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_cle_event_endpoint(request: HttpRequest, product_id: str, payload: CLEEventCreateSchema) -> Any:
    """Create a new CLE lifecycle event for a product."""
    result = _get_product_or_404(request, product_id)
    if not isinstance(result, Product):
        return result

    svc_result = create_cle_event(
        product=result,
        event_type=payload.event_type,
        effective=payload.effective,
        version=payload.version,
        versions=[v.model_dump() for v in payload.versions],
        support_id=payload.support_id,
        license=payload.license,
        superseded_by_version=payload.superseded_by_version,
        identifiers=[i.model_dump() for i in payload.identifiers],
        withdrawn_event_id=payload.withdrawn_event_id,
        reason=payload.reason,
        description=payload.description,
        references=payload.references,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


@router.get(
    "/products/{product_id}/cle/events/{event_id}",
    response={200: CLEEventResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_cle_event(request: HttpRequest, product_id: str, event_id: int) -> Any:
    """Get a single CLE event by event_id."""
    result = _get_product_or_404(request, product_id)
    if not isinstance(result, Product):
        return result

    try:
        event = ProductCLEEvent.objects.get(product=result, event_id=event_id)
    except ProductCLEEvent.DoesNotExist:
        return 404, {"detail": "CLE event not found", "error_code": ErrorCode.NOT_FOUND}

    return 200, event


@router.get(
    "/products/{product_id}/cle/support-definitions",
    response={200: list[CLESupportDefinitionResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_cle_support_definitions(
    request: HttpRequest,
    product_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE support definitions for a product."""
    result = _get_product_or_404(request, product_id)
    if not isinstance(result, Product):
        return result

    definitions = ProductCLESupportDefinition.objects.filter(product=result).order_by("support_id")
    definitions = definitions[page_offset : page_offset + page_size]
    return 200, list(definitions)


@router.post(
    "/products/{product_id}/cle/support-definitions",
    response={
        201: CLESupportDefinitionResponseSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def create_cle_support_definition_endpoint(
    request: HttpRequest, product_id: str, payload: CLESupportDefinitionCreateSchema
) -> Any:
    """Create a new CLE support definition for a product."""
    result = _get_product_or_404(request, product_id)
    if not isinstance(result, Product):
        return result

    svc_result = create_support_definition(
        product=result,
        support_id=payload.support_id,
        description=payload.description,
        url=payload.url,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


# ===========================================================================
# Component CLE endpoints
# ===========================================================================


@router.get(
    "/components/{component_id}/cle/events",
    response={200: list[CLEEventResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_component_cle_events(
    request: HttpRequest,
    component_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE events for a component (newest first)."""
    result = _get_component_or_404(request, component_id)
    if not isinstance(result, Component):
        return result

    events = ComponentCLEEvent.objects.filter(component=result).order_by("-event_id")
    events = events[page_offset : page_offset + page_size]
    return 200, list(events)


@router.post(
    "/components/{component_id}/cle/events",
    response={201: CLEEventResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_component_cle_event_endpoint(request: HttpRequest, component_id: str, payload: CLEEventCreateSchema) -> Any:
    """Create a new CLE lifecycle event for a component."""
    result = _get_component_or_404(request, component_id)
    if not isinstance(result, Component):
        return result

    svc_result = create_component_cle_event(
        component=result,
        event_type=payload.event_type,
        effective=payload.effective,
        version=payload.version,
        versions=[v.model_dump() for v in payload.versions],
        support_id=payload.support_id,
        license=payload.license,
        superseded_by_version=payload.superseded_by_version,
        identifiers=[i.model_dump() for i in payload.identifiers],
        withdrawn_event_id=payload.withdrawn_event_id,
        reason=payload.reason,
        description=payload.description,
        references=payload.references,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


@router.get(
    "/components/{component_id}/cle/events/{event_id}",
    response={200: CLEEventResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_component_cle_event(request: HttpRequest, component_id: str, event_id: int) -> Any:
    """Get a single CLE event for a component by event_id."""
    result = _get_component_or_404(request, component_id)
    if not isinstance(result, Component):
        return result

    try:
        event = ComponentCLEEvent.objects.get(component=result, event_id=event_id)
    except ComponentCLEEvent.DoesNotExist:
        return 404, {"detail": "CLE event not found", "error_code": ErrorCode.NOT_FOUND}

    return 200, event


@router.get(
    "/components/{component_id}/cle/support-definitions",
    response={200: list[CLESupportDefinitionResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_component_cle_support_definitions(
    request: HttpRequest,
    component_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE support definitions for a component."""
    result = _get_component_or_404(request, component_id)
    if not isinstance(result, Component):
        return result

    definitions = ComponentCLESupportDefinition.objects.filter(component=result).order_by("support_id")
    definitions = definitions[page_offset : page_offset + page_size]
    return 200, list(definitions)


@router.post(
    "/components/{component_id}/cle/support-definitions",
    response={
        201: CLESupportDefinitionResponseSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def create_component_cle_support_definition_endpoint(
    request: HttpRequest, component_id: str, payload: CLESupportDefinitionCreateSchema
) -> Any:
    """Create a new CLE support definition for a component."""
    result = _get_component_or_404(request, component_id)
    if not isinstance(result, Component):
        return result

    svc_result = create_component_support_definition(
        component=result,
        support_id=payload.support_id,
        description=payload.description,
        url=payload.url,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


# ===========================================================================
# Release CLE endpoints
# ===========================================================================


@router.get(
    "/releases/{release_id}/cle/events",
    response={200: list[CLEEventResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_release_cle_events(
    request: HttpRequest,
    release_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE events for a release (newest first)."""
    result = _get_release_or_404(request, release_id)
    if not isinstance(result, Release):
        return result

    events = ReleaseCLEEvent.objects.filter(release=result).order_by("-event_id")
    events = events[page_offset : page_offset + page_size]
    return 200, list(events)


@router.post(
    "/releases/{release_id}/cle/events",
    response={201: CLEEventResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_release_cle_event_endpoint(request: HttpRequest, release_id: str, payload: CLEEventCreateSchema) -> Any:
    """Create a new CLE lifecycle event for a release."""
    result = _get_release_or_404(request, release_id)
    if not isinstance(result, Release):
        return result

    svc_result = create_release_cle_event(
        release=result,
        event_type=payload.event_type,
        effective=payload.effective,
        version=payload.version,
        versions=[v.model_dump() for v in payload.versions],
        support_id=payload.support_id,
        license=payload.license,
        superseded_by_version=payload.superseded_by_version,
        identifiers=[i.model_dump() for i in payload.identifiers],
        withdrawn_event_id=payload.withdrawn_event_id,
        reason=payload.reason,
        description=payload.description,
        references=payload.references,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


@router.get(
    "/releases/{release_id}/cle/events/{event_id}",
    response={200: CLEEventResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_release_cle_event(request: HttpRequest, release_id: str, event_id: int) -> Any:
    """Get a single CLE event for a release by event_id."""
    result = _get_release_or_404(request, release_id)
    if not isinstance(result, Release):
        return result

    try:
        event = ReleaseCLEEvent.objects.get(release=result, event_id=event_id)
    except ReleaseCLEEvent.DoesNotExist:
        return 404, {"detail": "CLE event not found", "error_code": ErrorCode.NOT_FOUND}

    return 200, event


@router.get(
    "/releases/{release_id}/cle/support-definitions",
    response={200: list[CLESupportDefinitionResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_release_cle_support_definitions(
    request: HttpRequest,
    release_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE support definitions for a release."""
    result = _get_release_or_404(request, release_id)
    if not isinstance(result, Release):
        return result

    definitions = ReleaseCLESupportDefinition.objects.filter(release=result).order_by("support_id")
    definitions = definitions[page_offset : page_offset + page_size]
    return 200, list(definitions)


@router.post(
    "/releases/{release_id}/cle/support-definitions",
    response={
        201: CLESupportDefinitionResponseSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def create_release_cle_support_definition_endpoint(
    request: HttpRequest, release_id: str, payload: CLESupportDefinitionCreateSchema
) -> Any:
    """Create a new CLE support definition for a release."""
    result = _get_release_or_404(request, release_id)
    if not isinstance(result, Release):
        return result

    svc_result = create_release_support_definition(
        release=result,
        support_id=payload.support_id,
        description=payload.description,
        url=payload.url,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


# ===========================================================================
# ComponentRelease CLE endpoints
# ===========================================================================


@router.get(
    "/component-releases/{component_release_id}/cle/events",
    response={200: list[CLEEventResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_component_release_cle_events(
    request: HttpRequest,
    component_release_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE events for a component release (newest first)."""
    result = _get_component_release_or_404(request, component_release_id)
    if not isinstance(result, ComponentRelease):
        return result

    events = ComponentReleaseCLEEvent.objects.filter(component_release=result).order_by("-event_id")
    events = events[page_offset : page_offset + page_size]
    return 200, list(events)


@router.post(
    "/component-releases/{component_release_id}/cle/events",
    response={201: CLEEventResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_component_release_cle_event_endpoint(
    request: HttpRequest, component_release_id: str, payload: CLEEventCreateSchema
) -> Any:
    """Create a new CLE lifecycle event for a component release."""
    result = _get_component_release_or_404(request, component_release_id)
    if not isinstance(result, ComponentRelease):
        return result

    svc_result = create_component_release_cle_event(
        component_release=result,
        event_type=payload.event_type,
        effective=payload.effective,
        version=payload.version,
        versions=[v.model_dump() for v in payload.versions],
        support_id=payload.support_id,
        license=payload.license,
        superseded_by_version=payload.superseded_by_version,
        identifiers=[i.model_dump() for i in payload.identifiers],
        withdrawn_event_id=payload.withdrawn_event_id,
        reason=payload.reason,
        description=payload.description,
        references=payload.references,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value


@router.get(
    "/component-releases/{component_release_id}/cle/events/{event_id}",
    response={200: CLEEventResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_component_release_cle_event(request: HttpRequest, component_release_id: str, event_id: int) -> Any:
    """Get a single CLE event for a component release by event_id."""
    result = _get_component_release_or_404(request, component_release_id)
    if not isinstance(result, ComponentRelease):
        return result

    try:
        event = ComponentReleaseCLEEvent.objects.get(component_release=result, event_id=event_id)
    except ComponentReleaseCLEEvent.DoesNotExist:
        return 404, {"detail": "CLE event not found", "error_code": ErrorCode.NOT_FOUND}

    return 200, event


@router.get(
    "/component-releases/{component_release_id}/cle/support-definitions",
    response={200: list[CLESupportDefinitionResponseSchema], 403: ErrorResponse, 404: ErrorResponse},
)
def list_component_release_cle_support_definitions(
    request: HttpRequest,
    component_release_id: str,
    page_offset: int = Query(0, ge=0, alias="pageOffset"),  # type: ignore[type-arg]
    page_size: int = Query(100, ge=1, le=1000, alias="pageSize"),  # type: ignore[type-arg]
) -> Any:
    """List CLE support definitions for a component release."""
    result = _get_component_release_or_404(request, component_release_id)
    if not isinstance(result, ComponentRelease):
        return result

    definitions = ComponentReleaseCLESupportDefinition.objects.filter(component_release=result).order_by("support_id")
    definitions = definitions[page_offset : page_offset + page_size]
    return 200, list(definitions)


@router.post(
    "/component-releases/{component_release_id}/cle/support-definitions",
    response={
        201: CLESupportDefinitionResponseSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
    },
)
def create_component_release_cle_support_definition_endpoint(
    request: HttpRequest, component_release_id: str, payload: CLESupportDefinitionCreateSchema
) -> Any:
    """Create a new CLE support definition for a component release."""
    result = _get_component_release_or_404(request, component_release_id)
    if not isinstance(result, ComponentRelease):
        return result

    svc_result = create_component_release_support_definition(
        component_release=result,
        support_id=payload.support_id,
        description=payload.description,
        url=payload.url,
    )

    if not svc_result.ok:
        status = svc_result.status_code or 400
        error_code = _ERROR_CODE_BY_STATUS.get(status, ErrorCode.BAD_REQUEST)
        return status, {"detail": svc_result.error, "error_code": error_code}

    return 201, svc_result.value
