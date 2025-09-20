"""Integration tests for license APIs."""

import pytest
from django.test import Client

from sbomify.apps.core.tests.shared_fixtures import authenticated_api_client, get_api_headers


@pytest.mark.django_db
def test_integration_licenses_endpoint_via_http(authenticated_api_client):
    """Test the full API endpoint via HTTP."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    response = client.get("/api/v1/licensing/licenses", **headers)
    assert response.status_code == 200

    licenses = response.json()
    assert len(licenses) >= 520

    # Verify some key SPDX licenses exist
    license_keys = {license["key"] for license in licenses}
    assert "MIT" in license_keys
    assert "Apache-2.0" in license_keys
    assert "GPL-3.0-only" in license_keys  # GPL-3.0 is now GPL-3.0-only in newer SPDX versions

    # Check that we have both SPDX and custom licenses
    spdx_licenses = [l for l in licenses if l["origin"] == "SPDX"]
    custom_licenses = [l for l in licenses if l["origin"] != "SPDX"]

    assert len(spdx_licenses) >= 500  # Should have many SPDX licenses
    assert len(custom_licenses) >= 10  # Should have some custom licenses

    # Check structure of SPDX license
    mit_license = next(l for l in licenses if l["key"] == "MIT")
    assert mit_license["name"] == "MIT"  # The actual name returned by the API
    assert mit_license["origin"] == "SPDX"
    assert "url" in mit_license  # URL field should exist (may be None)


@pytest.mark.django_db
def test_integration_validate_expression_endpoint_via_http(authenticated_api_client):
    """Test the validation endpoint via HTTP."""
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
def test_integration_validate_expression_with_unknown_token_via_http(authenticated_api_client):
    """Test validation with unknown token via HTTP."""
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
def test_integration_validate_expression_syntax_error_via_http(authenticated_api_client):
    """Test validation with syntax error via HTTP."""
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