"""License API endpoints for listing and validating licenses."""

from typing import Any, Dict, List

from ninja import Router, Schema

from .loader import get_license_list, validate_expression

router = Router()


class LicenseSchema(Schema):
    """Schema for license information."""

    key: str
    name: str
    category: str
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
    category_summary: Dict[str, int] | None = None
    error: str | None = None


@router.get("/licenses", response=List[LicenseSchema])
def list_licenses(request) -> List[Dict[str, Any]]:
    """Get a list of all available licenses."""
    return get_license_list()


@router.post("/license-expressions/validate", response=ValidationResponseSchema)
def validate_license_expression(request, data: ValidationRequestSchema) -> Dict[str, Any]:
    """Validate a license expression and return detailed information."""
    return validate_expression(data.expression)
