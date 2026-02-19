"""Service helpers for product identifiers HTMX views."""

from __future__ import annotations

from django.http import HttpRequest
from pydantic import ValidationError as PydanticValidationError

from sbomify.apps.core.apis import (
    create_product_identifier,
    delete_product_identifier,
    get_product,
    list_product_identifiers,
    update_product_identifier,
)
from sbomify.apps.core.schemas import ProductIdentifierCreateSchema, ProductIdentifierUpdateSchema
from sbomify.apps.core.services.results import ServiceResult, extract_pydantic_error_message

# Identifier types mapping
IDENTIFIER_TYPES = {
    "gtin_12": "GTIN-12 (UPC-A)",
    "gtin_13": "GTIN-13 (EAN-13)",
    "gtin_14": "GTIN-14 / ITF-14",
    "gtin_8": "GTIN-8",
    "sku": "SKU",
    "mpn": "MPN",
    "asin": "ASIN",
    "gs1_gpc_brick": "GS1 GPC Brick code",
    "cpe": "CPE",
    "purl": "PURL",
}

# Types that can render barcodes
BARCODE_TYPES = ["gtin_12", "gtin_13", "gtin_14", "gtin_8"]


def build_identifiers_context(request: HttpRequest, product_id: str) -> ServiceResult[dict]:
    status_code, product = get_product(request, product_id)
    if status_code != 200:
        return ServiceResult.failure("Product not found", status_code=status_code)

    status_code, identifiers_response = list_product_identifiers(request, product_id, page=1, page_size=100)
    identifiers = []
    if status_code == 200:
        identifiers = identifiers_response.get("items", [])

    current_team = request.session.get("current_team", {})
    billing_plan = current_team.get("billing_plan", "community")
    is_feature_allowed = billing_plan != "community"
    has_crud_permissions = product.get("has_crud_permissions", False)
    can_manage = has_crud_permissions and is_feature_allowed

    return ServiceResult.success(
        {
            "product": product,
            "identifiers": identifiers,
            "identifier_types": IDENTIFIER_TYPES,
            "barcode_types": BARCODE_TYPES,
            "has_crud_permissions": has_crud_permissions,
            "is_feature_allowed": is_feature_allowed,
            "can_manage_identifiers": can_manage,
        }
    )


def handle_identifiers_action(request: HttpRequest, product_id: str) -> ServiceResult[None]:
    action = request.POST.get("action")

    if action == "create":
        identifier_type = request.POST.get("identifier_type", "").strip()
        value = request.POST.get("value", "").strip()

        if not identifier_type or not value:
            return ServiceResult.failure("Both identifier type and value are required")

        try:
            payload = ProductIdentifierCreateSchema(identifier_type=identifier_type, value=value)
        except PydanticValidationError as e:
            msg = extract_pydantic_error_message(e)
            return ServiceResult.failure(msg)
        status_code, result = create_product_identifier(request, product_id, payload)
        if status_code != 201:
            return ServiceResult.failure(result.get("detail", "Failed to create identifier"), status_code=status_code)

    elif action == "update":
        identifier_id = request.POST.get("identifier_id", "").strip()
        identifier_type = request.POST.get("identifier_type", "").strip()
        value = request.POST.get("value", "").strip()

        if not identifier_id or not identifier_type or not value:
            return ServiceResult.failure("All fields are required")

        try:
            payload = ProductIdentifierUpdateSchema(identifier_type=identifier_type, value=value)
        except PydanticValidationError as e:
            msg = extract_pydantic_error_message(e)
            return ServiceResult.failure(msg)
        status_code, result = update_product_identifier(request, product_id, identifier_id, payload)
        if status_code != 200:
            return ServiceResult.failure(result.get("detail", "Failed to update identifier"), status_code=status_code)

    elif action == "delete":
        identifier_id = request.POST.get("identifier_id", "").strip()
        if not identifier_id:
            return ServiceResult.failure("Identifier ID is required")

        status_code, result = delete_product_identifier(request, product_id, identifier_id)
        if status_code != 204:
            return ServiceResult.failure(result.get("detail", "Failed to delete identifier"), status_code=status_code)

    return ServiceResult.success()
