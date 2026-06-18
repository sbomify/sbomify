"""Tests for the component-level post-quantum posture card (#1001 increment 6)."""

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


def _posture_url(component_id: str) -> str:
    return reverse("sboms:component_crypto_posture", kwargs={"component_id": component_id})


def _mock_s3(mocker: MockerFixture, payload: bytes | None) -> None:
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = payload


def _owner_client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


@pytest.mark.django_db
def test_posture_renders_for_component_with_crypto(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    component_id = sample_sbom.component.id
    response = _owner_client(sample_sbom).get(_posture_url(component_id))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Post-Quantum Posture" in html
    assert "At risk" in html  # RSA/ECDSA vulnerable -> overall at_risk
    # links through to the per-SBOM crypto detail
    assert reverse("core:component_item", args=[component_id, "sboms", sample_sbom.id]) in html


@pytest.mark.django_db
def test_posture_collapses_for_non_crypto(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, json.dumps({"specVersion": "1.6", "components": [{"type": "library", "name": "x"}]}).encode())
    response = _owner_client(sample_sbom).get(_posture_url(sample_sbom.component.id))
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


@pytest.mark.django_db
def test_posture_collapses_for_component_without_sboms(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="No SBOMs", team=team, component_type=Component.ComponentType.BOM)
    client = Client()
    setup_test_session(client, team, sample_team_with_owner_member.user)
    response = client.get(_posture_url(component.id))
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


@pytest.mark.django_db
def test_posture_does_not_leak_private_to_anonymous(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, (_DATA / "cbom_sample_1.6.cdx.json").read_bytes())
    response = Client().get(_posture_url(sample_sbom.component.id))  # anon, component private
    assert response.status_code == 200
    assert "At risk" not in response.content.decode()
