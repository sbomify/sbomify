"""Service helpers for the product custom metadata HTMX card.

Reads and writes go through the product API functions, so the card enforces
exactly the permission, validation and broadcast rules the public API does.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from sbomify.apps.core.apis import get_product, patch_product
from sbomify.apps.core.custom_metadata import CustomMetadataError, custom_metadata_from_pairs
from sbomify.apps.core.schemas import ProductPatchSchema
from sbomify.apps.core.services.results import ServiceResult


def build_custom_metadata_context(request: HttpRequest, product_id: str) -> ServiceResult[dict[str, Any]]:
    status_code, product = get_product(request, product_id)
    if status_code != 200:
        return ServiceResult.failure("Product not found", status_code=status_code)

    custom_metadata = product.get("custom_metadata") or {}
    return ServiceResult.success(
        {
            "product": product,
            "custom_metadata": custom_metadata,
            "custom_metadata_rows": [{"key": k, "value": v} for k, v in custom_metadata.items()],
            "can_edit": product.get("has_crud_permissions", False),
        }
    )


def save_custom_metadata(request: HttpRequest, product_id: str) -> ServiceResult[None]:
    try:
        pairs = custom_metadata_from_pairs(request.POST.getlist("meta_key"), request.POST.getlist("meta_value"))
    except CustomMetadataError as exc:
        return ServiceResult.failure(str(exc), status_code=400)

    status_code, result = patch_product(
        request, product_id, ProductPatchSchema.model_validate({"custom_metadata": pairs})
    )
    if status_code != 200:
        detail = result.get("detail") if isinstance(result, dict) else None
        return ServiceResult.failure(detail or "Failed to save custom metadata", status_code=status_code)
    return ServiceResult.success(None)
