"""Signing the CRA export bundle with sbomify's export key.

Every key here is generated inside the test that uses it.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import logging
import shutil
import subprocess
import zipfile
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.core.checks import registry

from sbomify.apps.compliance.models import CRAExportPackage
from sbomify.apps.compliance.services import export_signing
from sbomify.apps.compliance.services.export_service import build_export_package, get_signature_url
from sbomify.apps.compliance.tests.test_export_service import (  # noqa: F401
    assessment,
    assessment_with_docs,
    product,
)
from sbomify.apps.core.tests.shared_fixtures import get_api_headers


def _private_pem(key, password: bytes | None = None) -> str:
    encryption = (
        serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
    )
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption).decode()


def _public_pem(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def _kid(key) -> str:
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:16]


class _Store:
    """Captures every upload by key. ``fail_suffix`` makes matching uploads raise."""

    def __init__(self, fail_suffix: str | None = None) -> None:
        self.uploads: dict[str, bytes] = {}
        self.fail_suffix = fail_suffix

    def upload_data_as_file(self, bucket, key, data):
        if self.fail_suffix and key.endswith(self.fail_suffix):
            raise RuntimeError("storage unavailable")
        self.uploads[key] = data

    def get_file_data(self, bucket, key):
        return b""

    def get_sbom_data(self, filename):
        return b""


@contextlib.contextmanager
def _records(logger_name: str):
    """Records from a logger under ``sbomify``, which does not propagate to caplog's root handler."""
    captured: list[logging.LogRecord] = []

    class _List(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _List(level=logging.DEBUG)
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    try:
        yield captured
    finally:
        logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def _fresh_key_cache():
    export_signing._load.cache_clear()
    yield
    export_signing._load.cache_clear()


@pytest.fixture
def store():
    s = _Store()
    with patch("sbomify.apps.compliance.services.export_service.StorageClient", return_value=s):
        yield s


@pytest.fixture
def signing_key(settings):
    key = ec.generate_private_key(ec.SECP256R1())
    settings.CRA_EXPORT_SIGNING_KEY = _private_pem(key)
    return key


@pytest.fixture
def no_signing_key(settings):
    settings.CRA_EXPORT_SIGNING_KEY = ""


def _zip_text(zip_bytes: bytes, suffix: str) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return zf.read(next(n for n in zf.namelist() if n.endswith(suffix))).decode()


@pytest.mark.django_db
class TestSignedBundle:
    def test_the_signature_verifies_over_the_zip_with_the_public_key(
        self, signing_key, store, assessment_with_docs, sample_user
    ):
        result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok, result.error
        package = result.value
        zip_bytes = store.uploads[package.storage_key]
        signature = store.uploads[package.storage_key + ".sig"]
        signing_key.public_key().verify(base64.b64decode(signature), zip_bytes, ec.ECDSA(hashes.SHA256()))
        assert package.signing_key_id == _kid(signing_key)

    def test_the_manifest_and_readme_name_the_key(self, signing_key, store, assessment_with_docs, sample_user):
        result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok, result.error
        kid = _kid(signing_key)
        manifest = result.value.manifest
        assert manifest["format_version"] == "1.3"
        signature = manifest["integrity"]["signature"]
        assert signature["algorithm"] == "ecdsa-p256-sha256"
        assert signature["encoding"] == "base64-der"
        assert signature["key_id"] == kid
        assert signature["public_key_url"].endswith(f"/.well-known/sbomify/export-keys/{kid}.pem")
        readme = _zip_text(store.uploads[result.value.storage_key], "metadata/INTEGRITY.md")
        assert "sbomify signs this bundle" in readme
        assert kid in readme
        assert "cosign verify-blob" in readme
        assert "sbomify does not sign the bundle itself" not in readme

    def test_the_key_url_uses_the_app_base_url(self, settings, signing_key, store, assessment_with_docs, sample_user):
        settings.APP_BASE_URL = "https://app.example.com/"

        result = build_export_package(assessment_with_docs, sample_user)

        kid = _kid(signing_key)
        url = result.value.manifest["integrity"]["signature"]["public_key_url"]
        assert url == f"https://app.example.com/.well-known/sbomify/export-keys/{kid}.pem"

    @pytest.mark.skipif(shutil.which("cosign") is None, reason="cosign is not installed")
    def test_cosign_verifies_the_signature(self, signing_key, store, assessment_with_docs, sample_user, tmp_path):
        result = build_export_package(assessment_with_docs, sample_user)

        bundle = tmp_path / "bundle.zip"
        bundle.write_bytes(store.uploads[result.value.storage_key])
        (tmp_path / "bundle.zip.sig").write_bytes(store.uploads[result.value.storage_key + ".sig"])
        (tmp_path / "sbomify.pub").write_bytes(_public_pem(signing_key))
        verify = subprocess.run(
            [
                "cosign",
                "verify-blob",
                "--key",
                str(tmp_path / "sbomify.pub"),
                "--signature",
                str(tmp_path / "bundle.zip.sig"),
                "--insecure-ignore-tlog=true",
                str(bundle),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert verify.returncode == 0, verify.stderr

    def test_a_key_with_escaped_newlines_still_loads(self, settings, store, assessment_with_docs, sample_user):
        key = ec.generate_private_key(ec.SECP256R1())
        settings.CRA_EXPORT_SIGNING_KEY = _private_pem(key).replace("\n", "\\n")

        result = build_export_package(assessment_with_docs, sample_user)

        assert result.value.signing_key_id == _kid(key)

    def test_a_failed_signature_upload_fails_the_export(self, signing_key, assessment_with_docs, sample_user):
        failing = _Store(fail_suffix=".sig")
        with patch("sbomify.apps.compliance.services.export_service.StorageClient", return_value=failing):
            result = build_export_package(assessment_with_docs, sample_user)

        assert not result.ok
        assert result.status_code == 502
        assert not CRAExportPackage.objects.filter(assessment=assessment_with_docs).exists()
        assert not any(key.endswith(".zip") for key in failing.uploads)


@pytest.mark.django_db
class TestUnsignedBundle:
    def test_no_key_means_no_signature_and_todays_text(self, no_signing_key, store, assessment_with_docs, sample_user):
        result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok, result.error
        package = result.value
        assert package.signing_key_id == ""
        assert not any(key.endswith(".sig") for key in store.uploads)
        assert "signature" not in package.manifest["integrity"]
        readme = _zip_text(store.uploads[package.storage_key], "metadata/INTEGRITY.md")
        assert "sbomify does not sign the bundle itself" in readme

    @pytest.mark.parametrize(
        ("label", "make_value"),
        [
            ("garbage", lambda: "not a key"),
            ("rsa", lambda: _private_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))),
            ("p384", lambda: _private_pem(ec.generate_private_key(ec.SECP384R1()))),
            ("encrypted", lambda: _private_pem(ec.generate_private_key(ec.SECP256R1()), password=b"pw")),
        ],
    )
    def test_an_unusable_key_exports_unsigned_and_warns(
        self, settings, store, assessment_with_docs, sample_user, label, make_value
    ):
        settings.CRA_EXPORT_SIGNING_KEY = make_value()

        with _records(export_signing.__name__) as records:
            result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok, result.error
        assert result.value.signing_key_id == ""
        assert not any(key.endswith(".sig") for key in store.uploads)
        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, label
        assert settings.CRA_EXPORT_SIGNING_KEY not in warnings[0].getMessage()


@pytest.mark.django_db
class TestExportAuditEvent:
    @pytest.mark.parametrize("signed", [True, False])
    def test_every_export_is_audited_with_its_hash(self, settings, store, assessment_with_docs, sample_user, signed):
        key = ec.generate_private_key(ec.SECP256R1())
        settings.CRA_EXPORT_SIGNING_KEY = _private_pem(key) if signed else ""

        with _records("sbomify.compliance.audit") as records:
            result = build_export_package(assessment_with_docs, sample_user)

        events = [r for r in records if getattr(r, "event", None) == "cra.export.created"]
        assert len(events) == 1
        event = events[0]
        assert event.content_hash == result.value.content_hash
        assert event.package_id == result.value.id
        assert event.assessment_id == assessment_with_docs.id
        assert event.signing_key_id == (_kid(key) if signed else "")


@pytest.mark.django_db
class TestSignatureDownload:
    def _package(self, assessment, signing_key_id: str) -> CRAExportPackage:
        return CRAExportPackage.objects.create(
            assessment=assessment,
            storage_key=f"compliance/exports/{assessment.id}/{'0' * 64}.zip",
            content_hash="0" * 64,
            manifest={"format_version": "1.3"},
            signing_key_id=signing_key_id,
        )

    def test_a_signed_package_gets_a_signature_url(self, assessment, mock_s3_client):
        package = self._package(assessment, "0123456789abcdef")

        result = get_signature_url(package)

        assert result.ok
        assert result.value == "https://s3.example.com/presigned"
        call = mock_s3_client.generate_presigned_url.call_args.kwargs
        assert call["Params"]["Key"] == package.storage_key + ".sig"
        assert call["Params"]["ResponseContentType"] == "text/plain"
        assert call["Params"]["ResponseContentDisposition"].endswith('-000000000000.zip.sig"')
        assert call["ExpiresIn"] == 900

    def test_an_unsigned_package_has_no_signature_url(self, assessment):
        package = self._package(assessment, "")

        result = get_signature_url(package)

        assert result.ok
        assert result.value is None

    def test_the_download_endpoint_returns_both_urls(
        self, settings, authenticated_api_client, assessment, mock_s3_client
    ):
        settings.BILLING = False
        signed = self._package(assessment, "0123456789abcdef")
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/export/{signed.id}/download",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"] == "https://s3.example.com/presigned"
        assert body["signature_url"] == "https://s3.example.com/presigned"

    def test_the_download_endpoint_says_null_when_unsigned(
        self, settings, authenticated_api_client, assessment, mock_s3_client
    ):
        settings.BILLING = False
        unsigned = self._package(assessment, "")
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/export/{unsigned.id}/download",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["signature_url"] is None


@pytest.mark.django_db
class TestPublishedKeys:
    def test_the_current_key_is_published(self, client, signing_key):
        response = client.get(f"/.well-known/sbomify/export-keys/{_kid(signing_key)}.pem")

        assert response.status_code == 200
        assert response.content == _public_pem(signing_key)
        assert response["Content-Type"] == "application/x-pem-file"

    def test_a_retired_key_stays_published(self, client, settings, signing_key):
        old = ec.generate_private_key(ec.SECP256R1())
        older = ec.generate_private_key(ec.SECP256R1())
        settings.CRA_EXPORT_SIGNING_RETIRED_PUBLIC_KEYS = (_public_pem(old) + _public_pem(older)).decode()

        for key in (old, older):
            response = client.get(f"/.well-known/sbomify/export-keys/{_kid(key)}.pem")
            assert response.status_code == 200
            assert response.content == _public_pem(key)

    def test_an_unknown_key_is_404(self, client, signing_key):
        assert client.get("/.well-known/sbomify/export-keys/ffffffffffffffff.pem").status_code == 404

    def test_no_configured_key_publishes_nothing(self, client, no_signing_key, settings):
        settings.CRA_EXPORT_SIGNING_RETIRED_PUBLIC_KEYS = ""

        assert client.get("/.well-known/sbomify/export-keys/0123456789abcdef.pem").status_code == 404


class TestSystemCheck:
    def test_the_check_is_registered(self):
        from sbomify.apps.compliance.checks import check_export_signing_key

        assert check_export_signing_key in registry.registry.get_checks()

    def test_an_unusable_key_warns(self, settings):
        from sbomify.apps.compliance.checks import check_export_signing_key

        settings.CRA_EXPORT_SIGNING_KEY = "not a key"

        messages = check_export_signing_key(None)

        assert [m.id for m in messages] == ["compliance.W001"]
        assert "not a key" not in messages[0].msg

    @pytest.mark.parametrize("value", ["", "valid"])
    def test_an_unset_or_valid_key_is_quiet(self, settings, value):
        from sbomify.apps.compliance.checks import check_export_signing_key

        settings.CRA_EXPORT_SIGNING_KEY = (
            _private_pem(ec.generate_private_key(ec.SECP256R1())) if value == "valid" else ""
        )

        assert check_export_signing_key(None) == []

