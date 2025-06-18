"""Integration tests for the license API endpoints via HTTP."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_integration_licenses_endpoint_via_http():
    """Test the GET /api/v1/licensing/licenses endpoint via HTTP."""
    client = Client()
    response = client.get("/api/v1/licensing/licenses")

    assert response.status_code == 200
    licenses = response.json()
    assert len(licenses) >= 520

    # Separate SPDX and custom licenses
    spdx_licenses = [l for l in licenses if l["origin"] == "SPDX"]
    custom_licenses = [l for l in licenses if l["origin"] != "SPDX"]

    # Check SPDX license structure (should not have category)
    if spdx_licenses:
        spdx_license = spdx_licenses[0]
        assert "key" in spdx_license
        assert "name" in spdx_license
        assert "origin" in spdx_license
        assert spdx_license["origin"] == "SPDX"
        assert "category" not in spdx_license

    # Check custom license structure (should have category)
    if custom_licenses:
        custom_license = custom_licenses[0]
        assert "key" in custom_license
        assert "name" in custom_license
        assert "category" in custom_license
        assert "origin" in custom_license
        assert custom_license["origin"] != "SPDX"


@pytest.mark.django_db
def test_integration_validate_expression_endpoint_via_http():
    """Test the POST /api/v1/licensing/license-expressions/validate endpoint via HTTP."""
    client = Client()

    # Test valid expression
    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
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
def test_integration_validate_expression_with_unknown_token_via_http():
    """Test validation with unknown token via HTTP."""
    client = Client()

    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data={"expression": "FooBar-1.0"},
        content_type="application/json"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == 200
    assert result["unknown_tokens"] == ["FooBar-1.0"]


@pytest.mark.django_db
def test_integration_validate_expression_syntax_error_via_http():
    """Test validation with syntax error via HTTP."""
    client = Client()

    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data={"expression": "Apache-2.0 AND ("},
        content_type="application/json"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == 400
    assert "error" in result