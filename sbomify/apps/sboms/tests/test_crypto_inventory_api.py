"""API tests for the derived crypto-inventory endpoint (#1001 increment 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from ..models import SBOM
from .fixtures import sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session

_DATA = Path(__file__).parent / "test_data"
_S3_TARGET = "sbomify.apps.sboms.services.sboms.S3Client"


def _url(sbom_id: str) -> str:
    return reverse("api-1:get_sbom_crypto_inventory", kwargs={"sbom_id": sbom_id})


def _mock_s3(mocker: MockerFixture, payload: bytes | None) -> None:
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = payload


def _owner_client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


@pytest.mark.django_db
def test_returns_derived_crypto_inventory(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    response = _owner_client(sample_sbom).get(_url(sample_sbom.id))

    assert response.status_code == 200
    body = response.json()
    assert body["sbom_id"] == sample_sbom.id
    assert body["count"] == 6
    assert body["by_asset_type"]["algorithm"] == 3
    names = {a["name"] for a in body["assets"]}
    assert "RSA-2048" in names
    assert "left-pad" not in names  # plain library excluded


@pytest.mark.django_db
def test_empty_inventory_for_non_crypto_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, json.dumps({"specVersion": "1.6", "components": [{"type": "library", "name": "x"}]}).encode())
    response = _owner_client(sample_sbom).get(_url(sample_sbom.id))

    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.django_db
def test_404_for_unknown_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, b"{}")
    response = _owner_client(sample_sbom).get(_url("doesnotexist1"))
    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [None, b""])
def test_404_when_artifact_missing_from_storage(
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,
    payload: bytes | None,
):
    # An empty object body is corruption/absence, not a crypto-free SBOM: 404, not an empty inventory.
    _mock_s3(mocker, payload)
    response = _owner_client(sample_sbom).get(_url(sample_sbom.id))
    assert response.status_code == 404


@pytest.mark.django_db
def test_403_for_private_sbom_without_access(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, b"{}")
    response = Client().get(_url(sample_sbom.id))  # no session, component is private
    assert response.status_code == 403


@pytest.mark.django_db
def test_invalid_utf8_artifact_yields_empty_inventory_not_500(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    # Corrupt (non-UTF-8) bytes must degrade to an empty inventory, never a 500.
    _mock_s3(mocker, b"\xff\xfe\x00not-valid-utf8")
    response = _owner_client(sample_sbom).get(_url(sample_sbom.id))
    assert response.status_code == 200
    assert response.json()["count"] == 0
