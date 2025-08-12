"""Unit tests for the license API endpoints."""

import pytest
from django.test import Client
from ninja.testing import TestClient

from core.tests.shared_fixtures import authenticated_api_client, get_api_headers
from ..api import router

client = TestClient(router)


@pytest.mark.django_db
def test_list_licenses(authenticated_api_client):
    """Test the GET /licensing/licenses endpoint."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    response = client.get("/api/v1/licensing/licenses", **headers)
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
        assert "url" in spdx_license

    # Check custom license structure
    if custom_licenses:
        custom_license = custom_licenses[0]
        assert "key" in custom_license
        assert "name" in custom_license
        assert "origin" in custom_license
        assert "url" in custom_license


@pytest.mark.django_db
def test_validate_expression_valid(authenticated_api_client):
    """Test validating a valid license expression."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    import json

    payload = {"expression": "MIT"}
    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data=json.dumps(payload),
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert result["normalized"] == "MIT"
    assert len(result["tokens"]) == 1
    assert result["tokens"][0]["key"] == "MIT"
    assert result["tokens"][0]["known"] is True


@pytest.mark.django_db
def test_validate_expression_complex(authenticated_api_client):
    """Test validating a complex license expression."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    import json

    payload = {"expression": "MIT AND (Apache-2.0 OR GPL-3.0)"}
    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data=json.dumps(payload),
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert "MIT" in result["normalized"]
    assert "Apache-2.0" in result["normalized"]
    assert "GPL-3.0" in result["normalized"]
    assert len(result["tokens"]) == 3

    # Check that all tokens are known
    for token in result["tokens"]:
        assert token["known"] is True


@pytest.mark.django_db
def test_validate_expression_unknown_token(authenticated_api_client):
    """Test validating an expression with unknown license token."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    import json

    payload = {"expression": "MIT AND UnknownLicense"}
    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data=json.dumps(payload),
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 200
    assert "MIT" in result["normalized"]
    assert "UnknownLicense" in result["normalized"]
    assert len(result["tokens"]) == 2

    # Check MIT is known, UnknownLicense is not
    mit_token = next(t for t in result["tokens"] if t["key"] == "MIT")
    unknown_token = next(t for t in result["tokens"] if t["key"] == "UnknownLicense")
    assert mit_token["known"] is True
    assert unknown_token["known"] is False


@pytest.mark.django_db
def test_validate_expression_syntax_error(authenticated_api_client):
    """Test validating an expression with syntax errors."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    import json

    payload = {"expression": "MIT AND ("}
    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data=json.dumps(payload),
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200

    result = response.json()
    assert result["status"] == 400
    assert "error" in result
    assert "processing error" in result["error"].lower()


@pytest.mark.django_db
def test_validate_expression_invalid_request(authenticated_api_client):
    """Test validating with invalid request format."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    import json

    # Missing expression field
    payload = {}
    response = client.post(
        "/api/v1/licensing/license-expressions/validate",
        data=json.dumps(payload),
        content_type="application/json",
        **headers
    )
    assert response.status_code == 422  # Validation error