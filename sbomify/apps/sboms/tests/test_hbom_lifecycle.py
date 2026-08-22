"""HBOM across the artifact lifecycle: both upload endpoints, the per-bom_type
duplicate guard, the single-artifact download and delete paths, and the scanner
gate.

Detection itself lives in ``test_hbom_detection``; what is pinned here is that an
HBOM travels the same routes as an SBOM without colliding with it, and that the
two vulnerability scanners never see one — hardware components carry no PURLs,
so a scan would match nothing and bank a misleading zero-finding run.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.plugins.builtins.osv import OSVPlugin
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.orchestrator import PluginOrchestrator
from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import SBOM, Component

_DATA = pathlib.Path(__file__).parent.resolve() / "test_data"
_PCIE_HBOM = _DATA / "hbom_pcie_sata_adapter.cdx.json"
_SPDX_SBOM = _DATA / "hello-world_syft.spdx.json"
# The upload derives the row version from metadata.component.version, so the
# duplicate-guard tests have to line their fixture SBOM up with this value.
_PCIE_VERSION = "rev-1"


@pytest.fixture
def _s3(mocker: MockerFixture) -> None:
    """Stub the object store so the upload paths run without a bucket."""
    mocker.patch("boto3.resource")
    # upload_sbom is what the upload endpoints call, and it returns the filename
    # stored on the row — mocking only upload_data_as_file left the real method
    # running and the stub depending on boto3 being patched everywhere.
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_sbom", return_value="stub-upload.json")


def _cyclonedx_url(component: Component, query: str = "") -> str:
    return reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": component.id}) + query


def _plain_sbom(component: Component, version: str) -> SBOM:
    return SBOM.objects.create(
        name="app",
        version=version,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="app.json",
        component=component,
        source="api",
        bom_type=SBOM.BomType.SBOM,
    )


@pytest.mark.django_db
def test_cyclonedx_upload_with_explicit_hbom_type(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
) -> None:
    """A generator that knows what it emits passes ?bom_type=hbom rather than
    relying on detection; the row lands in the same slot either way."""
    response = Client().post(
        _cyclonedx_url(sample_component, "?bom_type=hbom"),
        data=_PCIE_HBOM.read_text(),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201, response.content
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.bom_type == SBOM.BomType.HBOM
    assert sbom.has_hardware_components is True
    assert sbom.version == _PCIE_VERSION


@pytest.mark.django_db
def test_file_upload_with_explicit_hbom_type(
    sample_user,
    sample_component: Component,
    _s3: None,
) -> None:
    client = Client()
    client.force_login(sample_user)
    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id}) + "?bom_type=hbom"

    with open(_PCIE_HBOM, "rb") as handle:
        response = client.post(url, data={"sbom_file": handle}, format="multipart")

    assert response.status_code == 201, response.content
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.bom_type == SBOM.BomType.HBOM
    assert sbom.source == "manual_upload"


@pytest.mark.django_db
def test_spdx_api_upload_rejects_hbom_type(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
) -> None:
    """SPDX has no device component type, so an SPDX document can never be a
    hardware BOM — the type is rejected rather than silently stored."""
    response = Client().post(
        reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id}) + "?bom_type=hbom",
        data=_SPDX_SBOM.read_text(),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400, response.content
    assert "not supported for SPDX uploads" in response.json()["detail"]
    assert not SBOM.objects.filter(component=sample_component).exists()


@pytest.mark.django_db
def test_file_upload_of_spdx_rejects_hbom_type(
    sample_user,
    sample_component: Component,
    _s3: None,
) -> None:
    client = Client()
    client.force_login(sample_user)
    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id}) + "?bom_type=hbom"

    with open(_SPDX_SBOM, "rb") as handle:
        response = client.post(url, data={"sbom_file": handle}, format="multipart")

    assert response.status_code == 400, response.content
    assert "not supported for SPDX uploads" in response.json()["detail"]
    assert not SBOM.objects.filter(component=sample_component).exists()


@pytest.mark.django_db
def test_hbom_does_not_collide_with_same_version_sbom(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
) -> None:
    """The uniqueness key carries bom_type: a board's HBOM and its firmware SBOM
    are both "rev-1" of the same component and must coexist."""
    sbom = _plain_sbom(sample_component, _PCIE_VERSION)

    response = Client().post(
        _cyclonedx_url(sample_component),
        data=_PCIE_HBOM.read_text(),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201, response.content
    hbom = SBOM.objects.get(id=response.json()["id"])
    assert hbom.bom_type == SBOM.BomType.HBOM
    assert hbom.version == sbom.version
    assert SBOM.objects.filter(component=sample_component, version=_PCIE_VERSION).count() == 2


@pytest.mark.django_db
def test_duplicate_hbom_at_same_version_is_rejected(
    sample_access_token: AccessToken,
    sample_component: Component,
    _s3: None,
) -> None:
    """HBOM keeps the guard VEX is exempt from: a re-uploaded static artifact is
    still a 409, per bom_type."""
    client = Client()
    headers = get_api_headers(sample_access_token)
    payload = _PCIE_HBOM.read_text()

    first = client.post(_cyclonedx_url(sample_component), data=payload, content_type="application/json", **headers)
    assert first.status_code == 201, first.content

    second = client.post(_cyclonedx_url(sample_component), data=payload, content_type="application/json", **headers)

    assert second.status_code == 409, second.content
    assert "HBOM artifact" in second.json()["detail"]


@pytest.mark.django_db
def test_hbom_download_fires_hbom_event(
    sample_user,
    sample_component: Component,
    mocker: MockerFixture,
) -> None:
    hbom = SBOM.objects.create(
        name="pcie-sata-adaptor-board",
        version=_PCIE_VERSION,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="board.hbom.json",
        component=sample_component,
        source="api",
        bom_type=SBOM.BomType.HBOM,
    )
    mocker.patch(
        "sbomify.apps.core.object_store.S3Client.get_sbom_data",
        return_value=_PCIE_HBOM.read_bytes(),
    )
    capture = mocker.patch("sbomify.apps.core.posthog_service.capture")
    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)

    client = Client()
    setup_authenticated_client_session(client, sample_component.team, sample_user)
    response = client.get(reverse("sboms:sbom_download", kwargs={"sbom_id": hbom.id}))

    assert response.status_code == 200
    assert json.loads(response.content)["specVersion"] == "1.4"
    names = [call.args[1] for call in capture.call_args_list]
    assert "hbom:downloaded" in names
    assert "sbom:downloaded" not in names


@pytest.mark.django_db
def test_hbom_delete_removes_blob_and_fires_hbom_event(
    sample_access_token: AccessToken,
    sample_component: Component,
    mocker: MockerFixture,
    django_capture_on_commit_callbacks,
) -> None:
    hbom = SBOM.objects.create(
        name="pcie-sata-adaptor-board",
        version=_PCIE_VERSION,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="board.hbom.json",
        component=sample_component,
        source="api",
        bom_type=SBOM.BomType.HBOM,
    )
    delete_object = mocker.patch("sbomify.apps.core.object_store.S3Client.delete_object")
    capture_for_request = mocker.patch("sbomify.apps.core.posthog_service.capture_for_request")

    with django_capture_on_commit_callbacks(execute=True):
        response = Client().delete(
            reverse("api-1:delete_sbom", kwargs={"sbom_id": hbom.id}),
            **get_api_headers(sample_access_token),
        )

    assert response.status_code == 204, response.content
    assert not SBOM.objects.filter(id=hbom.id).exists()
    delete_object.assert_called_once_with(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, "board.hbom.json")
    names = [call.args[1] for call in capture_for_request.call_args_list]
    assert "hbom:deleted" in names
    assert "sbom:deleted" not in names


@pytest.mark.django_db
@pytest.mark.parametrize("plugin_class", [OSVPlugin, DependencyTrackPlugin], ids=["osv", "dependency-track"])
def test_vulnerability_scanners_skip_hbom(
    plugin_class: type[AssessmentPlugin],
    sample_component: Component,
    mocker: MockerFixture,
) -> None:
    """Both scanners pin supported_bom_types=["sbom"], so the orchestrator must
    skip an HBOM before it fetches the document — no run row, no scanner call,
    and therefore no zero-finding result masquerading as a clean scan."""
    hbom = SBOM.objects.create(
        name="pcie-sata-adaptor-board",
        version=_PCIE_VERSION,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="board.hbom.json",
        component=sample_component,
        bom_type=SBOM.BomType.HBOM,
    )
    fetch = mocker.patch("sbomify.apps.plugins.orchestrator.get_sbom_data_bytes")

    run = PluginOrchestrator().run_assessment(sbom_id=hbom.id, plugin=plugin_class(), run_reason=RunReason.ON_UPLOAD)

    assert run is None
    fetch.assert_not_called()
    assert not AssessmentRun.objects.filter(sbom_id=hbom.id).exists()
