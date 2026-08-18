"""Hardware-BOM auto-detection: ``_is_hbom`` / ``_contains_hardware_components``
and the two upload paths that stamp them."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.utils import _contains_hardware_components, _is_hbom

_DATA = pathlib.Path(__file__).parent.resolve() / "test_data"
_PCIE_HBOM = _DATA / "hbom_pcie_sata_adapter.cdx.json"
_TRIVY_SBOM = _DATA / "sbomify_trivy.cdx.json"


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _doc(*types: str) -> dict[str, Any]:
    return {"components": [{"type": t, "name": f"c-{i}"} for i, t in enumerate(types)]}


def test_pcie_sata_adapter_example_is_hbom():
    """The upstream CycloneDX HBOM example: six components, all type=device."""
    doc = _load(_PCIE_HBOM)
    assert _is_hbom(doc)
    assert _contains_hardware_components(doc)


def test_cdxgen_hbom_shape_is_hbom():
    """cdxgen emits platform and firmware entries beside the devices it enumerates."""
    doc = _doc("device", "device", "platform", "firmware", "device-driver")
    assert _is_hbom(doc)
    assert _contains_hardware_components(doc)


def test_lockfile_sbom_is_not_hbom():
    doc = _load(_TRIVY_SBOM)
    assert not _is_hbom(doc)
    assert not _contains_hardware_components(doc)


def test_device_metadata_with_software_components_is_not_hbom():
    """A device's *software* SBOM: metadata.component names the device, the
    components are its libraries. It stays an sbom but is still stamped."""
    doc = _doc("library", "library")
    doc["metadata"] = {"component": {"type": "device", "name": "router"}}
    assert not _is_hbom(doc)
    assert _contains_hardware_components(doc)


def test_all_platform_document_is_not_hbom():
    """platform is a software runtime environment; without a device it is no HBOM."""
    assert not _is_hbom(_doc("platform", "platform"))
    assert not _contains_hardware_components(_doc("platform", "platform"))


def test_mixed_hardware_and_software_is_not_hbom_but_is_stamped():
    doc = _doc("device", "library")
    assert not _is_hbom(doc)
    assert _contains_hardware_components(doc)


def test_firmware_alone_is_neither():
    """A firmware SBOM is a software SBOM, so it neither re-tags nor stamps."""
    doc = _doc("firmware", "firmware")
    assert not _is_hbom(doc)
    assert not _contains_hardware_components(doc)


@pytest.mark.parametrize("doc", [{}, {"components": []}, {"components": "nope"}, {"components": ["oops", None]}])
def test_missing_or_malformed_components_are_not_hbom(doc: dict[str, Any]):
    assert not _is_hbom(doc)
    assert not _contains_hardware_components(doc)


def test_metadata_only_device_does_not_retag():
    """The deliberate divergence from ``_is_cbom``: no components array means no HBOM."""
    doc: dict[str, Any] = {"metadata": {"component": {"type": "device", "name": "board"}}}
    assert not _is_hbom(doc)
    assert _contains_hardware_components(doc)


@pytest.fixture
def _s3(mocker: MockerFixture) -> None:
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")
    SBOM.objects.all().delete()


def _upload_cyclonedx(client: Client, component: Component, token: AccessToken, payload: str, query: str = "") -> SBOM:
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": component.id}) + query
    resp = client.post(url, data=payload, content_type="application/json", **get_api_headers(token))
    assert resp.status_code == 201, resp.content
    return SBOM.objects.get(id=resp.json()["id"])


@pytest.mark.django_db
def test_cyclonedx_upload_autodetects_hbom(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
):
    sbom = _upload_cyclonedx(Client(), sample_component, sample_access_token, _PCIE_HBOM.read_text())
    assert sbom.bom_type == "hbom"
    assert sbom.has_hardware_components is True


@pytest.mark.django_db
def test_cyclonedx_upload_explicit_sbom_not_retagged_hbom(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
):
    sbom = _upload_cyclonedx(Client(), sample_component, sample_access_token, _PCIE_HBOM.read_text(), "?bom_type=sbom")
    assert sbom.bom_type == "sbom"
    assert sbom.has_hardware_components is True


@pytest.mark.django_db
def test_cyclonedx_upload_explicit_vex_not_retagged_hbom(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
):
    sbom = _upload_cyclonedx(Client(), sample_component, sample_access_token, _PCIE_HBOM.read_text(), "?bom_type=vex")
    assert sbom.bom_type == "vex"


@pytest.mark.django_db
def test_cyclonedx_upload_software_sbom_stamps_no_hardware(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
):
    sbom = _upload_cyclonedx(Client(), sample_component, sample_access_token, _TRIVY_SBOM.read_text())
    assert sbom.bom_type == "sbom"
    assert sbom.has_hardware_components is False


@pytest.mark.django_db
def test_cyclonedx_upload_device_metadata_stays_sbom(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
):
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"type": "device", "name": "router", "version": "1.0.0"}},
        "components": [{"type": "library", "name": "libfoo", "version": "1.0"}],
    }
    sbom = _upload_cyclonedx(Client(), sample_component, sample_access_token, json.dumps(doc))
    assert sbom.bom_type == "sbom"
    assert sbom.has_hardware_components is True


@pytest.mark.django_db
def test_file_upload_autodetects_hbom(
    sample_user,
    sample_component: Component,
    _s3: None,
):
    client = Client()
    client.force_login(sample_user)
    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})
    with open(_PCIE_HBOM, "rb") as f:
        resp = client.post(url, data={"sbom_file": f}, format="multipart")

    assert resp.status_code == 201, resp.content
    sbom = SBOM.objects.get(id=resp.json()["id"])
    assert sbom.bom_type == "hbom"
    assert sbom.has_hardware_components is True


@pytest.mark.parametrize("device_type", ["device", "Device", "DEVICE"])
def test_detection_ignores_the_case_of_the_component_type(device_type: str) -> None:
    """CycloneDX defines type as a lowercase enum, so a capitalised one is out
    of spec — but the compliance plugins already lowercase before comparing.
    Detection matching exactly while scoring matched loosely was the worst
    pairing: such a document was filed as software and exempted from the checks
    that would have graded it."""
    document = {"components": [{"type": device_type, "name": "STM32"}]}

    assert _is_hbom(document) is True
    assert _contains_hardware_components(document) is True


def test_a_capitalised_hardware_set_member_does_not_reject_the_document() -> None:
    """_is_hbom requires every component to be a hardware type, so one
    capitalised entry used to fail the all() and reject the whole document."""
    document = {
        "components": [
            {"type": "device", "name": "board"},
            {"type": "Firmware", "name": "bootloader"},
        ]
    }

    assert _is_hbom(document) is True
