"""Downloading an SBOM with an API token honours the token's scope.

The download authorizes through can(), as the other download routes do, so a
token without read scope gets 403 on a private SBOM.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM, Component

pytestmark = pytest.mark.django_db


@pytest.fixture
def private_sbom(team_with_business_plan) -> SBOM:
    component = Component.objects.create(
        name="app", team=team_with_business_plan, visibility=Component.Visibility.PRIVATE
    )
    return SBOM.objects.create(
        name="app", component=component, format="cyclonedx", format_version="1.6", sbom_filename="app.json"
    )


@pytest.fixture(autouse=True)
def storage():
    with patch("sbomify.apps.sboms.apis.StorageClient") as storage:
        storage.return_value.get_sbom_data.return_value = b'{"bomFormat": "CycloneDX"}'
        yield storage


def _download(authenticated_api_client, sbom: SBOM, scopes: list[str]):
    client, token = authenticated_api_client
    token.scopes = scopes
    token.save(update_fields=["scopes"])
    return client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sbom.id}), **get_api_headers(token))


def test_a_publish_only_token_cannot_download_a_private_sbom(authenticated_api_client, private_sbom):
    response = _download(authenticated_api_client, private_sbom, SCOPE_PRESETS["publish"])

    assert response.status_code == 403


def test_a_read_scoped_token_downloads_it(authenticated_api_client, private_sbom):
    response = _download(authenticated_api_client, private_sbom, SCOPE_PRESETS["read_only"])

    assert response.status_code == 200
