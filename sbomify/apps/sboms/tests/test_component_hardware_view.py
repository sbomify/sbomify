"""Component-level hardware page: which artifact it picks, and what it shows without one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_mock.plugin import MockerFixture

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM, Component

_S3_TARGET = "sbomify.apps.sboms.hardware_inventory.S3Client"
_PCIE = Path(__file__).parent / "test_data" / "hbom_pcie_sata_adapter.cdx.json"


def _url(component_id: str) -> str:
    return reverse("sboms:component_hardware", kwargs={"component_id": component_id})


def _owner_client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_authenticated_client_session(client, team, team.members.first())
    return client


def _device_doc(*names: str) -> bytes:
    components = [{"type": "device", "bom-ref": name, "name": name} for name in names]
    return json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": components}).encode()


def _root_only_doc(name: str) -> bytes:
    """A device named only in metadata.component — enough to stamp the artifact hardware-bearing."""
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"type": "device", "bom-ref": name, "name": name}},
            "components": [{"type": "library", "name": "left-pad"}],
        }
    ).encode()


def _software_doc() -> bytes:
    return json.dumps({"specVersion": "1.6", "components": [{"type": "library", "name": "left-pad"}]}).encode()


def _mock_s3(mocker: MockerFixture, docs_by_filename: dict[str, bytes]):
    client = mocker.patch(_S3_TARGET)
    client.return_value.get_sbom_data.side_effect = lambda filename: docs_by_filename.get(filename)
    return client


def _make_hardware_bearing(sbom: SBOM, **fields) -> None:
    # update() rather than save(): the flag is stamped at upload, and the test
    # must not re-run the model's save-time derivations.
    SBOM.objects.filter(pk=sbom.id).update(has_hardware_components=True, **fields)


@pytest.mark.django_db
def test_renders_the_parts_of_a_hardware_bearing_sbom(sample_sbom: SBOM, mocker: MockerFixture):
    _make_hardware_bearing(sample_sbom)
    _mock_s3(mocker, {sample_sbom.sbom_filename: _PCIE.read_bytes()})

    response = _owner_client(sample_sbom).get(_url(sample_sbom.component_id))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Hardware Components" in html
    assert "PCIE-098-02-F-D-EMS2" in html
    assert "Samtec" in html


@pytest.mark.django_db
def test_renders_a_device_named_only_in_metadata(sample_sbom: SBOM, mocker: MockerFixture):
    """The upload stamp counts a device found in metadata.component, so this page
    selects the artifact *because* it holds hardware. Rendering "no parts" then
    contradicts its own selector — and the merged release HBOM lists that board."""
    _make_hardware_bearing(sample_sbom)
    _mock_s3(mocker, {sample_sbom.sbom_filename: _root_only_doc("MAX-9611-BOARD")})

    html = _owner_client(sample_sbom).get(_url(sample_sbom.component_id)).content.decode()

    assert "MAX-9611-BOARD" in html
    assert "No parts to show" not in html


@pytest.mark.django_db
def test_hbom_wins_over_a_newer_hardware_bearing_sbom(sample_sbom: SBOM, mocker: MockerFixture):
    SBOM.objects.create(
        name="board",
        version="1.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="board.cdx.json",
        component=sample_sbom.component,
        bom_type=SBOM.BomType.HBOM,
    )
    # The mixed SBOM is the newer row; the HBOM must still win.
    _make_hardware_bearing(sample_sbom, created_at=timezone.now())
    _mock_s3(
        mocker,
        {"board.cdx.json": _device_doc("MAX-9611"), sample_sbom.sbom_filename: _device_doc("NOT-THE-HBOM")},
    )

    html = _owner_client(sample_sbom).get(_url(sample_sbom.component_id)).content.decode()

    assert "MAX-9611" in html
    assert "not-the-hbom" not in html.lower()  # the search terms are lowercased, so match case-insensitively


@pytest.mark.django_db
def test_empty_state_when_no_artifact_carries_hardware(sample_sbom: SBOM, mocker: MockerFixture):
    # sample_sbom predates the flag (None), so it is not hardware-bearing.
    s3 = mocker.patch(_S3_TARGET)

    response = _owner_client(sample_sbom).get(_url(sample_sbom.component_id))

    assert response.status_code == 200
    assert "No hardware components yet" in response.content.decode()
    s3.assert_not_called()  # nothing to read, so no storage round-trip


@pytest.mark.django_db
def test_empty_state_when_the_artifact_carries_no_parts(sample_sbom: SBOM, mocker: MockerFixture):
    _make_hardware_bearing(sample_sbom)
    _mock_s3(mocker, {sample_sbom.sbom_filename: _software_doc()})

    response = _owner_client(sample_sbom).get(_url(sample_sbom.component_id))

    assert response.status_code == 200
    assert "No parts to show" in response.content.decode()


@pytest.mark.django_db
def test_unreadable_artifact_renders_the_empty_state_not_a_500(sample_sbom: SBOM, mocker: MockerFixture):
    _make_hardware_bearing(sample_sbom)
    mocker.patch(_S3_TARGET).return_value.get_sbom_data.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket"}}, "GetObject"
    )

    response = _owner_client(sample_sbom).get(_url(sample_sbom.component_id))

    assert response.status_code == 200
    assert "No parts to show" in response.content.decode()


@pytest.mark.django_db
def test_unknown_component_is_404(sample_sbom: SBOM):
    assert _owner_client(sample_sbom).get(_url("doesnotexist1")).status_code == 404


@pytest.mark.django_db
def test_an_anonymous_visitor_is_sent_to_login(sample_sbom: SBOM, mocker: MockerFixture):
    """There is no anonymous version of this page.

    It renders inside the authenticated dashboard shell, which reads the
    signed-in user, so an anonymous request used to reach the template and 500
    on ``user.email``. The public read path for the same parts is the inventory
    card on the public artifact page. ``can`` still decides whether a signed-in
    user may read this particular component.
    """
    _make_hardware_bearing(sample_sbom)
    Component.objects.filter(pk=sample_sbom.component_id).update(visibility=Component.Visibility.PUBLIC)
    _mock_s3(mocker, {sample_sbom.sbom_filename: _PCIE.read_bytes()})

    response = Client().get(_url(sample_sbom.component_id))

    assert response.status_code == 302
    assert "login" in response["Location"].lower()
    assert "Samtec" not in response.content.decode()
