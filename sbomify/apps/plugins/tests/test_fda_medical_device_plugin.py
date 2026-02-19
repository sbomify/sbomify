"""Tests for the FDA Medical Device Cybersecurity compliance plugin.

Tests validation of SBOMs against FDA guidance 'Cybersecurity in Medical Devices:
Quality System Considerations and Content of Premarket Submissions' (June 2025).

This plugin validates:
- 7 NTIA minimum elements (baseline)
- 2 FDA-specific CLE elements (support status, end-of-support date)
"""

import json
import tempfile
from pathlib import Path

import pytest

from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import (
    CLE_SUPPORT_STATUS_VALUES,
    FDAMedicalDevicePlugin,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult


class TestFDAPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = FDAMedicalDevicePlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "fda-medical-device-2025"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_standard_info(self) -> None:
        """Test that plugin has correct standard information."""
        plugin = FDAMedicalDevicePlugin()

        assert plugin.STANDARD_NAME == "FDA Cybersecurity in Medical Devices"
        assert plugin.STANDARD_VERSION == "2025-06"
        assert plugin.STANDARD_URL == "https://www.fda.gov/media/119933/download"

    def test_finding_ids_use_fda_prefix(self) -> None:
        """Test that NTIA finding IDs are prefixed with fda-2025:ntia."""
        plugin = FDAMedicalDevicePlugin()

        for key, finding_id in plugin.NTIA_FINDING_IDS.items():
            assert finding_id.startswith("fda-2025:ntia:"), (
                f"NTIA finding ID {finding_id} should start with 'fda-2025:ntia:'"
            )

    def test_fda_finding_ids_use_cle_prefix(self) -> None:
        """Test that FDA-specific finding IDs are prefixed with fda-2025:cle."""
        plugin = FDAMedicalDevicePlugin()

        for key, finding_id in plugin.FDA_FINDING_IDS.items():
            assert finding_id.startswith("fda-2025:cle:"), (
                f"FDA finding ID {finding_id} should start with 'fda-2025:cle:'"
            )

    def test_cle_support_status_values(self) -> None:
        """Test that valid CLE support status values are defined."""
        expected_values = {"active", "deprecated", "eol", "abandoned", "unknown"}
        assert CLE_SUPPORT_STATUS_VALUES == expected_values


class TestCycloneDXValidation:
    """Tests for CycloneDX SBOM validation."""

    def test_compliant_cyclonedx_sbom_with_cle(self) -> None:
        """Test validation of a fully compliant CycloneDX SBOM with CLE data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "active"},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 9  # 7 NTIA + 2 CLE elements
        assert result.summary.total_findings == 9

    def test_cyclonedx_missing_cle_support_status(self) -> None:
        """Test CycloneDX SBOM missing CLE support status."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        # Missing cdx:cle:supportStatus
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"

    def test_cyclonedx_missing_cle_end_of_support(self) -> None:
        """Test CycloneDX SBOM missing CLE end-of-support date."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "active"},
                        # Missing cdx:cle:endOfSupport
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert eos_finding.status == "fail"

    def test_cyclonedx_missing_all_cle_data(self) -> None:
        """Test CycloneDX SBOM missing all CLE data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    # No properties - missing CLE data
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 2  # Both CLE elements fail
        assert result.summary.pass_count == 7  # All NTIA elements pass

    def test_cyclonedx_invalid_support_status_value(self) -> None:
        """Test CycloneDX SBOM with invalid CLE support status value."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "invalid-status"},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        # Invalid support status should be treated as missing
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"

    @pytest.mark.parametrize(
        "status_value",
        ["active", "deprecated", "eol", "abandoned", "unknown", "ACTIVE", "Active"],
    )
    def test_cyclonedx_valid_support_status_values(self, status_value: str) -> None:
        """Test CycloneDX SBOM with various valid CLE support status values."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": status_value},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "pass"

    def test_cyclonedx_multiple_components_mixed_cle(self) -> None:
        """Test CycloneDX SBOM with multiple components, some missing CLE data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "component-with-cle",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/component-with-cle@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "active"},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                },
                {
                    "name": "component-without-cle",
                    "version": "2.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/component-without-cle@2.0.0",
                    # Missing CLE properties
                },
            ],
            "dependencies": [
                {"ref": "pkg:pypi/component-with-cle@1.0.0", "dependsOn": []},
                {"ref": "pkg:pypi/component-without-cle@2.0.0", "dependsOn": []},
            ],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        # Both CLE elements should fail because one component is missing CLE data
        assert result.summary.fail_count == 2
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert support_finding.status == "fail"
        assert eos_finding.status == "fail"
        assert "component-without-cle" in support_finding.description
        assert "component-without-cle" in eos_finding.description

    def test_cyclonedx_ntia_elements_still_validated(self) -> None:
        """Test that NTIA elements are still validated alongside CLE elements."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version, publisher, purl
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "active"},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            # Missing dependencies
            "metadata": {
                # Missing authors/tools and timestamp
            },
        }

        result = self._assess_sbom(sbom_data)

        # NTIA elements should fail: version, supplier, unique_ids, dependencies, author, timestamp
        # CLE elements should pass
        assert result.summary.fail_count >= 5  # At least 5 NTIA failures
        assert result.summary.pass_count >= 2  # CLE elements pass

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestSPDXValidation:
    """Tests for SPDX SBOM validation."""

    def test_compliant_spdx_sbom_with_cle(self) -> None:
        """Test validation of a fully compliant SPDX SBOM with CLE data."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    "annotations": [
                        {
                            "annotationType": "OTHER",
                            "comment": "cle:supportStatus=active",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2023-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 9  # 7 NTIA + 2 CLE elements

    def test_spdx_missing_valid_until_date(self) -> None:
        """Test SPDX SBOM missing validUntilDate for end-of-support."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    # Missing validUntilDate
                    "annotations": [
                        {
                            "annotationType": "OTHER",
                            "comment": "cle:supportStatus=active",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2023-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert eos_finding.status == "fail"

    def test_spdx_missing_support_status_annotation(self) -> None:
        """Test SPDX SBOM missing CLE support status annotation."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    # Missing annotations with support status
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"

    def test_spdx_support_status_in_document_annotations(self) -> None:
        """Test SPDX SBOM with support status in document-level annotations."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                }
            ],
            "annotations": [
                {
                    "spdxElementId": "SPDXRef-Package",
                    "annotationType": "OTHER",
                    "comment": "cle:supportStatus=deprecated",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "pass"

    def test_spdx_wrong_annotation_type_ignored(self) -> None:
        """Test SPDX SBOM with wrong annotation type is not counted as support status."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    "annotations": [
                        {
                            "annotationType": "REVIEW",  # Wrong type - should be OTHER
                            "comment": "cle:supportStatus=active",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2023-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"  # Wrong annotation type is not valid

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestErrorHandling:
    """Tests for error handling in the plugin."""

    def test_invalid_json(self) -> None:
        """Test handling of invalid JSON file."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert result.metadata.get("error") is True

    def test_unknown_format(self) -> None:
        """Test handling of unknown SBOM format."""
        plugin = FDAMedicalDevicePlugin()
        sbom_data = {"some": "data", "without": "format indicators"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert "format" in result.findings[0].description.lower()

    def test_empty_components(self) -> None:
        """Test handling of SBOM with empty components list."""
        plugin = FDAMedicalDevicePlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "dependencies": [],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # With empty components, per-component checks pass (nothing to fail)
        # but dependencies should fail
        dep_finding = next(f for f in result.findings if "dependency" in f.id)
        assert dep_finding.status == "fail"


class TestFindingDetails:
    """Tests for finding details and remediation suggestions."""

    def test_findings_have_remediation(self) -> None:
        """Test that failed findings include remediation suggestions."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [{"name": "example"}],  # Missing most required fields
            "metadata": {},
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            if finding.status == "fail":
                assert finding.remediation is not None, f"Finding {finding.id} should have remediation"

    def test_findings_have_standard_metadata(self) -> None:
        """Test that findings include standard version metadata."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Example",
                    "purl": "pkg:npm/example@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "active"},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            assert finding.metadata is not None
            assert finding.metadata.get("standard") == "FDA"
            assert finding.metadata.get("standard_version") == "2025-06"
            # Check element source is correctly set
            if "cle" in finding.id:
                assert finding.metadata.get("element_source") == "FDA-CLE"
            else:
                assert finding.metadata.get("element_source") == "NTIA"

    def test_result_includes_standard_info(self) -> None:
        """Test that assessment result includes standard reference information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["standard_name"] == plugin.STANDARD_NAME
        assert result.metadata["standard_version"] == plugin.STANDARD_VERSION
        assert result.metadata["standard_url"] == plugin.STANDARD_URL

    def test_cle_remediation_mentions_github_action(self) -> None:
        """Test that CLE element remediation mentions the sbomify GitHub Action."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    # Missing CLE properties
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)

        assert "sbomify GitHub Action" in support_finding.remediation
        assert "sbomify GitHub Action" in eos_finding.remediation

    def test_failure_list_includes_all_components(self) -> None:
        """Test that failure details include all failing components."""
        # Create SBOM with 10 components missing CLE data
        components = [
            {
                "name": f"component-{i}",
                "version": "1.0.0",
                "publisher": "Example Corp",
                "purl": f"pkg:pypi/component-{i}@1.0.0",
            }
            for i in range(10)
        ]

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": components,
            "dependencies": [{"ref": c["purl"], "dependsOn": []} for c in components],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        # All 10 components should be listed (no truncation)
        for i in range(10):
            assert f"component-{i}" in support_finding.description


def _create_base_spdx3_sbom() -> dict:
    """Create a base compliant SPDX 3.0 SBOM for FDA testing."""
    return {
        "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
        "@graph": [
            {
                "type": "CreationInfo",
                "@id": "_:creationInfo",
                "specVersion": "3.0.1",
                "created": "2024-01-15T12:00:00Z",
                "createdBy": ["SPDXRef-Creator"],
            },
            {
                "type": "Organization",
                "spdxId": "SPDXRef-Creator",
                "name": "SBOM Creator Corp",
                "externalIdentifiers": [{"externalIdentifierType": "email", "identifier": "creator@example.com"}],
            },
            {
                "type": "Organization",
                "spdxId": "SPDXRef-Supplier",
                "name": "Supplier Corp",
                "externalIdentifiers": [{"externalIdentifierType": "email", "identifier": "supplier@example.com"}],
            },
            {
                "type": "software_Package",
                "spdxId": "SPDXRef-Package-1",
                "name": "example-package",
                "software_packageVersion": "1.0.0",
                "originatedBy": ["SPDXRef-Supplier"],
                "software_validUntilDate": "2025-12-31T00:00:00Z",
                "externalIdentifiers": [
                    {"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/example@1.0.0"}
                ],
            },
            {
                "type": "Relationship",
                "spdxId": "SPDXRef-Rel-1",
                "from": "SPDXRef-Package-1",
                "relationshipType": "dependsOn",
                "to": [],
            },
            {
                "type": "Annotation",
                "spdxId": "SPDXRef-Annotation-1",
                "subject": "SPDXRef-Package-1",
                "statement": "cle:supportStatus=active",
            },
        ],
    }


class TestSPDX3Validation:
    """Tests for SPDX 3.0 SBOM validation against FDA requirements."""

    def test_compliant_spdx3_sbom(self) -> None:
        """Test validation of a compliant SPDX 3.0 SBOM."""
        sbom_data = _create_base_spdx3_sbom()
        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 9  # 7 NTIA + 2 CLE
        assert result.summary.total_findings == 9

    def test_spdx3_format_detection(self) -> None:
        """Test that SPDX 3.0 format is correctly detected."""
        sbom_data = _create_base_spdx3_sbom()
        result = self._assess_sbom(sbom_data)

        assert result.metadata["sbom_format"] == "spdx3"

    def test_spdx3_missing_supplier(self) -> None:
        """Test SPDX 3.0 SBOM missing supplier (originatedBy)."""
        sbom_data = _create_base_spdx3_sbom()
        del sbom_data["@graph"][3]["originatedBy"]

        result = self._assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier-name" in f.id)
        assert supplier_finding.status == "fail"

    def test_spdx3_missing_version(self) -> None:
        """Test SPDX 3.0 SBOM missing version."""
        sbom_data = _create_base_spdx3_sbom()
        del sbom_data["@graph"][3]["software_packageVersion"]

        result = self._assess_sbom(sbom_data)

        version_finding = next(f for f in result.findings if "version" in f.id)
        assert version_finding.status == "fail"

    def test_spdx3_missing_support_status(self) -> None:
        """Test SPDX 3.0 SBOM missing CLE support status annotation."""
        sbom_data = _create_base_spdx3_sbom()
        # Remove annotation (last element in graph)
        sbom_data["@graph"] = [e for e in sbom_data["@graph"] if e.get("type") != "Annotation"]

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"

    def test_spdx3_missing_end_of_support(self) -> None:
        """Test SPDX 3.0 SBOM missing end-of-support date (software_validUntilDate)."""
        sbom_data = _create_base_spdx3_sbom()
        del sbom_data["@graph"][3]["software_validUntilDate"]

        result = self._assess_sbom(sbom_data)

        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert eos_finding.status == "fail"

    def test_spdx3_valid_support_status_values(self) -> None:
        """Test all valid CLE support status values."""
        for status in ["active", "deprecated", "eol", "abandoned", "unknown"]:
            sbom_data = _create_base_spdx3_sbom()
            # Update the annotation statement
            for elem in sbom_data["@graph"]:
                if elem.get("type") == "Annotation":
                    elem["statement"] = f"cle:supportStatus={status}"

            result = self._assess_sbom(sbom_data)

            support_finding = next(f for f in result.findings if "support-status" in f.id)
            assert support_finding.status == "pass", f"Status '{status}' should be valid"

    def test_spdx3_missing_sbom_author(self) -> None:
        """Test SPDX 3.0 SBOM missing SBOM author."""
        sbom_data = _create_base_spdx3_sbom()
        sbom_data["@graph"][0]["createdBy"] = []

        result = self._assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_spdx3_missing_dependencies(self) -> None:
        """Test SPDX 3.0 SBOM with no dependency relationships."""
        sbom_data = _create_base_spdx3_sbom()
        sbom_data["@graph"] = [
            e for e in sbom_data["@graph"] if e.get("relationshipType") not in ("dependsOn", "contains")
        ]

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency-relationship" in f.id)
        assert dep_finding.status == "fail"

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))
