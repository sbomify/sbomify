"""Tests for the ChecksumPlugin (SBOM Integrity Verification)."""

import hashlib
import json
from pathlib import Path

from sbomify.apps.plugins.builtins.checksum import ChecksumPlugin
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory


class TestChecksumPlugin:
    """Tests for the ChecksumPlugin class."""

    def test_get_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = ChecksumPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "checksum"
        assert metadata.version == "1.1.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_integrity_verified_when_hashes_match(self, tmp_path: Path) -> None:
        """Test that integrity is verified when computed hash matches stored hash."""
        sbom_content = b'{"bomFormat": "CycloneDX", "specVersion": "1.5"}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        # Pre-compute the correct hash
        expected_hash = hashlib.sha256(sbom_content).hexdigest()
        context = SBOMContext(sha256_hash=expected_hash)

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file, context)

        assert result.plugin_name == "checksum"
        assert result.plugin_version == "1.1.0"
        assert result.category == "compliance"

        # Should pass with integrity verified
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.id == "checksum:integrity-verified"
        assert finding.title == "SBOM Integrity Verified"
        assert finding.status == "pass"
        assert finding.severity == "info"
        assert finding.metadata["computed_hash"] == expected_hash
        assert finding.metadata["stored_hash"] == expected_hash

        # Summary should show pass
        assert result.summary.pass_count == 1
        assert result.summary.fail_count == 0
        assert result.summary.warning_count == 0

    def test_integrity_failed_when_hashes_differ(self, tmp_path: Path) -> None:
        """Test that integrity check fails when hashes differ."""
        sbom_content = b'{"bomFormat": "CycloneDX", "specVersion": "1.5"}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        # Provide a different (wrong) stored hash
        wrong_hash = "a" * 64  # 64 hex chars
        context = SBOMContext(sha256_hash=wrong_hash)

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file, context)

        # Should fail with integrity check failed
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.id == "checksum:integrity-failed"
        assert finding.title == "SBOM Integrity Check Failed"
        assert finding.status == "fail"
        assert finding.severity == "critical"
        assert finding.metadata["stored_hash"] == wrong_hash
        assert finding.metadata["computed_hash"] != wrong_hash

        # Summary should show failure
        assert result.summary.pass_count == 0
        assert result.summary.fail_count == 1
        assert result.summary.warning_count == 0

    def test_warning_when_no_stored_hash(self, tmp_path: Path) -> None:
        """Test that warning is produced when no stored hash is available."""
        sbom_content = b'{"bomFormat": "CycloneDX", "specVersion": "1.5"}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        # No context or no hash in context
        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file, context=None)

        # Should warn about no stored hash
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.id == "checksum:no-stored-hash"
        assert finding.title == "No Stored Hash Available"
        assert finding.status == "warning"
        assert finding.severity == "medium"
        assert finding.metadata["stored_hash"] is None
        assert finding.metadata["computed_hash"] is not None

        # Summary should show warning
        assert result.summary.pass_count == 0
        assert result.summary.fail_count == 0
        assert result.summary.warning_count == 1

    def test_warning_when_context_has_no_hash(self, tmp_path: Path) -> None:
        """Test warning when context exists but has no hash."""
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(b"content")

        # Context with no hash (legacy SBOM scenario)
        context = SBOMContext(sha256_hash=None, sbom_format="cyclonedx")

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file, context)

        assert result.findings[0].id == "checksum:no-stored-hash"
        assert result.summary.warning_count == 1

    def test_assess_result_serializable(self, tmp_path: Path) -> None:
        """Test that result can be serialized to JSON."""
        sbom_content = b'{"test": true}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        expected_hash = hashlib.sha256(sbom_content).hexdigest()
        context = SBOMContext(sha256_hash=expected_hash)

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom", sbom_file, context)

        # Should not raise
        result_dict = result.to_dict()
        json_str = json.dumps(result_dict)

        # Verify it can be deserialized
        parsed = json.loads(json_str)
        assert parsed["plugin_name"] == "checksum"
        assert len(parsed["findings"]) == 1

    def test_metadata_includes_verification_flag(self, tmp_path: Path) -> None:
        """Test that result metadata includes verification_performed flag."""
        sbom_content = b"test content"
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        expected_hash = hashlib.sha256(sbom_content).hexdigest()

        plugin = ChecksumPlugin()

        # With stored hash - verification performed
        result_with_hash = plugin.assess(
            "test-sbom", sbom_file, SBOMContext(sha256_hash=expected_hash)
        )
        assert result_with_hash.metadata["verification_performed"] is True

        # Without stored hash - verification not performed
        result_no_hash = plugin.assess("test-sbom", sbom_file, context=None)
        assert result_no_hash.metadata["verification_performed"] is False

    def test_deterministic_checksums(self, tmp_path: Path) -> None:
        """Test that checksums are deterministic across runs."""
        sbom_content = b'{"fixed": "content"}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        plugin = ChecksumPlugin()

        result1 = plugin.assess("sbom1", sbom_file)
        result2 = plugin.assess("sbom2", sbom_file)

        checksum1 = result1.findings[0].metadata["computed_hash"]
        checksum2 = result2.findings[0].metadata["computed_hash"]

        assert checksum1 == checksum2

    def test_different_content_different_checksums(self, tmp_path: Path) -> None:
        """Test that different content produces different checksums."""
        file1 = tmp_path / "file1.json"
        file2 = tmp_path / "file2.json"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        plugin = ChecksumPlugin()

        result1 = plugin.assess("sbom1", file1)
        result2 = plugin.assess("sbom2", file2)

        checksum1 = result1.findings[0].metadata["computed_hash"]
        checksum2 = result2.findings[0].metadata["computed_hash"]

        assert checksum1 != checksum2

    def test_file_size_in_metadata(self, tmp_path: Path) -> None:
        """Test that file size is included in finding metadata."""
        sbom_content = b"x" * 1000  # 1000 bytes
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom", sbom_file)

        assert result.findings[0].metadata["size_bytes"] == 1000
