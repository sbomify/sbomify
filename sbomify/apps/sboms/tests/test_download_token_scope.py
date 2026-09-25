"""Downloading an SBOM with an API token honours the token's scope.

The download authorizes through can(), as the other download routes do, so a
token without read scope gets 403 on a private SBOM. On a gated SBOM the denial
points at an access request only when approving one would lift it, and approval
never widens a token's scope.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db


def _sbom(team: Team, visibility: str) -> SBOM:
    component = Component.objects.create(name="app", team=team, visibility=visibility)
    return SBOM.objects.create(
        name="app", component=component, format="cyclonedx", format_version="1.6", sbom_filename="app.json"
    )


@pytest.fixture
def private_sbom(team_with_business_plan) -> SBOM:
    return _sbom(team_with_business_plan, Component.Visibility.PRIVATE)


@pytest.fixture
def gated_sbom(sample_team) -> SBOM:
    # sample_team has no members, so the token's user holds no grant on it.
    return _sbom(sample_team, Component.Visibility.GATED)


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


def test_an_anonymous_reader_is_asked_to_request_access_to_a_gated_sbom(client, gated_sbom):
    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": gated_sbom.id}))

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied. Please request access to download this SBOM."


def test_a_read_scoped_token_without_a_grant_is_pointed_at_an_access_request(authenticated_api_client, gated_sbom):
    response = _download(authenticated_api_client, gated_sbom, SCOPE_PRESETS["read_only"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied. Your access request is pending approval or has been rejected."


def test_a_publish_only_token_is_not_pointed_at_an_access_request(authenticated_api_client, gated_sbom):
    response = _download(authenticated_api_client, gated_sbom, SCOPE_PRESETS["publish"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_a_token_bound_to_another_workspace_is_not_pointed_at_an_access_request(
    authenticated_api_client, gated_sbom, team_with_business_plan
):
    _, token = authenticated_api_client
    token.team = team_with_business_plan
    token.save(update_fields=["team"])

    response = _download(authenticated_api_client, gated_sbom, SCOPE_PRESETS["read_only"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
