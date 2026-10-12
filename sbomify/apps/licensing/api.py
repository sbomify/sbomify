"""License API endpoints for listing and validating licenses."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth

from .loader import get_license_list, validate_expression

router = Router(tags=["Licensing"], auth=(PersonalAccessTokenAuth(), django_auth))


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
    tokens: list[TokenSchema] | None = None
    unknown_tokens: list[str] | None = None
    error: str | None = None


@router.get("/licenses")
def list_licenses(request: HttpRequest) -> list[dict[str, Any]]:
    """Get a list of all available licenses."""
    return get_license_list()


@router.post("/license-expressions/validate", response=ValidationResponseSchema)
def validate_license_expression(request: HttpRequest, data: ValidationRequestSchema) -> dict[str, Any]:
    """Validate a license expression and return detailed information."""
    return validate_expression(data.expression)
