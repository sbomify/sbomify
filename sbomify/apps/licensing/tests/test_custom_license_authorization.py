"""The licence catalogue ships with the app and no API call changes it.

The custom-licence endpoint let any signed-in caller write into the catalogue
file inside the app package and reload the table every workspace reads, and a
custom key replaced the SPDX licence of the same id. Nothing in the app called
it, so it is gone.
"""

from __future__ import annotations

import json

import pytest

from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.licensing import loader

pytestmark = pytest.mark.django_db


def test_no_api_call_changes_the_licence_catalogue(authenticated_api_client):
    client, access_token = authenticated_api_client
    before = loader.load_custom_licenses()

    response = client.post(
        "/api/v1/licensing/custom-licenses",
        json.dumps({"key": "MIT", "name": "Not MIT"}),
        content_type="application/json",
        **get_api_headers(access_token),
    )

    assert response.status_code == 404
    assert loader.load_custom_licenses() == before
    assert "MIT" not in loader.CUSTOM_SYMBOLS
