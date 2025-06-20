"""License API endpoints for listing and validating licenses."""

import os
from typing import Any, Dict, List

import yaml
from ninja import Router, Schema

from .loader import get_license_list, load_custom_licenses, validate_expression

router = Router()


class LicenseSchema(Schema):
    """Schema for license information."""

    key: str
    name: str
    origin: str
    url: str | None = None


class ValidationRequestSchema(Schema):
    """Schema for license expression validation request."""

    expression: str


class TokenSchema(Schema):
    """Schema for license token information."""

    key: str
    known: bool


class ValidationResponseSchema(Schema):
    """Schema for license expression validation response."""

    status: int
    normalized: str | None = None
    tokens: List[TokenSchema] | None = None
    unknown_tokens: List[str] | None = None
    error: str | None = None


class CustomLicenseRequestSchema(Schema):
    key: str
    name: str
    url: str | None = None
    text: str | None = None
    category: str = "proprietary"
    origin: str = "Custom"


@router.get("/licenses")
def list_licenses(request) -> List[Dict[str, Any]]:
    """Get a list of all available licenses."""
    return get_license_list()


@router.post("/license-expressions/validate", response=ValidationResponseSchema)
def validate_license_expression(request, data: ValidationRequestSchema) -> Dict[str, Any]:
    """Validate a license expression and return detailed information."""
    return validate_expression(data.expression)


@router.post("/custom-licenses")
def add_custom_license(request, data: CustomLicenseRequestSchema):
    """Add a custom license to the non_spdx.yaml file and reload."""
    yaml_path = os.path.join(os.path.dirname(__file__), "data", "non_spdx.yaml")
    # Load current custom licenses
    custom_licenses = load_custom_licenses()
    # Add or update the license
    custom_licenses[data.key] = {
        "name": data.name,
        "category": data.category,
        "origin": data.origin,
        "url": data.url,
        "text": data.text,
    }
    # Write back to YAML
    with open(yaml_path, "w") as f:
        yaml.dump(custom_licenses, f, sort_keys=False, allow_unicode=True)
    # Reload in-memory
    from . import loader

    loader.CUSTOM_SYMBOLS = load_custom_licenses()
    loader.ALL_LICENSES = {**loader.SPDX_SYMBOLS, **loader.CUSTOM_SYMBOLS}
    return custom_licenses[data.key]
