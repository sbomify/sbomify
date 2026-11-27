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


REKOR_BODY = base64.b64encode(json.dumps({"kind": "hashedrekord", "apiVersion": "0.0.1"}).encode()).decode()
LOG_ID = "c0d23d6ad406973f9559f3ba2d1ca01f84147d8ffc5b8445c224f98b9591801d"


def _legacy_bundle(with_cert: bool = True) -> bytes:
    """The shape ``cosign sign-blob --bundle`` writes in v2."""
    bundle: dict[str, Any] = {
        "base64Signature": base64.b64encode(b"signature").decode(),
        "rekorBundle": {
            "SignedEntryTimestamp": "c2V0",
            "Payload": {"body": REKOR_BODY, "integratedTime": 1700000000, "logIndex": 42, "logID": LOG_ID},
        },
    }
    if with_cert:
        pem = _fulcio_like_certificate().public_bytes(serialization.Encoding.PEM)
        bundle["cert"] = base64.b64encode(pem).decode()
    return json.dumps(bundle).encode()


def _rekor_response(body: str = REKOR_BODY, status: int = 200) -> MagicMock:
    response = MagicMock(status_code=status)
    response.json.return_value = {
        "entry-uuid": {
            "body": body,
            "verification": {
                "inclusionProof": {
                    "logIndex": 7,
                    "rootHash": "ab" * 32,
                    "treeSize": 100,
                    "hashes": ["cd" * 32],
                    "checkpoint": "rekor.sigstore.dev - 1\n100\nq6s=\n",
                }
            },
        }
    }
    session = MagicMock()
    session.get.return_value = response
    return session


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

    @patch(f"{MODULE}.get_http_session")
    def test_legacy_bundle_is_rewritten_and_verified_in_process(self, mock_session: MagicMock) -> None:
        mock_session.return_value = _rekor_response()
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_verify_sigstore_bundle", return_value=_signature_pass()) as verify:
            finding = plugin._verify_cosign_bundle(_legacy_bundle(), b"sbom bytes")

        assert finding.status == "pass"
        converted_bytes, sbom, bundle_format = verify.call_args.args
        assert sbom == b"sbom bytes"
        assert bundle_format == "cosign-legacy"
        converted = json.loads(converted_bytes)
        assert converted["mediaType"] == "application/vnd.dev.sigstore.bundle.v0.3+json"
        assert converted["messageSignature"] == {
            "messageDigest": {
                "algorithm": "SHA2_256",
                "digest": base64.b64encode(hashlib.sha256(b"sbom bytes").digest()).decode(),
            },
            "signature": base64.b64encode(b"signature").decode(),
        }
        entry = converted["verificationMaterial"]["tlogEntries"][0]
        assert entry["logIndex"] == "42"
        assert entry["logId"]["keyId"] == base64.b64encode(bytes.fromhex(LOG_ID)).decode()
        assert entry["kindVersion"] == {"kind": "hashedrekord", "version": "0.0.1"}
        assert entry["canonicalizedBody"] == REKOR_BODY
        assert entry["inclusionPromise"] == {"signedEntryTimestamp": "c2V0"}
        assert entry["inclusionProof"]["logIndex"] == "7"
        assert entry["inclusionProof"]["hashes"] == [base64.b64encode(bytes.fromhex("cd" * 32)).decode()]
        assert mock_session.return_value.get.call_args.kwargs["params"] == {"logIndex": 42}

    def test_legacy_bundle_signer_comes_from_its_certificate(self) -> None:
        """The certificate survives the rewrite, so a pass names the real signer."""
        plugin = SBOMVerificationPlugin()
        document = json.loads(_legacy_bundle())

        der = plugin._pem_to_der(base64.b64decode(document["cert"]))

        assert plugin._signer_identity(x509.load_der_x509_certificate(der)) == {"identity": SIGNER, "issuer": ISSUER}

    @patch(f"{MODULE}.get_http_session")
    def test_rekor_entry_for_another_body_is_refused(self, mock_session: MagicMock) -> None:
        mock_session.return_value = _rekor_response(body="b3RoZXI=")
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_verify_sigstore_bundle") as verify:
            finding = plugin._verify_cosign_bundle(_legacy_bundle(), b"sbom bytes")

        verify.assert_not_called()
        assert finding.status == "warning"
        assert "not the one this bundle names" in finding.description

    @pytest.mark.parametrize("status", [404, 503])
    @patch(f"{MODULE}.get_http_session")
    def test_rekor_unreachable_is_a_warning(self, mock_session: MagicMock, status: int) -> None:
        mock_session.return_value = _rekor_response(status=status)

        finding = SBOMVerificationPlugin()._verify_cosign_bundle(_legacy_bundle(), b"sbom bytes")

        assert finding.status == "warning"
        assert finding.title == "Transparency Log Unavailable"

    @patch(f"{MODULE}.get_http_session")
    def test_key_signed_legacy_bundle_is_not_verifiable(self, mock_session: MagicMock) -> None:
        finding = SBOMVerificationPlugin()._verify_cosign_bundle(_legacy_bundle(with_cert=False), b"sbom")

        assert finding.status == "warning"
        assert "key" in finding.title.lower()
        mock_session.assert_not_called()

    def test_incomplete_legacy_bundle_fails(self) -> None:
        document = json.loads(_legacy_bundle())
        del document["rekorBundle"]

        finding = SBOMVerificationPlugin()._verify_cosign_bundle(json.dumps(document).encode(), b"sbom")

        assert finding.status == "fail"

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

        finding = self._digest_finding(tmp_path, build)
        assert finding.metadata is not None
        assert finding.metadata["matched_subject"] == "sbom.json"

    def test_multi_line_jsonl(self, tmp_path: Path) -> None:
        def build(sha256: str) -> bytes:
            lines = [json.dumps(self._envelope("0" * 64)), json.dumps(self._envelope(sha256))]
            return "\n".join(lines).encode() + b"\n"

        finding = self._digest_finding(tmp_path, build)
        assert finding.metadata is not None
        assert finding.metadata["matched_subject"] == "sbom.json"

    def test_unrecognised_document(self, tmp_path: Path) -> None:
        finding = self._digest_finding(tmp_path, lambda _sha256: b'{"random": "data"}')

        assert finding.status == "fail"
        assert finding.title == "Provenance Format Unrecognised"


class TestSignedProvenance:
    """Only provenance whose signature verifies counts as an attestation.

    Anyone who can upload can write a Statement naming the SBOM's digest, so a
    matching subject alone proves nothing about who built it.
    """

    BUNDLE_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"

    @classmethod
    def _bundle(cls, sha256: str) -> dict[str, Any]:
        return {
            "mediaType": cls.BUNDLE_TYPE,
            "verificationMaterial": {"certificate": {"rawBytes": "AAAA"}},
            "dsseEnvelope": TestProvenanceShapes._envelope(sha256),
        }

    @staticmethod
    def _verifier(signed_digest: str | None) -> MagicMock:
        verifier = MagicMock()
        if signed_digest is None:
            verifier.verify_dsse.side_effect = ValueError("signature does not match\nmore detail")
        else:
            statement = TestProvenanceShapes._statement(signed_digest)
            verifier.verify_dsse.return_value = ("application/vnd.in-toto+json", json.dumps(statement).encode())
        return verifier

    def _assess(self, tmp_path: Path, build: Callable[[str], bytes], signed_digest: str | None = "") -> Any:
        """Assess with ``build(sha256)`` as the provenance; the verifier signs ``signed_digest``.

        ``signed_digest=""`` signs this SBOM's own digest, ``None`` fails verification.
        """
        sbom_file, sha256 = _plain_sbom(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="p.json")
        plugin = SBOMVerificationPlugin()
        bundle = MagicMock(signing_certificate=_fulcio_like_certificate())
        verifier = self._verifier(sha256 if signed_digest == "" else signed_digest)
        with (
            patch.object(plugin, "_fetch_blob", return_value=build(sha256)),
            patch("sigstore.models.Bundle.from_json", return_value=bundle),
            patch("sigstore.verify.Verifier.production", return_value=verifier),
        ):
            return plugin.assess("sbom-1", sbom_file, context=context)

    def test_an_unsigned_statement_does_not_attest(self, tmp_path: Path) -> None:
        result = self._assess(tmp_path, lambda sha256: json.dumps(TestProvenanceShapes._statement(sha256)).encode())

        assert _by_id(result, "verification:provenance-digest").status == "warning"
        assert _by_id(result, "verification:attestation").status == "fail"

    def test_an_envelope_signature_sbomify_cannot_check_does_not_attest(self, tmp_path: Path) -> None:
        def build(sha256: str) -> bytes:
            envelope = TestProvenanceShapes._envelope(sha256)
            envelope["signatures"] = [{"sig": "abc123"}]
            return json.dumps(envelope).encode()

        result = self._assess(tmp_path, build)

        assert _by_id(result, "verification:provenance-digest").status == "warning"
        assert _by_id(result, "verification:attestation").status == "fail"

    def test_a_verified_bundle_naming_this_sbom_attests(self, tmp_path: Path) -> None:
        result = self._assess(tmp_path, lambda sha256: json.dumps(self._bundle(sha256)).encode())

        finding = _by_id(result, "verification:provenance-digest")
        assert finding.status == "pass"
        assert SIGNER in finding.description
        assert finding.metadata is not None
        assert finding.metadata["identity"] == SIGNER
        assert _by_id(result, "verification:attestation").status == "pass"

    def test_a_bundle_whose_signature_fails_is_a_failure(self, tmp_path: Path) -> None:
        result = self._assess(tmp_path, lambda sha256: json.dumps(self._bundle(sha256)).encode(), signed_digest=None)

        finding = _by_id(result, "verification:provenance-digest")
        assert finding.status == "fail"
        assert "\n" not in finding.description
        assert _by_id(result, "verification:attestation").status == "fail"

    def test_a_signature_over_another_artifact_does_not_attest_this_one(self, tmp_path: Path) -> None:
        """A real signed bundle for something else, beside an unsigned line naming this SBOM."""

        def build(sha256: str) -> bytes:
            lines = [json.dumps(self._bundle("0" * 64)), json.dumps(TestProvenanceShapes._envelope(sha256))]
            return "\n".join(lines).encode()

        result = self._assess(tmp_path, build, signed_digest="0" * 64)

        assert _by_id(result, "verification:provenance-digest").status == "warning"
        assert _by_id(result, "verification:attestation").status == "fail"
