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

    # Check structure of first license
    first_license = licenses[0]
    assert "key" in first_license
    assert "name" in first_license
    assert "category" in first_license
    assert "origin" in first_license
    assert first_license["origin"] in ["SPDX", "Custom"]

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