"""Tests for the OSV vulnerability scanning plugin.

Tests scanning SBOMs for vulnerabilities using mocked osv-scanner subprocess.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from sbomify.apps.plugins.builtins.osv import OSVPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult

# Sample osv-scanner output with vulnerabilities
SAMPLE_OSV_OUTPUT = {
    "results": [
        {
            "source": {"path": "/tmp/test.cdx.json", "type": "sbom"},
            "packages": [
                {
                    "package": {
                        "name": "lodash",
                        "version": "4.17.20",
                        "ecosystem": "npm",
                    },
                    "vulnerabilities": [
                        {
                            "id": "GHSA-jf85-cpcp-j695",
                            "summary": "Prototype Pollution in lodash",
                            "details": "Lodash versions prior to 4.17.21 are vulnerable to prototype pollution.",
                            "aliases": ["CVE-2021-23337"],
                            "severity": [
                                {
                                    "type": "CVSS_V3",
                                    "score": "CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H",
                                }
                            ],
                            "references": [
                                {"type": "ADVISORY", "url": "https://nvd.nist.gov/vuln/detail/CVE-2021-23337"},
                                {"type": "WEB", "url": "https://github.com/lodash/lodash/issues/5261"},
                            ],
                            "published": "2021-02-19T16:23:00Z",
                            "modified": "2021-08-16T00:00:00Z",
                            "affected": [],
                        },
                    ],
                },
                {
                    "package": {
                        "name": "express",
                        "version": "4.17.1",
                        "ecosystem": "npm",
                    },
                    "vulnerabilities": [
                        {
                            "id": "GHSA-rv95-896h-c2vc",
                            "summary": "Express vulnerable to open redirect",
                            "details": "Express.js open redirect vulnerability.",
                            "aliases": ["CVE-2024-29041"],
                            "severity": [],
                            "references": [],
                            "affected": [
                                {
                                    "ranges": [
                                        {
                                            "type": "SEMVER",
                                            "database_specific": {"severity": "medium"},
                                        }
                                    ]
                                }
                            ],
                        },
                    ],
                },
            ],
        }
    ]
}

# Sample output with CVSS numeric scores in database_specific
SAMPLE_OSV_OUTPUT_CVSS_SCORE = {
    "results": [
        {
            "packages": [
                {
                    "package": {"name": "pkg", "version": "1.0", "ecosystem": "npm"},
                    "vulnerabilities": [
                        {
                            "id": "CVE-2024-9999",
                            "summary": "Critical vuln",
                            "details": "",
                            "severity": [],
                            "affected": [
                                {
                                    "ranges": [
                                        {
                                            "type": "SEMVER",
                                            "database_specific": {"cvss_score": 9.8},
                                        }
                                    ]
                                }
                            ],
                        },
                    ],
                }
            ]
        }
    ]
}


class TestOSVPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = OSVPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "osv"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.SECURITY

    def test_default_config(self) -> None:
        """Test that plugin has correct default config values."""
        plugin = OSVPlugin()
        assert plugin.config.get("timeout", 300) == 300
        assert plugin.config.get("scanner_path", "/usr/local/bin/osv-scanner") == "/usr/local/bin/osv-scanner"

    def test_custom_config(self) -> None:
        """Test that plugin accepts custom config."""
        plugin = OSVPlugin(config={"timeout": 600, "scanner_path": "/opt/bin/osv-scanner"})
        assert plugin.config["timeout"] == 600
        assert plugin.config["scanner_path"] == "/opt/bin/osv-scanner"


class TestOSVPluginFileSuffix:
    """Tests for SBOM format detection and file suffix determination."""

    def test_cyclonedx_suffix(self) -> None:
        """Test CycloneDX format is detected correctly."""
        plugin = OSVPlugin()
        sbom = json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5"}).encode()
        assert plugin._determine_file_suffix(sbom) == ".cdx.json"

    def test_spdx_suffix(self) -> None:
        """Test SPDX format is detected correctly."""
        plugin = OSVPlugin()
        sbom = json.dumps({"spdxVersion": "SPDX-2.3"}).encode()
        assert plugin._determine_file_suffix(sbom) == ".spdx.json"

    def test_unknown_format_suffix(self) -> None:
        """Test unknown format falls back to .json."""
        plugin = OSVPlugin()
        sbom = json.dumps({"unknown": "format"}).encode()
        assert plugin._determine_file_suffix(sbom) == ".json"

    def test_invalid_json_suffix(self) -> None:
        """Test invalid JSON falls back to .json."""
        plugin = OSVPlugin()
        assert plugin._determine_file_suffix(b"not json") == ".json"

    def test_format_name_detection(self) -> None:
        """Test format name detection."""
        plugin = OSVPlugin()
        assert plugin._detect_format_name(json.dumps({"bomFormat": "CycloneDX"}).encode()) == "cyclonedx"
        assert plugin._detect_format_name(json.dumps({"spdxVersion": "SPDX-2.3"}).encode()) == "spdx"
        assert plugin._detect_format_name(json.dumps({"foo": "bar"}).encode()) == "unknown"
        assert plugin._detect_format_name(b"bad") == "unknown"


class TestOSVPluginAssess:
    """Tests for the assess() method with mocked subprocess."""

    def _make_sbom_file(self, sbom_data: dict) -> Path:
        """Create a temporary SBOM file and return its path."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(sbom_data, f)
        f.flush()
        return Path(f.name)

    def test_no_vulnerabilities(self) -> None:
        """Test scan with no vulnerabilities found."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        assert isinstance(result, AssessmentResult)
        assert result.plugin_name == "osv"
        assert result.category == "security"
        assert result.summary.total_findings == 0
        assert len(result.findings) == 0

    def test_with_vulnerabilities(self) -> None:
        """Test scan with vulnerabilities found."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(SAMPLE_OSV_OUTPUT), stderr=""
        )

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        assert result.summary.total_findings == 2
        assert len(result.findings) == 2

        # Check first finding (lodash)
        lodash_finding = next(f for f in result.findings if f.id == "GHSA-jf85-cpcp-j695")
        assert lodash_finding.title == "Prototype Pollution in lodash"
        assert lodash_finding.component["name"] == "lodash"
        assert lodash_finding.component["version"] == "4.17.20"
        assert lodash_finding.component["ecosystem"] == "npm"
        assert lodash_finding.aliases == ["CVE-2021-23337"]
        assert lodash_finding.published_at == "2021-02-19T16:23:00Z"
        assert lodash_finding.modified_at == "2021-08-16T00:00:00Z"
        assert any("nvd.nist.gov" in ref for ref in lodash_finding.references)

    def test_severity_mapping_cvss_vector(self) -> None:
        """Test CVSS vector severity mapping."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(SAMPLE_OSV_OUTPUT), stderr=""
        )

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        # lodash vuln has CVSS v3 vector → should be high severity
        lodash_finding = next(f for f in result.findings if f.id == "GHSA-jf85-cpcp-j695")
        assert lodash_finding.severity in ("high", "critical")

    def test_severity_mapping_database_specific(self) -> None:
        """Test severity from database_specific field."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(SAMPLE_OSV_OUTPUT), stderr=""
        )

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        # express vuln uses database_specific severity
        express_finding = next(f for f in result.findings if f.id == "GHSA-rv95-896h-c2vc")
        assert express_finding.severity == "medium"

    def test_severity_mapping_cvss_score(self) -> None:
        """Test CVSS numeric score mapping."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(SAMPLE_OSV_OUTPUT_CVSS_SCORE), stderr=""
        )

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        finding = result.findings[0]
        assert finding.severity == "critical"
        assert finding.cvss_score == 9.8

    def test_summary_counts(self) -> None:
        """Test by_severity summary counts."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(SAMPLE_OSV_OUTPUT), stderr=""
        )

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        assert result.summary.by_severity is not None
        total_from_severity = sum(result.summary.by_severity.values())
        assert total_from_severity == result.summary.total_findings

    def test_scanner_timeout(self) -> None:
        """Test scanner timeout produces error result."""
        plugin = OSVPlugin(config={"timeout": 5})
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        try:
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osv-scanner", timeout=5)):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        assert result.summary.error_count == 1
        assert result.summary.total_findings == 1
        assert result.findings[0].id == "osv:error"
        assert "timed out" in result.findings[0].description

    def test_scanner_not_found(self) -> None:
        """Test missing scanner binary produces error result."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        try:
            with patch("subprocess.run", side_effect=FileNotFoundError("osv-scanner not found")):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        assert result.summary.error_count == 1
        assert "not found" in result.findings[0].description

    def test_temp_file_cleanup(self) -> None:
        """Test that temporary copy is cleaned up after scanning."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        try:
            with patch("subprocess.run", return_value=mock_process):
                plugin.assess("sbom-123", sbom_path)

            # Check no .cdx.json file remains in parent dir
            parent = sbom_path.parent
            cdx_files = list(parent.glob("*.cdx.json"))
            # Filter to only files that match our pattern
            matching = [f for f in cdx_files if sbom_path.stem in f.stem]
            assert len(matching) == 0, f"Temp copy not cleaned up: {matching}"
        finally:
            sbom_path.unlink(missing_ok=True)

    def test_vex_fields_are_none(self) -> None:
        """Test that VEX fields are None in OSV findings."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(SAMPLE_OSV_OUTPUT), stderr=""
        )

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        for finding in result.findings:
            assert finding.analysis_state is None
            assert finding.analysis_justification is None
            assert finding.analysis_response is None
            assert finding.analysis_detail is None

    def test_spdx_format_creates_correct_temp_copy(self) -> None:
        """Test SPDX SBOM creates .spdx.json temp copy."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"spdxVersion": "SPDX-2.3", "packages": []})

        mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch("subprocess.run", return_value=mock_process) as mock_run:
            try:
                plugin.assess("sbom-123", sbom_path)
            finally:
                sbom_path.unlink(missing_ok=True)

            # Verify the command used a .spdx.json file
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            sbom_arg = cmd[cmd.index("--sbom") + 1]
            assert sbom_arg.endswith(".spdx.json")

    def test_metadata_includes_format(self) -> None:
        """Test result metadata includes SBOM format."""
        plugin = OSVPlugin()
        sbom_path = self._make_sbom_file({"bomFormat": "CycloneDX", "specVersion": "1.5"})

        mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        try:
            with patch("subprocess.run", return_value=mock_process):
                result = plugin.assess("sbom-123", sbom_path)
        finally:
            sbom_path.unlink(missing_ok=True)

        assert result.metadata["sbom_format"] == "cyclonedx"
        assert result.metadata["scanner"] == "osv-scanner"


class TestOSVSeverityMapping:
    """Tests for severity mapping logic in isolation."""

    def test_score_to_severity_critical(self) -> None:
        assert OSVPlugin._score_to_severity(9.0) == "critical"
        assert OSVPlugin._score_to_severity(10.0) == "critical"

    def test_score_to_severity_high(self) -> None:
        assert OSVPlugin._score_to_severity(7.0) == "high"
        assert OSVPlugin._score_to_severity(8.9) == "high"

    def test_score_to_severity_medium(self) -> None:
        assert OSVPlugin._score_to_severity(4.0) == "medium"
        assert OSVPlugin._score_to_severity(6.9) == "medium"

    def test_score_to_severity_low(self) -> None:
        assert OSVPlugin._score_to_severity(0.1) == "low"
        assert OSVPlugin._score_to_severity(3.9) == "low"

    def test_map_severity_no_data_defaults_to_medium(self) -> None:
        plugin = OSVPlugin()
        severity, score = plugin._map_severity({"severity": [], "affected": []})
        assert severity == "medium"
        assert score is None

    def test_map_severity_cvss_v3_vector(self) -> None:
        plugin = OSVPlugin()
        vuln = {
            "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"}],
            "affected": [],
        }
        severity, score = plugin._map_severity(vuln)
        assert severity == "critical"
        assert score == 10.0

    def test_map_severity_database_specific_string(self) -> None:
        plugin = OSVPlugin()
        vuln = {
            "severity": [],
            "affected": [{"ranges": [{"type": "SEMVER", "database_specific": {"severity": "HIGH"}}]}],
        }
        severity, score = plugin._map_severity(vuln)
        assert severity == "high"

    def test_map_severity_database_specific_list(self) -> None:
        plugin = OSVPlugin()
        vuln = {
            "severity": [],
            "affected": [{"ranges": [{"type": "SEMVER", "database_specific": {"severity": ["Low", "Medium"]}}]}],
        }
        severity, score = plugin._map_severity(vuln)
        assert severity == "low"

    def test_extract_cvss_score_none(self) -> None:
        plugin = OSVPlugin()
        assert plugin._extract_cvss_score("") is None
        assert plugin._extract_cvss_score(None) is None
        assert plugin._extract_cvss_score("not-cvss") is None


class TestSPDX3Handling:
    """Tests for SPDX 3.0 handling in OSV plugin."""

    def test_spdx3_detected_by_is_spdx3(self) -> None:
        """Test that SPDX 3.0 content is detected by _is_spdx3."""
        spdx3_content = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [],
            }
        ).encode("utf-8")

        assert OSVPlugin._is_spdx3(spdx3_content) is True

    def test_spdx3_context_as_list(self) -> None:
        """Test that SPDX 3.0 @context as list is detected."""
        spdx3_content = json.dumps(
            {
                "@context": [
                    "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                    {"@vocab": "https://spdx.org/rdf/3.0/terms/"},
                ],
                "@graph": [],
            }
        ).encode("utf-8")

        assert OSVPlugin._is_spdx3(spdx3_content) is True

    def test_spdx2_not_detected_as_spdx3(self) -> None:
        """Test that SPDX 2.x is not detected as SPDX 3.0."""
        spdx2_content = json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [],
            }
        ).encode("utf-8")

        assert OSVPlugin._is_spdx3(spdx2_content) is False

    def test_spdx3_returns_unsupported_format_result(self) -> None:
        """Test that SPDX 3.0 SBOMs get an unsupported format warning instead of scanning."""
        plugin = OSVPlugin()
        spdx3_sbom = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [
                    {"type": "software_Package", "name": "test-pkg"},
                ],
            }
        ).encode("utf-8")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(spdx3_sbom)
            f.flush()
            sbom_path = Path(f.name)

        try:
            result = plugin.assess("test-sbom-id", sbom_path)
            assert isinstance(result, AssessmentResult)
            assert result.metadata["unsupported_format"] is True
            assert result.metadata["sbom_format"] == "spdx3"
            assert len(result.findings) == 1
            assert result.findings[0].id == "osv:unsupported-format"
            assert result.findings[0].status == "warning"
            assert "SPDX 3.0" in result.findings[0].title
            assert result.summary.warning_count == 1
        finally:
            sbom_path.unlink(missing_ok=True)

    def test_spdx2_still_detected(self) -> None:
        """Test that SPDX 2.x detection still works."""
        plugin = OSVPlugin()
        spdx2_content = json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [],
            }
        ).encode("utf-8")

        assert plugin._determine_file_suffix(spdx2_content) == ".spdx.json"
        assert plugin._detect_format_name(spdx2_content) == "spdx"

    def test_cyclonedx_still_detected(self) -> None:
        """Test that CycloneDX detection still works."""
        plugin = OSVPlugin()
        cdx_content = json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
            }
        ).encode("utf-8")

        assert plugin._determine_file_suffix(cdx_content) == ".cdx.json"
        assert plugin._detect_format_name(cdx_content) == "cyclonedx"
