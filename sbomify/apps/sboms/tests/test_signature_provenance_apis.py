"""Tests for SBOM signature and provenance upload/download API endpoints."""

from __future__ import annotations

import base64
import json
from typing import Any, Generator

import pytest
from django.test import Client
from pytest_mock.plugin import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import get_api_headers

from ..models import SBOM, Component

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sbom_with_hash(
    sample_component: Component,
    sample_access_token: AccessToken,
) -> Generator[SBOM, Any, None]:
    """SBOM that has a sha256_hash (prerequisite for signature/provenance)."""
    sbom = SBOM.objects.create(
        name="test-sbom-sig",
        version="1.0.0",
        format="spdx",
        format_version="2.3",
        sbom_filename="abc123.json",
        component=sample_component,
        source="api",
        sha256_hash="a" * 64,
    )
    yield sbom
    sbom.delete()


@pytest.fixture
def sbom_without_hash(
    sample_component: Component,
    sample_access_token: AccessToken,
) -> Generator[SBOM, Any, None]:
    """SBOM without sha256_hash."""
    sbom = SBOM.objects.create(
        name="test-sbom-nohash",
        version="1.0.0",
        format="spdx",
        format_version="2.3",
        sbom_filename="def456.json",
        component=sample_component,
        source="api",
        sha256_hash=None,
    )
    yield sbom
    sbom.delete()


def _make_provenance_statement(sha256: str) -> dict[str, Any]:
    """Build a minimal in-toto Statement with a matching subject."""
    return {
        "_type": "https://in-toto.io/Statement/v0.1",
        "subject": [
            {
                "name": "sbom.json",
                "digest": {"sha256": sha256},
            }
        ],
        "predicateType": "https://slsa.dev/provenance/v0.2",
        "predicate": {},
    }


def _wrap_in_dsse(statement: dict[str, Any]) -> dict[str, Any]:
    """Wrap a statement in a DSSE envelope."""
    payload = base64.b64encode(json.dumps(statement).encode()).decode()
    return {
        "payloadType": "application/vnd.in-toto+json",
        "payload": payload,
        "signatures": [{"sig": "fakesig"}],
    }


# ============================================================================
# Signature upload tests
# ============================================================================


@pytest.mark.django_db
def test_signature_upload_success(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_sbom_signature", return_value="aaa.sig")
    # Prevent actual dramatiq dispatch
    mocker.patch("sbomify.apps.plugins.tasks.enqueue_assessment")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.post(
        url,
        data=b"signature-bytes",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="cosign-bundle",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["blob_key"] == "aaa.sig"

    sbom_with_hash.refresh_from_db()
    assert sbom_with_hash.signature_blob_key == "aaa.sig"
    assert sbom_with_hash.signature_type == "cosign-bundle"


@pytest.mark.django_db
def test_signature_upload_missing_header(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.post(
        url,
        data=b"signature-bytes",
        content_type="application/octet-stream",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "Missing X-Signature-Type" in response.json()["detail"]


@pytest.mark.django_db
def test_signature_upload_invalid_type(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.post(
        url,
        data=b"signature-bytes",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="unknown-type",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "Invalid signature type" in response.json()["detail"]


@pytest.mark.django_db
def test_signature_upload_already_exists(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    sbom_with_hash.signature_blob_key = "existing.sig"
    sbom_with_hash.signature_type = "pgp-detached"
    sbom_with_hash.save(update_fields=["signature_blob_key", "signature_type"])

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.post(
        url,
        data=b"new-sig",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="cosign-bundle",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_signature_upload_sbom_not_found(
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = "/api/v1/sboms/sbom/nonexistent99/signature"
    response = client.post(
        url,
        data=b"sig",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="cosign-bundle",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_signature_upload_sbom_no_hash(
    sbom_without_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_without_hash.id}/signature"
    response = client.post(
        url,
        data=b"sig",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="cosign-bundle",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "no sha256 hash" in response.json()["detail"]


@pytest.mark.django_db
def test_signature_upload_forbidden_for_guest(
    sbom_with_hash: SBOM,
    mocker: MockerFixture,
) -> None:
    """An unauthenticated request should be rejected."""
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.post(
        url,
        data=b"sig",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="cosign-bundle",
    )

    # Without auth the endpoint returns 401 (Ninja default for missing credentials)
    assert response.status_code in (401, 403)


# ============================================================================
# Signature download tests
# ============================================================================


@pytest.mark.django_db
def test_signature_download_success(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    mocker.patch(
        "sbomify.apps.core.object_store.S3Client.get_sbom_data",
        return_value=b"raw-signature-data",
    )

    sbom_with_hash.signature_blob_key = "aaa.sig"
    sbom_with_hash.signature_type = "pgp-detached"
    sbom_with_hash.save(update_fields=["signature_blob_key", "signature_type"])

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.get(url, **get_api_headers(sample_access_token))

    assert response.status_code == 200
    assert response.content == b"raw-signature-data"
    assert response["Content-Type"] == "application/octet-stream"
    assert response["X-Signature-Type"] == "pgp-detached"


@pytest.mark.django_db
def test_signature_download_not_attached(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/signature"
    response = client.get(url, **get_api_headers(sample_access_token))

    assert response.status_code == 404
    assert "No signature attached" in response.json()["detail"]


# ============================================================================
# Provenance upload tests
# ============================================================================


@pytest.mark.django_db
def test_provenance_upload_dsse_envelope(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    mocker.patch(
        "sbomify.apps.core.object_store.S3Client.upload_sbom_provenance",
        return_value="aaa.provenance.json",
    )

    statement = _make_provenance_statement(sbom_with_hash.sha256_hash)
    dsse = _wrap_in_dsse(statement)

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.post(
        url,
        data=json.dumps(dsse),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201, response.json()
    sbom_with_hash.refresh_from_db()
    assert sbom_with_hash.provenance_blob_key == "aaa.provenance.json"


@pytest.mark.django_db
def test_provenance_upload_direct_statement(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    mocker.patch(
        "sbomify.apps.core.object_store.S3Client.upload_sbom_provenance",
        return_value="aaa.provenance.json",
    )

    statement = _make_provenance_statement(sbom_with_hash.sha256_hash)

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.post(
        url,
        data=json.dumps(statement),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201, response.json()
    sbom_with_hash.refresh_from_db()
    assert sbom_with_hash.provenance_blob_key == "aaa.provenance.json"


@pytest.mark.django_db
def test_provenance_upload_digest_mismatch(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    statement = _make_provenance_statement("b" * 64)  # wrong hash

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.post(
        url,
        data=json.dumps(statement),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "No subject sha256 digest matches" in response.json()["detail"]


@pytest.mark.django_db
def test_provenance_upload_invalid_json(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.post(
        url,
        data=b"not-json{{{",
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]


@pytest.mark.django_db
def test_provenance_upload_already_exists(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    sbom_with_hash.provenance_blob_key = "existing.provenance.json"
    sbom_with_hash.save(update_fields=["provenance_blob_key"])

    assert sbom_with_hash.sha256_hash is not None
    statement = _make_provenance_statement(sbom_with_hash.sha256_hash)

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.post(
        url,
        data=json.dumps(statement),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_provenance_upload_sbom_not_found(
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    statement = _make_provenance_statement("a" * 64)

    client = Client()
    url = "/api/v1/sboms/sbom/nonexistent99/provenance"
    response = client.post(
        url,
        data=json.dumps(statement),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_provenance_upload_sbom_no_hash(
    sbom_without_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    statement = _make_provenance_statement("a" * 64)

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_without_hash.id}/provenance"
    response = client.post(
        url,
        data=json.dumps(statement),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "no sha256 hash" in response.json()["detail"]


@pytest.mark.django_db
def test_provenance_upload_no_subject_field(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    """Body is valid JSON but has neither payloadType/payload nor subject."""
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.post(
        url,
        data=json.dumps({"random": "data"}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "DSSE envelope" in response.json()["detail"]


# ============================================================================
# Provenance download tests
# ============================================================================


@pytest.mark.django_db
def test_provenance_download_success(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")
    provenance_json = json.dumps({"predicateType": "test"}).encode()
    mocker.patch(
        "sbomify.apps.core.object_store.S3Client.get_sbom_data",
        return_value=provenance_json,
    )

    sbom_with_hash.provenance_blob_key = "aaa.provenance.json"
    sbom_with_hash.save(update_fields=["provenance_blob_key"])

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.get(url, **get_api_headers(sample_access_token))

    assert response.status_code == 200
    assert response.content == provenance_json
    assert response["Content-Type"] == "application/json"


@pytest.mark.django_db
def test_provenance_download_not_attached(
    sbom_with_hash: SBOM,
    sample_access_token: AccessToken,
    mocker: MockerFixture,
) -> None:
    mocker.patch("boto3.resource")

    client = Client()
    url = f"/api/v1/sboms/sbom/{sbom_with_hash.id}/provenance"
    response = client.get(url, **get_api_headers(sample_access_token))

    assert response.status_code == 404
    assert "No provenance attached" in response.json()["detail"]
