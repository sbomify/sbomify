"""The signature and provenance shapes real pipelines upload, and how a run ends.

Each case here is one a real upload got wrong: a cosign v2 bundle that the
sigstore library cannot load, a GitHub lookup that held back a signature that
had already verified, and provenance written by ``cosign attest-blob`` or as
a multi-line ``.intoto.jsonl``.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from sbomify.apps.plugins.builtins.verification import AttestationNotYetAvailableError, SBOMVerificationPlugin
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.plugins.sdk.results import Finding

SIGNER = "https://github.com/acme/widget/.github/workflows/release.yml@refs/tags/v1.0.0"
ISSUER = "https://token.actions.githubusercontent.com"
MODULE = "sbomify.apps.plugins.builtins.verification"


def _fulcio_like_certificate() -> x509.Certificate:
    """A certificate carrying the SAN and issuer extensions Fulcio writes."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "sigstore.dev")])
    now = datetime.datetime.now(datetime.timezone.utc)
    issuer_utf8 = ISSUER.encode()
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(minutes=10))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(SIGNER)]), critical=True)
        .add_extension(
            x509.UnrecognizedExtension(
                x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.8"), bytes([0x0C, len(issuer_utf8)]) + issuer_utf8
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )


def _legacy_bundle(with_cert: bool = True) -> bytes:
    """The shape ``cosign sign-blob --bundle`` writes in v2."""
    bundle: dict[str, Any] = {
        "base64Signature": base64.b64encode(b"signature").decode(),
        "rekorBundle": {"SignedEntryTimestamp": "", "Payload": {}},
    }
    if with_cert:
        pem = _fulcio_like_certificate().public_bytes(serialization.Encoding.PEM)
        bundle["cert"] = base64.b64encode(pem).decode()
    return json.dumps(bundle).encode()


def _cyclonedx_with_vcs(tmp_path: Path) -> tuple[Path, str]:
    body = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {
                "component": {
                    "name": "widget",
                    "type": "application",
                    "externalReferences": [{"type": "vcs", "url": "https://github.com/acme/widget"}],
                }
            },
        }
    ).encode()
    path = tmp_path / "sbom.json"
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


def _plain_sbom(tmp_path: Path) -> tuple[Path, str]:
    body = b'{"test": true}'
    path = tmp_path / "sbom.json"
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


def _signature_pass() -> Finding:
    return SBOMVerificationPlugin()._signature_verified({"identity": SIGNER, "issuer": ISSUER}, "sigstore")


def _by_id(result: Any, finding_id: str) -> Finding:
    return next(f for f in result.findings if f.id == finding_id)


class TestBundleFormats:
    def test_signer_identity_is_read_from_a_fulcio_certificate(self) -> None:
        identity = SBOMVerificationPlugin._signer_identity(_fulcio_like_certificate())

        assert identity == {"identity": SIGNER, "issuer": ISSUER}

    def test_a_verified_signature_names_its_signer(self) -> None:
        finding = _signature_pass()

        assert finding.status == "pass"
        assert SIGNER in finding.description
        assert ISSUER in finding.description
        assert finding.metadata is not None
        assert finding.metadata["identity_verified"] is False

    def test_new_format_bundle_goes_to_the_sigstore_library(self) -> None:
        plugin = SBOMVerificationPlugin()
        bundle = json.dumps({"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}).encode()

        with patch.object(plugin, "_verify_sigstore_bundle", return_value=_signature_pass()) as verify:
            finding = plugin._verify_cosign_bundle(bundle, b"sbom")

        verify.assert_called_once_with(bundle, b"sbom")
        assert finding.status == "pass"

    def test_sigstore_library_errors_are_one_line(self) -> None:
        """A pydantic dump of every missing field is not something to show a user."""
        plugin = SBOMVerificationPlugin()
        bundle = json.dumps({"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}).encode()

        finding = plugin._verify_sigstore_bundle(bundle, b"sbom")

        assert finding.status == "fail"
        assert "\n" not in finding.description

    @patch(f"{MODULE}.shutil.which", return_value="/usr/bin/cosign")
    @patch(f"{MODULE}.subprocess.run")
    def test_legacy_bundle_is_verified_by_cosign(self, mock_run: MagicMock, _which: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="Verified OK", stderr="")

        finding = SBOMVerificationPlugin()._verify_cosign_bundle(_legacy_bundle(), b"sbom bytes")

        assert finding.status == "pass"
        assert finding.metadata is not None
        assert finding.metadata["bundle_format"] == "cosign-legacy"
        assert finding.metadata["identity"] == SIGNER
        cmd = mock_run.call_args.args[0]
        assert cmd[:2] == ["/usr/bin/cosign", "verify-blob"]
        assert "--bundle" in cmd

    @patch(f"{MODULE}.shutil.which", return_value="/usr/bin/cosign")
    @patch(f"{MODULE}.subprocess.run")
    def test_legacy_bundle_cosign_rejects(self, mock_run: MagicMock, _which: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: error verifying bundle: matching bundle to payload\nmore"
        )

        finding = SBOMVerificationPlugin()._verify_cosign_bundle(_legacy_bundle(), b"sbom bytes")

        assert finding.status == "fail"
        assert "matching bundle to payload" in finding.description
        assert "more" not in finding.description

    @patch(f"{MODULE}.shutil.which", return_value=None)
    def test_legacy_bundle_without_cosign_is_a_warning(self, _which: MagicMock) -> None:
        finding = SBOMVerificationPlugin()._verify_cosign_bundle(_legacy_bundle(), b"sbom bytes")

        assert finding.status == "warning"

    @patch(f"{MODULE}.subprocess.run")
    def test_key_signed_legacy_bundle_is_not_verifiable(self, mock_run: MagicMock) -> None:
        finding = SBOMVerificationPlugin()._verify_cosign_bundle(_legacy_bundle(with_cert=False), b"sbom")

        assert finding.status == "warning"
        assert "key" in finding.title.lower()
        mock_run.assert_not_called()

    @pytest.mark.parametrize("blob", [b"not json", b"[]", b'{"some": "json"}'])
    def test_anything_else_fails(self, blob: bytes) -> None:
        finding = SBOMVerificationPlugin()._verify_cosign_bundle(blob, b"sbom")

        assert finding.status == "fail"
        assert finding.title == "Signature Is Not a Sigstore Bundle"


class TestGitHubDoesNotHoldBackAVerifiedSignature:
    @staticmethod
    def _github_404() -> MagicMock:
        response = MagicMock(status_code=404, headers={}, text='{"message": "Not Found"}')
        response.json.return_value = {"message": "Not Found"}
        session = MagicMock()
        session.get.return_value = response
        return session

    @patch(f"{MODULE}.get_http_session")
    def test_no_attestation_on_github_after_a_verified_signature_completes(
        self, mock_session: MagicMock, tmp_path: Path
    ) -> None:
        mock_session.return_value = self._github_404()
        sbom_file, sha256 = _cyclonedx_with_vcs(tmp_path)
        context = SBOMContext(sha256_hash=sha256, signature_blob_key="s.sig", signature_type="cosign-bundle")
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_check_signature_valid", return_value=_signature_pass()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        github = _by_id(result, "verification:github-attestation")
        assert github.status == "info"
        assert github.metadata == {"reason": "not_retried_other_source_verified"}
        assert _by_id(result, "verification:attestation").status == "pass"
        assert result.summary.info_count == 1
        assert result.summary.fail_count == 0

    @patch(f"{MODULE}.get_http_session")
    def test_a_failed_signature_still_waits_for_github(self, mock_session: MagicMock, tmp_path: Path) -> None:
        mock_session.return_value = self._github_404()
        sbom_file, sha256 = _cyclonedx_with_vcs(tmp_path)
        context = SBOMContext(sha256_hash=sha256, signature_blob_key="s.sig", signature_type="cosign-bundle")
        plugin = SBOMVerificationPlugin()
        failed = SBOMVerificationPlugin._signature_finding("fail", "Cosign Signature Verification Failed", "bad")

        with (
            patch.object(plugin, "_check_signature_valid", return_value=failed),
            pytest.raises(AttestationNotYetAvailableError),
        ):
            plugin.assess("sbom-1", sbom_file, context=context)

    def test_no_repository_link_is_informational_once_verified(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _plain_sbom(tmp_path)
        context = SBOMContext(sha256_hash=sha256, signature_blob_key="s.sig", signature_type="cosign-bundle")
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_check_signature_valid", return_value=_signature_pass()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        assert _by_id(result, "verification:github-attestation").status == "info"
        assert result.summary.warning_count == 2  # no provenance attached, nothing to check it against


class TestProvenanceShapes:
    @staticmethod
    def _statement(sha256: str) -> dict[str, Any]:
        return {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": "sbom.json", "digest": {"sha256": sha256}}],
            "predicateType": "https://slsa.dev/provenance/v1",
            "predicate": {},
        }

    @classmethod
    def _envelope(cls, sha256: str) -> dict[str, Any]:
        return {
            "payloadType": "application/vnd.in-toto+json",
            "payload": base64.b64encode(json.dumps(cls._statement(sha256)).encode()).decode(),
            "signatures": [],
        }

    def _digest_finding(self, tmp_path: Path, build: Callable[[str], bytes]) -> Finding:
        sbom_file, sha256 = _plain_sbom(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="p.json")
        plugin = SBOMVerificationPlugin()
        with patch.object(plugin, "_fetch_blob", return_value=build(sha256)):
            return _by_id(plugin.assess("sbom-1", sbom_file, context=context), "verification:provenance-digest")

    def test_cosign_attest_blob_bundle(self, tmp_path: Path) -> None:
        def build(sha256: str) -> bytes:
            bundle = {
                "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                "dsseEnvelope": self._envelope(sha256),
            }
            return json.dumps(bundle).encode()

        assert self._digest_finding(tmp_path, build).status == "pass"

    def test_multi_line_jsonl(self, tmp_path: Path) -> None:
        def build(sha256: str) -> bytes:
            lines = [json.dumps(self._envelope("0" * 64)), json.dumps(self._envelope(sha256))]
            return "\n".join(lines).encode() + b"\n"

        assert self._digest_finding(tmp_path, build).status == "pass"

    def test_unrecognised_document(self, tmp_path: Path) -> None:
        finding = self._digest_finding(tmp_path, lambda _sha256: b'{"random": "data"}')

        assert finding.status == "fail"
        assert finding.title == "Provenance Format Unrecognised"
