"""Tests for the unified SBOMVerificationPlugin."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.plugins.builtins.verification import (
    AttestationNotYetAvailableError,
    SBOMVerificationPlugin,
)
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory


def _sbom_file(tmp_path: Path, content: bytes = b'{"test": true}') -> tuple[Path, str]:
    """Write content to a temp file and return (path, sha256)."""
    path = tmp_path / "test.json"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def _cyclonedx_with_vcs(tmp_path: Path, org: str = "acme", repo: str = "widget") -> tuple[Path, str]:
    """Write a minimal CycloneDX SBOM with a GitHub VCS externalReference."""
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {
            "component": {
                "name": repo,
                "type": "application",
                "externalReferences": [
                    {"type": "vcs", "url": f"https://github.com/{org}/{repo}"},
                ],
            }
        },
    }
    body = json.dumps(sbom).encode()
    path = tmp_path / "sbom.json"
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


class TestMetadata:
    def test_metadata(self) -> None:
        plugin = SBOMVerificationPlugin()
        meta = plugin.get_metadata()

        assert meta.name == "sbom-verification"
        assert meta.version == "2.0.0"
        # The unified plugin lives in the ``attestation`` category so a
        # single ``requires_one_of`` clause in BSI/FDA/etc. matches it
        # without needing to enumerate plugins by name.
        assert meta.category == AssessmentCategory.ATTESTATION
        assert meta.supported_bom_types == ["sbom"]


class TestDigestIntegrity:
    def test_digest_integrity_pass(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:digest-integrity")
        assert finding.status == "pass"
        assert finding.metadata is not None
        assert finding.metadata["computed_hash"] == sha256

    def test_digest_integrity_fail(self, tmp_path: Path) -> None:
        sbom_file, _ = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash="a" * 64)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:digest-integrity")
        assert finding.status == "fail"
        assert finding.severity == "critical"

    def test_digest_integrity_no_stored_hash(self, tmp_path: Path) -> None:
        sbom_file, _ = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=None)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:digest-integrity")
        assert finding.status == "warning"


class TestSignaturePresent:
    def test_signature_not_present(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, signature_blob_key=None)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:signature-present")
        assert finding.status == "warning"

    def test_signature_present(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, signature_blob_key="abc.sig")
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=b"sig-data"):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:signature-present")
        assert finding.status == "pass"


class TestSignatureValid:
    def test_signature_present_unsupported_type(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(
            sha256_hash=sha256,
            signature_blob_key="abc.sig",
            signature_type="pgp-detached",
        )
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=b"pgp-data"):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:signature-valid")
        assert finding.status == "warning"
        assert finding.metadata is not None
        assert finding.metadata["signature_type"] == "pgp-detached"

    def test_signature_blob_missing_from_s3(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(
            sha256_hash=sha256,
            signature_blob_key="missing.sig",
            signature_type="cosign-bundle",
        )
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:signature-valid")
        assert finding.status == "fail"
        assert finding.title == "Signature Blob Missing"

    def test_signature_skipped_when_no_signature(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:signature-valid")
        assert finding.status == "warning"


class TestProvenancePresent:
    def test_provenance_not_present(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key=None)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:provenance-present")
        assert finding.status == "warning"

    def test_provenance_present(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="abc.provenance.json")
        plugin = SBOMVerificationPlugin()

        statement = {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [{"name": "test.json", "digest": {"sha256": sha256}}],
        }
        with patch.object(plugin, "_fetch_blob", return_value=json.dumps(statement).encode()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:provenance-present")
        assert finding.status == "pass"


class TestProvenanceDigest:
    def test_provenance_digest_match(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="prov.json")

        statement = {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [{"name": "test.json", "digest": {"sha256": sha256}}],
        }
        plugin = SBOMVerificationPlugin()
        with patch.object(plugin, "_fetch_blob", return_value=json.dumps(statement).encode()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:provenance-digest")
        assert finding.status == "pass"

    def test_provenance_digest_mismatch(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="prov.json")

        statement = {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [{"name": "test.json", "digest": {"sha256": "b" * 64}}],
        }
        plugin = SBOMVerificationPlugin()
        with patch.object(plugin, "_fetch_blob", return_value=json.dumps(statement).encode()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:provenance-digest")
        assert finding.status == "fail"
        assert "Mismatch" in finding.title

    def test_provenance_dsse_envelope(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="prov.json")

        statement = {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [{"name": "test.json", "digest": {"sha256": sha256}}],
        }
        envelope = {
            "payloadType": "application/vnd.in-toto+json",
            "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
            "signatures": [{"sig": "abc123"}],
        }
        plugin = SBOMVerificationPlugin()
        with patch.object(plugin, "_fetch_blob", return_value=json.dumps(envelope).encode()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:provenance-digest")
        assert finding.status == "pass"

    def test_provenance_parse_error(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256, provenance_blob_key="prov.json")

        plugin = SBOMVerificationPlugin()
        with patch.object(plugin, "_fetch_blob", return_value=b"not-json{{{"):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        finding = next(f for f in result.findings if f.id == "verification:provenance-digest")
        assert finding.status == "fail"
        assert "Parse Error" in finding.title


class TestOverall:
    def test_overall_provenance_passes_summary(self, tmp_path: Path) -> None:
        """Provenance subject-digest match satisfies the attestation summary.

        Six sub-findings + the aggregating ``verification:attestation``
        summary = 7 total. The plugin reports a passing summary when
        any one cryptographic source verified.
        """
        content = b'{"bomFormat": "CycloneDX"}'
        sbom_file, sha256 = _sbom_file(tmp_path, content)

        statement = {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [{"name": "test.json", "digest": {"sha256": sha256}}],
        }
        provenance_blob = json.dumps(statement).encode()

        context = SBOMContext(
            sha256_hash=sha256,
            signature_blob_key="abc.sig",
            signature_type="pgp-detached",
            provenance_blob_key="prov.json",
        )
        plugin = SBOMVerificationPlugin()

        def mock_fetch(key: str) -> bytes | None:
            if key == "abc.sig":
                return b"pgp-signature-data"
            if key == "prov.json":
                return provenance_blob
            return None

        with patch.object(plugin, "_fetch_blob", side_effect=mock_fetch):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        assert result.summary.fail_count == 0
        assert result.summary.total_findings == 7

        statuses = {f.id: f.status for f in result.findings}
        assert statuses["verification:digest-integrity"] == "pass"
        assert statuses["verification:signature-present"] == "pass"
        # pgp-detached is unsupported -> warning (not fail)
        assert statuses["verification:signature-valid"] == "warning"
        assert statuses["verification:provenance-present"] == "pass"
        assert statuses["verification:provenance-digest"] == "pass"
        # No GitHub VCS in this minimal SBOM -> warning, not fail.
        assert statuses["verification:github-attestation"] == "warning"
        # Provenance match → summary passes.
        assert statuses["verification:attestation"] == "pass"

    def test_result_serializable(self, tmp_path: Path) -> None:
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        result_dict = result.to_dict()
        json_str = json.dumps(result_dict)
        parsed = json.loads(json_str)
        assert parsed["plugin_name"] == "sbom-verification"
        # 6 sub-findings (digest, signature x2, provenance x2, github-att) + summary.
        assert len(parsed["findings"]) == 7


_COSIGN_PATCH = "sbomify.apps.plugins.builtins.verification.SBOMVerificationPlugin._verify_cosign_bundle"


class TestCosignBundleVerification:
    """Tests for _verify_cosign_bundle paths."""

    def _run_with_mock(self, tmp_path: Path, mock_status: str, mock_desc: str) -> Any:
        from sbomify.apps.plugins.sdk.results import Finding

        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(
            sha256_hash=sha256,
            signature_blob_key=f"{sha256}.sig",
            signature_type="cosign-bundle",
        )
        plugin = SBOMVerificationPlugin()
        mock_finding = Finding(
            id="verification:signature-valid",
            title="Test",
            description=mock_desc,
            status=mock_status,
            severity="info",
        )
        with (
            patch.object(plugin, "_fetch_blob", return_value=b"bundle"),
            patch(_COSIGN_PATCH) as mock_verify,
        ):
            mock_verify.return_value = mock_finding
            result = plugin.assess("sbom-1", sbom_file, context=context)
        return next(f for f in result.findings if f.id == "verification:signature-valid")

    def test_cosign_import_error(self, tmp_path: Path) -> None:
        finding = self._run_with_mock(tmp_path, "warning", "sigstore not available")
        assert finding.status == "warning"

    def test_cosign_verification_failure(self, tmp_path: Path) -> None:
        finding = self._run_with_mock(tmp_path, "fail", "bundle invalid")
        assert finding.status == "fail"

    def test_cosign_verification_success(self, tmp_path: Path) -> None:
        finding = self._run_with_mock(tmp_path, "pass", "verified")
        assert finding.status == "pass"


class TestGitHubAttestation:
    """Tests for the GitHub-attestation source folded in from the old plugin."""

    @staticmethod
    def _make_response(status: int, payload: dict | None = None) -> Any:
        response = MagicMock()
        response.status_code = status
        response.json.return_value = payload or {}
        response.text = json.dumps(payload) if payload else ""
        return response

    def test_no_vcs_info_emits_warning(self, tmp_path: Path) -> None:
        """SBOM without a GitHub VCS link → github-attestation warning, not fail."""
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        gh = next(f for f in result.findings if f.id == "verification:github-attestation")
        assert gh.status == "warning"
        assert gh.metadata is not None
        assert gh.metadata["reason"] == "no_vcs_info"

    @patch("sbomify.apps.plugins.builtins.verification.shutil.which", return_value="/usr/bin/cosign")
    @patch("sbomify.apps.plugins.builtins.verification.subprocess.run")
    @patch("sbomify.apps.plugins.builtins.verification.get_http_session")
    def test_github_attestation_pass(
        self,
        mock_get_session: MagicMock,
        mock_run: MagicMock,
        _mock_which: MagicMock,
        tmp_path: Path,
    ) -> None:
        sbom_file, sha256 = _cyclonedx_with_vcs(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        bundle_payload = {"attestations": [{"bundle": {"mediaType": "application/vnd.dev.sigstore.bundle+json;v=0.3"}}]}
        session = MagicMock()
        session.get.return_value = self._make_response(200, bundle_payload)
        mock_get_session.return_value = session
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        gh = next(f for f in result.findings if f.id == "verification:github-attestation")
        assert gh.status == "pass"
        assert gh.metadata is not None
        assert gh.metadata["github_org"] == "acme"
        assert gh.metadata["github_repo"] == "widget"

        # Summary inherits the GitHub-attestation pass.
        summary_finding = next(f for f in result.findings if f.id == "verification:attestation")
        assert summary_finding.status == "pass"

    @patch("sbomify.apps.plugins.builtins.verification.get_http_session")
    def test_github_attestation_404_raises_retry(
        self,
        mock_get_session: MagicMock,
        tmp_path: Path,
    ) -> None:
        """``404`` from the GitHub API must propagate ``RetryLaterError``."""
        sbom_file, sha256 = _cyclonedx_with_vcs(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        session = MagicMock()
        session.get.return_value = self._make_response(404, {"message": "Not Found"})
        mock_get_session.return_value = session

        with (
            patch.object(plugin, "_fetch_blob", return_value=None),
            pytest.raises(AttestationNotYetAvailableError),
        ):
            plugin.assess("sbom-1", sbom_file, context=context)

    @patch("sbomify.apps.plugins.builtins.verification.shutil.which", return_value=None)
    @patch("sbomify.apps.plugins.builtins.verification.get_http_session")
    def test_github_attestation_cosign_missing_is_warning(
        self,
        mock_get_session: MagicMock,
        _mock_which: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No ``cosign`` binary → warning so the run isn't blocked from passing.

        Per-source verification failures emit ``warning`` status rather
        than ``fail``: the aggregating ``verification:attestation`` summary
        is the single ``fail`` signal when *no* cryptographic source
        verified. That way a stored cosign-bundle signature passing AND
        a missing cosign CLI doesn't block the run from satisfying BSI's
        ``requires_one_of: attestation`` gate.
        """
        sbom_file, sha256 = _cyclonedx_with_vcs(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        bundle_payload = {"attestations": [{"bundle": {"mediaType": "x"}}]}
        session = MagicMock()
        session.get.return_value = self._make_response(200, bundle_payload)
        mock_get_session.return_value = session

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        gh = next(f for f in result.findings if f.id == "verification:github-attestation")
        assert gh.status == "warning"


class TestAttestationSummary:
    """Tests for the aggregating ``verification:attestation`` finding."""

    def test_summary_fail_when_no_crypto_source_verified(self, tmp_path: Path) -> None:
        """All sub-checks warn → summary fails so BSI dependency gate doesn't pass.

        Exactly the scenario behind the latent bug: digest passed, every
        other check warned, github-attestation warned (no VCS). Without
        the summary, ``pass_count == 1`` would falsely satisfy
        ``requires_one_of: attestation``.
        """
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(sha256_hash=sha256)
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=None):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        summary = next(f for f in result.findings if f.id == "verification:attestation")
        assert summary.status == "fail"
        assert result.summary.fail_count >= 1

    def test_summary_fail_when_all_crypto_sources_failed(self, tmp_path: Path) -> None:
        """At least one source attempted, all failed → summary fails."""
        sbom_file, sha256 = _sbom_file(tmp_path)
        context = SBOMContext(
            sha256_hash=sha256,
            signature_blob_key="abc.sig",
            signature_type="cosign-bundle",
        )
        plugin = SBOMVerificationPlugin()

        # Force the cosign-bundle path to return a fail finding.
        from sbomify.apps.plugins.sdk.results import Finding

        fail_finding = Finding(
            id="verification:signature-valid",
            title="Cosign Signature Verification Failed",
            description="forced fail for test",
            status="fail",
            severity="high",
        )
        with (
            patch.object(plugin, "_fetch_blob", return_value=b"bundle"),
            patch.object(plugin, "_verify_cosign_bundle", return_value=fail_finding),
        ):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        summary = next(f for f in result.findings if f.id == "verification:attestation")
        assert summary.status == "fail"

    def test_summary_pass_with_provenance_match(self, tmp_path: Path) -> None:
        """Any single passing crypto source flips the summary to pass."""
        sbom_file, sha256 = _sbom_file(tmp_path)
        statement = {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [{"name": "x", "digest": {"sha256": sha256}}],
        }
        provenance_blob = base64.b64encode(json.dumps(statement).encode()).decode()
        envelope = {"payloadType": "application/vnd.in-toto+json", "payload": provenance_blob}

        context = SBOMContext(
            sha256_hash=sha256,
            provenance_blob_key="prov.json",
        )
        plugin = SBOMVerificationPlugin()

        with patch.object(plugin, "_fetch_blob", return_value=json.dumps(envelope).encode()):
            result = plugin.assess("sbom-1", sbom_file, context=context)

        summary = next(f for f in result.findings if f.id == "verification:attestation")
        assert summary.status == "pass"
        assert summary.metadata is not None
        assert "verification:provenance-digest" in summary.metadata["sources_passed"]
