"""Integration tests for the license API endpoints via HTTP."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_licenses_endpoint_via_http():
    """Test the GET /api/v1/licenses endpoint via HTTP."""
    client = Client()
    response = client.get("/api/v1/licenses")

    assert response.status_code == 200
    licenses = response.json()
    assert len(licenses) >= 520

    # Check structure of first license
    first_license = licenses[0]
    assert "key" in first_license
    assert "name" in first_license
    assert "category" in first_license
    assert "origin" in first_license
    assert first_license["origin"] in ["SPDX", "Custom"]


@pytest.mark.django_db
def test_validate_expression_endpoint_via_http():
    """Test the POST /api/v1/license-expressions/validate endpoint via HTTP."""
    client = Client()

    # Test valid expression
    response = client.post(
        "/api/v1/license-expressions/validate",
        data={"expression": "Apache-2.0"},
        content_type="application/json"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == 200
    assert result["normalized"] == "Apache-2.0"
    assert len(result["tokens"]) == 1
    assert not result["unknown_tokens"]


@pytest.mark.django_db
def test_validate_expression_with_unknown_token_via_http():
    """Test validation with unknown token via HTTP."""
    client = Client()

    response = client.post(
        "/api/v1/license-expressions/validate",
        data={"expression": "FooBar-1.0"},
        content_type="application/json"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == 200
    assert result["unknown_tokens"] == ["FooBar-1.0"]


@pytest.mark.django_db
def test_validate_expression_syntax_error_via_http():
    """Test validation with syntax error via HTTP."""
    client = Client()

    response = client.post(
        "/api/v1/license-expressions/validate",
        data={"expression": "Apache-2.0 AND ("},
        content_type="application/json"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == 400
    assert "error" in result