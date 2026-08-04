"""API and card tests for the derived hardware (HBOM) inventory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from sbomify.apps.core.tests.shared_fixtures import get_api_headers

from ..models import SBOM
from .fixtures import sample_access_token, sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session

_DATA = Path(__file__).parent / "test_data"
_S3_TARGET = "sbomify.apps.sboms.hardware_inventory.S3Client"
_PCIE = _DATA / "hbom_pcie_sata_adapter.cdx.json"


def _api_url(sbom_id: str) -> str:
    return reverse("api-1:get_sbom_hardware_inventory", kwargs={"sbom_id": sbom_id})


def _card_url(sbom_id: str) -> str:
    return reverse("sboms:sbom_hardware_inventory", kwargs={"sbom_id": sbom_id})


def _mock_s3(mocker: MockerFixture, payload: bytes | None) -> None:
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.return_value = payload


def _owner_client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


def _software_sbom() -> bytes:
    return json.dumps({"specVersion": "1.6", "components": [{"type": "library", "name": "left-pad"}]}).encode()


def _device_with(**component: Any) -> bytes:
    return json.dumps({"specVersion": "1.6", "components": [{"type": "device", **component}]}).encode()


@pytest.mark.django_db
def test_returns_derived_hardware_inventory(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _PCIE.read_bytes())
    response = _owner_client(sample_sbom).get(_api_url(sample_sbom.id))

    assert response.status_code == 200
    body = response.json()
    assert body["sbom_id"] == sample_sbom.id
    assert body["count"] == 6
    assert body["by_type"] == {"device": 6}
    part = next(p for p in body["parts"] if p["name"] == "47155-4001")
    assert part["manufacturer"] == "Molex"
    assert part["manufacturer_source"] == "supplier"
    assert part["quantity"] == "8"
    assert part["gs1"] == {"gtin-12": "822348522712"}
    assert part["cpe_nvd_url"] is None  # the example carries no CPE


@pytest.mark.django_db
def test_empty_inventory_for_software_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _software_sbom())
    response = _owner_client(sample_sbom).get(_api_url(sample_sbom.id))
    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.django_db
def test_404_for_unknown_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, b"{}")
    assert _owner_client(sample_sbom).get(_api_url("doesnotexist1")).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [None, b""])
def test_404_when_artifact_missing_from_storage(
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,
    payload: bytes | None,
):
    # An empty object body is corruption/absence, not a hardware-free SBOM.
    _mock_s3(mocker, payload)
    assert _owner_client(sample_sbom).get(_api_url(sample_sbom.id)).status_code == 404


@pytest.mark.django_db
def test_invalid_utf8_artifact_yields_empty_inventory_not_500(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, b"\xff\xfe\x00not-valid-utf8")
    response = _owner_client(sample_sbom).get(_api_url(sample_sbom.id))
    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.django_db
def test_403_for_private_sbom_without_access(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _PCIE.read_bytes())
    assert Client().get(_api_url(sample_sbom.id)).status_code == 403


@pytest.mark.django_db
def test_personal_access_token_reads_private_inventory(
    sample_sbom: SBOM,  # noqa: F811
    sample_access_token,  # noqa: F811
    mocker: MockerFixture,
):
    # auth=None must still honor a PAT (via optional_auth) for private SBOMs.
    _mock_s3(mocker, _PCIE.read_bytes())
    response = Client().get(_api_url(sample_sbom.id), **get_api_headers(sample_access_token))
    assert response.status_code == 200
    assert response.json()["count"] == 6


@pytest.mark.django_db
def test_publish_only_token_denied_private_inventory(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    # optional_auth processes the PAT, so the token scope must be honoured: a
    # publish-only token has no component:access and must not read the inventory.
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import create_personal_access_token
    from sbomify.apps.teams.models import Member

    _mock_s3(mocker, _PCIE.read_bytes())
    team = sample_sbom.component.team
    owner = Member.objects.filter(team=team, role="owner").first()
    assert owner is not None
    token_str = create_personal_access_token(owner.user)
    AccessToken.objects.create(
        user=owner.user, encoded_token=token_str, description="publish-only", team=team, scopes=["artifact:publish"]
    )

    response = Client().get(_api_url(sample_sbom.id), HTTP_AUTHORIZATION=f"Bearer {token_str}")
    assert response.status_code == 403


@pytest.mark.django_db
def test_card_renders_the_parts_table(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _PCIE.read_bytes())
    response = _owner_client(sample_sbom).get(_card_url(sample_sbom.id))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Hardware Components" in html
    assert "PCIE-098-02-F-D-EMS2" in html
    assert "Samtec" in html
    assert "822348522712" in html  # GTIN, from the row drill-down
    assert "thru-hole" in html
    assert "pcie-sata-adaptor-board" not in html  # metadata.component is the subject, not a part


@pytest.mark.django_db
def test_card_is_a_partial_not_a_full_page(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _PCIE.read_bytes())
    html = _owner_client(sample_sbom).get(_card_url(sample_sbom.id)).content.decode()
    assert "<html" not in html.lower()
    assert "<!doctype" not in html.lower()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [_software_sbom(), b"{}", b"not json"])
def test_card_collapses_when_there_is_no_hardware(
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,
    payload: bytes,
):
    _mock_s3(mocker, payload)
    response = _owner_client(sample_sbom).get(_card_url(sample_sbom.id))
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


@pytest.mark.django_db
def test_card_empty_for_unknown_sbom(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, b"{}")
    response = _owner_client(sample_sbom).get(_card_url("doesnotexist1"))
    assert response.status_code == 200
    assert response.content.decode().strip() == ""


@pytest.mark.django_db
def test_card_does_not_leak_private_to_anonymous(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _PCIE.read_bytes())
    response = Client().get(_card_url(sample_sbom.id))  # anon, component is private
    assert response.status_code == 200
    assert "Samtec" not in response.content.decode()


@pytest.mark.django_db
def test_cpe_renders_as_a_labelled_manual_lookup(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    _mock_s3(mocker, _device_with(name="core i7", cpe="cpe:2.3:h:intel:core_i7:-:*:*:*:*:*:*:*"))
    html = _owner_client(sample_sbom).get(_card_url(sample_sbom.id)).content.decode()

    assert "nvd.nist.gov/vuln/search/results" in html
    assert "manual lookup" in html.lower()
    # A link out, never a scan result: no finding count, no severity, no badge.
    assert "tw-badge-danger" not in html
    assert "tw-badge-warning" not in html
    assert "vulnerabilit" not in html.lower()
