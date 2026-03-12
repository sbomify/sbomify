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
from sbomify.apps.core.models import Product
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.core.services.cle import create_cle_event, create_support_definition
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import ProductCLEEvent, ProductCLESupportDefinition

router = Router(tags=["CLE"], auth=(PersonalAccessTokenAuth(), django_auth))

_ERROR_CODE_BY_STATUS: dict[int, ErrorCode] = {
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
}


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


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Support Definitions
# ---------------------------------------------------------------------------


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

    definitions = ProductCLESupportDefinition.objects.filter(product=result)
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
