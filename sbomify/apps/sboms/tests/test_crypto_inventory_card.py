"""Tests for the lazy-loaded crypto-inventory UI card (#1001 increment 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from ..models import SBOM, Component
from .fixtures import sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session

_DATA = Path(__file__).parent / "test_data"
_S3_TARGET = "sbomify.apps.sboms.services.sboms.S3Client"


def _card_url(sbom_id: str) -> str:
    return reverse("sboms:sbom_crypto_inventory", kwargs={"sbom_id": sbom_id})


def _mock_s3(mocker: MockerFixture, payload: bytes | None) -> None:
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = payload


def _owner_client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


@pytest.mark.django_db
def test_card_renders_for_cbom_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    response = _owner_client(sample_sbom).get(_card_url(sample_sbom.id))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Cryptographic Assets" in html
    assert "RSA-2048" in html  # an algorithm asset name
    assert "ML-KEM-768" in html
    assert "left-pad" not in html  # plain library excluded
    # raw NIST quantum level shown verbatim, including 0 (not hidden as falsy)
    assert "algorithm" in html  # asset-type breakdown label


@pytest.mark.django_db
def test_card_is_a_partial_not_a_full_page(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    html = _owner_client(sample_sbom).get(_card_url(sample_sbom.id)).content.decode()
    assert "<html" not in html.lower()
    assert "<!doctype" not in html.lower()


@pytest.mark.django_db
def test_card_empty_for_non_crypto_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, json.dumps({"specVersion": "1.6", "components": [{"type": "library", "name": "x"}]}).encode())
    response = _owner_client(sample_sbom).get(_card_url(sample_sbom.id))
    assert response.status_code == 200
    assert response.content.decode().strip() == ""  # nothing to show -> placeholder collapses


@pytest.mark.django_db
def test_card_empty_for_unknown_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, b"{}")
    response = _owner_client(sample_sbom).get(_card_url("doesnotexist1"))
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


@pytest.mark.django_db
def test_card_does_not_leak_private_to_anonymous(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    response = Client().get(_card_url(sample_sbom.id))  # anon, component is private
    assert response.status_code == 200
    assert "RSA-2048" not in response.content.decode()


@pytest.mark.django_db
def test_card_visible_on_public_component_to_anonymous(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    sample_sbom.component.visibility = Component.Visibility.PUBLIC
    sample_sbom.component.save()
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    response = Client().get(_card_url(sample_sbom.id))
    assert response.status_code == 200
    assert "RSA-2048" in response.content.decode()


@pytest.mark.django_db
def test_card_shows_pqc_readiness(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    html = _owner_client(sample_sbom).get(_card_url(sample_sbom.id)).content.decode()
    assert "At risk" in html  # overall readiness badge (RSA/ECDSA vulnerable)
    assert "Vulnerable" in html  # per-asset status
    assert "Quantum-safe" in html  # ML-KEM


@pytest.mark.django_db
def test_item_page_wires_lazy_placeholder(sample_sbom: SBOM):  # noqa: F811
    """The SBOM item detail page lazy-loads the card via hx-get (no S3 read at page render)."""
    client = _owner_client(sample_sbom)
    item_url = reverse("core:component_item", args=[sample_sbom.component.id, "sboms", sample_sbom.id])
    response = client.get(item_url)
    assert response.status_code == 200
    html = response.content.decode()
    assert _card_url(sample_sbom.id) in html
    assert 'hx-trigger="load"' in html
