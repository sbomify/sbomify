"""Tests for the ChecksumPlugin."""

import hashlib
import json
from pathlib import Path

from sbomify.apps.plugins.builtins.checksum import ChecksumPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory


class TestChecksumPlugin:
    """Tests for the ChecksumPlugin class."""

    def test_get_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = ChecksumPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "checksum"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_assess_returns_result(self, tmp_path: Path) -> None:
        """Test that assess returns a valid AssessmentResult."""
        # Create a test SBOM file
        sbom_content = json.dumps({"name": "test", "version": "1.0"}).encode("utf-8")
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file)

        assert result.plugin_name == "checksum"
        assert result.plugin_version == "1.0.0"
        assert result.category == "compliance"
        assert result.schema_version == "1.0"
        assert result.assessed_at is not None

    def test_assess_computes_correct_checksum(self, tmp_path: Path) -> None:
        """Test that assess computes the correct SHA256 checksum."""
        sbom_content = b'{"bomFormat": "CycloneDX", "specVersion": "1.5"}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        expected_checksum = hashlib.sha256(sbom_content).hexdigest()

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file)

        # Check the finding contains the correct checksum
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.id == "checksum:sha256"
        assert expected_checksum in finding.description
        assert finding.metadata["digest"] == expected_checksum

    def test_assess_finding_has_correct_structure(self, tmp_path: Path) -> None:
        """Test that the finding has all required fields."""
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(b"test content")

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file)

        finding = result.findings[0]
        assert finding.id == "checksum:sha256"
        assert finding.title == "SBOM Content Checksum"
        assert finding.description.startswith("SHA256:")
        assert finding.status == "pass"
        assert finding.severity == "info"

    def test_assess_summary(self, tmp_path: Path) -> None:
        """Test that assess returns correct summary."""
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(b"content")

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom-id", sbom_file)

        assert result.summary.total_findings == 1
        assert result.summary.pass_count == 1
        assert result.summary.fail_count == 0

    def test_assess_result_serializable(self, tmp_path: Path) -> None:
        """Test that result can be serialized to JSON."""
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(b'{"test": true}')

        plugin = ChecksumPlugin()
        result = plugin.assess("test-sbom", sbom_file)

        # Should not raise
        result_dict = result.to_dict()
        json_str = json.dumps(result_dict)

        # Verify it can be deserialized
        parsed = json.loads(json_str)
        assert parsed["plugin_name"] == "checksum"
        assert len(parsed["findings"]) == 1

    def test_deterministic_checksums(self, tmp_path: Path) -> None:
        """Test that checksums are deterministic across runs."""
        sbom_content = b'{"fixed": "content"}'
        sbom_file = tmp_path / "test.json"
        sbom_file.write_bytes(sbom_content)

        plugin = ChecksumPlugin()

        result1 = plugin.assess("sbom1", sbom_file)
        result2 = plugin.assess("sbom2", sbom_file)

        checksum1 = result1.findings[0].metadata["digest"]
        checksum2 = result2.findings[0].metadata["digest"]

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

        checksum1 = result1.findings[0].metadata["digest"]
        checksum2 = result2.findings[0].metadata["digest"]

        assert checksum1 != checksum2
