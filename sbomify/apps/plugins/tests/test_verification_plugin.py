"""Tests for the SBOMVerificationPlugin."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sbomify.apps.plugins.builtins.verification import SBOMVerificationPlugin
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory


def _sbom_file(tmp_path: Path, content: bytes = b'{"test": true}') -> tuple[Path, str]:
    """Write content to a temp file and return (path, sha256)."""
    path = tmp_path / "test.json"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


class TestMetadata:
    def test_metadata(self) -> None:
        plugin = SBOMVerificationPlugin()
        meta = plugin.get_metadata()

        assert meta.name == "sbom-verification"
        assert meta.version == "1.0.0"
        assert meta.category == AssessmentCategory.COMPLIANCE
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
    def test_overall_no_failures(self, tmp_path: Path) -> None:
        """Full context with everything present and matching — no fail findings."""
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
        assert result.summary.total_findings == 5

        statuses = {f.id: f.status for f in result.findings}
        assert statuses["verification:digest-integrity"] == "pass"
        assert statuses["verification:signature-present"] == "pass"
        # pgp-detached is unsupported -> warning (not fail)
        assert statuses["verification:signature-valid"] == "warning"
        assert statuses["verification:provenance-present"] == "pass"
        assert statuses["verification:provenance-digest"] == "pass"

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
        assert len(parsed["findings"]) == 5


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
