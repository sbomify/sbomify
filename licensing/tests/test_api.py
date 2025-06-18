"""Unit tests for the license API endpoints."""

import pytest
from django.test import Client
from ninja.testing import TestClient

from ..api import router

client = TestClient(router)

def test_list_licenses():
    """Test the GET /licensing/licenses endpoint."""
    response = client.get("/licenses")
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

def test_validate_expression_valid():
    """Test the POST /licensing/license-expressions/validate endpoint with valid expressions."""
    # Test simple valid expression
    response = client.post("/license-expressions/validate", json={"expression": "Apache-2.0"})
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert result["normalized"] == "Apache-2.0"
    assert len(result["tokens"]) == 1
    assert not result["unknown_tokens"]

    # Test complex valid expression with custom license
    response = client.post(
        "/license-expressions/validate",
        json={"expression": "Apache-2.0 WITH Commons-Clause OR MIT"}
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert "Apache-2.0" in result["normalized"]
    assert "Commons-Clause" in result["normalized"]
    assert "MIT" in result["normalized"]
    assert len(result["tokens"]) == 3
    assert not result["unknown_tokens"]

def test_validate_expression_unknown_token():
    """Test the POST /licensing/license-expressions/validate endpoint with unknown tokens."""
    response = client.post(
        "/license-expressions/validate",
        json={"expression": "FooBar-1.0"}
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert result["normalized"] == "FooBar-1.0"
    assert len(result["tokens"]) == 1
    assert result["unknown_tokens"] == ["FooBar-1.0"]

def test_validate_expression_syntax_error():
    """Test the POST /licensing/license-expressions/validate endpoint with syntax errors."""
    response = client.post(
        "/license-expressions/validate",
        json={"expression": "Apache-2.0 AND ("}
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 400
    assert "error" in result
    assert "invalid" in result["error"].lower()

def test_validate_expression_invalid_request():
    """Test the POST /licensing/license-expressions/validate endpoint with invalid request."""
    response = client.post("/license-expressions/validate", json={})
    assert response.status_code == 422  # Validation error

def test_validate_expression_complex():
    """Test the POST /licensing/license-expressions/validate endpoint with complex expressions."""
    # Test complex expression with multiple operators
    response = client.post(
        "/license-expressions/validate",
        json={"expression": "(MIT OR Apache-2.0) AND (GPL-3.0 OR BSD-3-Clause)"}
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert "MIT" in result["normalized"]
    assert "Apache-2.0" in result["normalized"]
    assert "GPL-3.0" in result["normalized"]
    assert "BSD-3-Clause" in result["normalized"]
    assert len(result["tokens"]) == 4
    assert not result["unknown_tokens"]

    # Test complex expression with WITH operator
    response = client.post(
        "/license-expressions/validate",
        json={"expression": "Apache-2.0 WITH Commons-Clause OR MIT WITH Classpath-exception-2.0"}
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert "Apache-2.0" in result["normalized"]
    assert "Commons-Clause" in result["normalized"]
    assert "MIT" in result["normalized"]
    assert "Classpath-exception-2.0" in result["normalized"]
    assert len(result["tokens"]) == 4
    assert not result["unknown_tokens"]

    # Test complex expression with custom licenses
    response = client.post(
        "/license-expressions/validate",
        json={"expression": "(Apache-2.0 OR MIT) AND (ELv2 OR CCL-1.0)"}
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert "Apache-2.0" in result["normalized"]
    assert "MIT" in result["normalized"]
    assert "ELv2" in result["normalized"]
    assert "CCL-1.0" in result["normalized"]
    assert len(result["tokens"]) == 4
    assert not result["unknown_tokens"]