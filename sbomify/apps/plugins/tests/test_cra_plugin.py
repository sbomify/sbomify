"""Tests for the EU Cyber Resilience Act (CRA) compliance plugin.

Tests validation of SBOMs against the CRA requirements for software bills
of materials as defined in Regulation (EU) 2024/2847.
"""

import json
import tempfile
from pathlib import Path

import pytest

from sbomify.apps.plugins.builtins.cra import CRACompliancePlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult


def create_base_cyclonedx_sbom() -> dict:
    """Create a base compliant CycloneDX SBOM for testing.

    Returns:
        A dictionary representing a fully compliant CycloneDX SBOM.
    """
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {
                "name": "example-component",
                "version": "1.0.0",
                "publisher": "Example Corp",
                "purl": "pkg:pypi/example-component@1.0.0",
            }
        ],
        "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
        "metadata": {
            "authors": [{"name": "Example Developer"}],
            "tools": [{"name": "sbom-generator", "version": "1.0.0"}],
            "timestamp": "2023-01-01T00:00:00Z",
            "manufacture": {
                "name": "Example Corp",
                "contact": [{"email": "security@example.com"}],
            },
            "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
        },
    }


def create_base_spdx_sbom() -> dict:
    """Create a base compliant SPDX SBOM for testing.

    Returns:
        A dictionary representing a fully compliant SPDX SBOM.
    """
    return {
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
                "validUntilDate": "2028-12-31T00:00:00Z",
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
            "creators": ["Tool: example-tool", "Organization: Example Corp (security@example.com)"],
            "created": "2023-01-01T00:00:00Z",
        },
    }


def assess_sbom(sbom_data: dict) -> AssessmentResult:
    """Write SBOM to temp file and assess it.

    Args:
        sbom_data: The SBOM dictionary to assess.

    Returns:
        AssessmentResult from the CRA plugin.
    """
    plugin = CRACompliancePlugin()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sbom_data, f)
        f.flush()
        return plugin.assess("test-sbom-id", Path(f.name))


@pytest.fixture
def base_cyclonedx_sbom() -> dict:
    """Pytest fixture for base CycloneDX SBOM."""
    return create_base_cyclonedx_sbom()


@pytest.fixture
def base_spdx_sbom() -> dict:
    """Pytest fixture for base SPDX SBOM."""
    return create_base_spdx_sbom()


class TestCRAPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = CRACompliancePlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "cra-compliance-2024"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_standard_info(self) -> None:
        """Test that plugin has correct standard information."""
        plugin = CRACompliancePlugin()

        assert plugin.STANDARD_NAME == "EU Cyber Resilience Act (CRA) - Regulation (EU) 2024/2847"
        assert plugin.STANDARD_VERSION == "2024/2847"
        assert plugin.STANDARD_URL == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202402847"

    def test_finding_ids_match_standard(self) -> None:
        """Test that finding IDs are properly formatted with standard version."""
        plugin = CRACompliancePlugin()

        for key, finding_id in plugin.FINDING_IDS.items():
            assert finding_id.startswith("cra-2024:"), f"Finding ID {finding_id} should start with 'cra-2024:'"

    def test_all_ten_elements_have_finding_ids(self) -> None:
        """Test that all 10 CRA elements have finding IDs."""
        plugin = CRACompliancePlugin()

        expected_elements = {
            "component_name",
            "component_version",
            "supplier",
            "unique_identifiers",
            "sbom_author",
            "timestamp",
            "dependencies",
            "machine_readable",
            "vulnerability_contact",
            "support_period",
        }

        assert set(plugin.FINDING_IDS.keys()) == expected_elements


class TestCycloneDXValidation:
    """Tests for CycloneDX SBOM validation."""

    def test_compliant_cyclonedx_sbom(self) -> None:
        """Test validation of a fully compliant CycloneDX SBOM."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "tools": [{"name": "sbom-generator", "version": "1.0.0"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "manufacture": {
                    "name": "Example Corp",
                    "contact": [{"email": "security@example.com"}],
                },
                "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
            },
        }

        result = assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 10  # All 10 CRA elements
        assert result.summary.total_findings == 10

    def test_cyclonedx_missing_component_name(self) -> None:
        """Test CycloneDX SBOM missing component name."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["name"]

        result = assess_sbom(sbom_data)

        name_finding = next(f for f in result.findings if "component-name" in f.id)
        assert name_finding.status == "fail"

    def test_cyclonedx_missing_component_version(self) -> None:
        """Test CycloneDX SBOM missing component version."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["version"]

        result = assess_sbom(sbom_data)

        version_finding = next(f for f in result.findings if "component-version" in f.id)
        assert version_finding.status == "fail"

    def test_cyclonedx_missing_supplier(self) -> None:
        """Test CycloneDX SBOM missing supplier information."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["publisher"]

        result = assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "fail"

    def test_cyclonedx_with_supplier_object(self) -> None:
        """Test CycloneDX SBOM with supplier.name instead of publisher."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["publisher"]
        sbom_data["components"][0]["supplier"] = {"name": "Example Corp"}

        result = assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "pass"

    def test_cyclonedx_missing_unique_identifiers(self) -> None:
        """Test CycloneDX SBOM missing unique identifiers."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["purl"]

        result = assess_sbom(sbom_data)

        identifier_finding = next(f for f in result.findings if "unique-identifiers" in f.id)
        assert identifier_finding.status == "fail"

    def test_cyclonedx_with_cpe_identifier(self) -> None:
        """Test CycloneDX SBOM with CPE instead of PURL."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["purl"]
        sbom_data["components"][0]["cpe"] = "cpe:2.3:a:example:component:1.0.0:*:*:*:*:*:*:*"

        result = assess_sbom(sbom_data)

        identifier_finding = next(f for f in result.findings if "unique-identifiers" in f.id)
        assert identifier_finding.status == "pass"

    def test_cyclonedx_missing_sbom_author(self) -> None:
        """Test CycloneDX SBOM missing SBOM author."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["authors"]
        del sbom_data["metadata"]["tools"]
        del sbom_data["metadata"]["manufacture"]

        result = assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_cyclonedx_with_tools_as_author(self) -> None:
        """Test CycloneDX SBOM with tools field satisfies author requirement."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["authors"]
        del sbom_data["metadata"]["manufacture"]
        sbom_data["metadata"]["tools"] = [{"name": "sbom-generator"}]

        result = assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "pass"

    def test_cyclonedx_missing_timestamp(self) -> None:
        """Test CycloneDX SBOM missing timestamp."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["timestamp"]

        result = assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if f.id == "cra-2024:timestamp")
        assert timestamp_finding.status == "fail"

    def test_cyclonedx_invalid_timestamp(self) -> None:
        """Test CycloneDX SBOM with invalid timestamp format."""
        sbom_data = create_base_cyclonedx_sbom()
        sbom_data["metadata"]["timestamp"] = "invalid-timestamp"

        result = assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if f.id == "cra-2024:timestamp")
        assert timestamp_finding.status == "fail"

    def test_cyclonedx_missing_dependencies(self) -> None:
        """Test CycloneDX SBOM missing dependencies."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["dependencies"]

        result = assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependencies" in f.id)
        assert dep_finding.status == "fail"

    def test_cyclonedx_machine_readable_always_passes(self) -> None:
        """Test that machine-readable format check always passes for valid CycloneDX."""
        sbom_data = create_base_cyclonedx_sbom()

        result = assess_sbom(sbom_data)

        format_finding = next(f for f in result.findings if "machine-readable" in f.id)
        assert format_finding.status == "pass"

    def test_cyclonedx_missing_vulnerability_contact(self) -> None:
        """Test CycloneDX SBOM missing vulnerability contact."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["manufacture"]

        result = assess_sbom(sbom_data)

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "fail"

    def test_cyclonedx_with_supplier_contact(self) -> None:
        """Test CycloneDX SBOM with supplier contact for vulnerability reporting."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["manufacture"]
        sbom_data["metadata"]["supplier"] = {
            "name": "Example Corp",
            "contact": [{"email": "security@example.com"}],
        }

        result = assess_sbom(sbom_data)

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "pass"

    def test_cyclonedx_with_external_reference_issue_tracker(self) -> None:
        """Test CycloneDX SBOM with external reference issue tracker."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["manufacture"]
        sbom_data["externalReferences"] = [{"type": "issue-tracker", "url": "https://github.com/example/issues"}]

        result = assess_sbom(sbom_data)

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "pass"

    def test_cyclonedx_missing_support_period(self) -> None:
        """Test CycloneDX SBOM missing support period."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["properties"]

        result = assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-period" in f.id)
        assert support_finding.status == "fail"

    def test_cyclonedx_with_cdx_support_property(self) -> None:
        """Test CycloneDX SBOM with cdx:support:endDate property."""
        sbom_data = create_base_cyclonedx_sbom()
        sbom_data["metadata"]["properties"] = [{"name": "cdx:support:endDate", "value": "2028-12-31"}]

        result = assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-period" in f.id)
        assert support_finding.status == "pass"

    def test_cyclonedx_with_lifecycle_end_of_life(self) -> None:
        """Test CycloneDX SBOM with lifecycle end-of-life phase."""
        sbom_data = create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["properties"]
        sbom_data["metadata"]["lifecycles"] = [{"phase": "end-of-life"}]

        result = assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-period" in f.id)
        assert support_finding.status == "pass"


class TestSPDXValidation:
    """Tests for SPDX SBOM validation."""

    def test_compliant_spdx_sbom(self) -> None:
        """Test validation of a fully compliant SPDX SBOM."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp (security@example.com)",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2028-12-31T00:00:00Z",
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
                "creators": ["Tool: example-tool", "Organization: Example Corp (security@example.com)"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 10

    def test_spdx_missing_component_name(self) -> None:
        """Test SPDX SBOM missing component name."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["packages"][0]["name"]

        result = assess_sbom(sbom_data)

        name_finding = next(f for f in result.findings if "component-name" in f.id)
        assert name_finding.status == "fail"

    def test_spdx_missing_component_version(self) -> None:
        """Test SPDX SBOM missing component version."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["packages"][0]["versionInfo"]

        result = assess_sbom(sbom_data)

        version_finding = next(f for f in result.findings if "component-version" in f.id)
        assert version_finding.status == "fail"

    def test_spdx_missing_supplier(self) -> None:
        """Test SPDX SBOM missing supplier information."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["packages"][0]["supplier"]

        result = assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "fail"

    def test_spdx_missing_unique_identifiers(self) -> None:
        """Test SPDX SBOM missing unique identifiers."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["packages"][0]["externalRefs"]

        result = assess_sbom(sbom_data)

        identifier_finding = next(f for f in result.findings if "unique-identifiers" in f.id)
        assert identifier_finding.status == "fail"

    def test_spdx_missing_sbom_author(self) -> None:
        """Test SPDX SBOM missing SBOM author."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["creationInfo"]["creators"]

        result = assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_spdx_missing_timestamp(self) -> None:
        """Test SPDX SBOM missing timestamp."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["creationInfo"]["created"]

        result = assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if f.id == "cra-2024:timestamp")
        assert timestamp_finding.status == "fail"

    def test_spdx_missing_dependencies(self) -> None:
        """Test SPDX SBOM missing dependencies."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["relationships"]

        result = assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependencies" in f.id)
        assert dep_finding.status == "fail"

    def test_spdx_with_contains_relationship(self) -> None:
        """Test SPDX SBOM with CONTAINS relationship."""
        sbom_data = create_base_spdx_sbom()
        sbom_data["relationships"][0]["relationshipType"] = "CONTAINS"

        result = assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependencies" in f.id)
        assert dep_finding.status == "pass"

    def test_spdx_machine_readable_always_passes(self) -> None:
        """Test that machine-readable format check always passes for valid SPDX."""
        sbom_data = create_base_spdx_sbom()

        result = assess_sbom(sbom_data)

        format_finding = next(f for f in result.findings if "machine-readable" in f.id)
        assert format_finding.status == "pass"

    def test_spdx_missing_vulnerability_contact(self) -> None:
        """Test SPDX SBOM missing vulnerability contact."""
        sbom_data = create_base_spdx_sbom()
        # Remove email from creators
        sbom_data["creationInfo"]["creators"] = ["Tool: example-tool"]

        result = assess_sbom(sbom_data)

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "fail"

    def test_spdx_with_creator_email(self) -> None:
        """Test SPDX SBOM with email in creators for vulnerability contact."""
        sbom_data = create_base_spdx_sbom()
        sbom_data["creationInfo"]["creators"] = ["Organization: Example Corp (security@example.com)"]

        result = assess_sbom(sbom_data)

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "pass"

    def test_spdx_with_vulnerability_contact_annotation(self) -> None:
        """Test SPDX SBOM with vulnerability contact in annotation."""
        sbom_data = create_base_spdx_sbom()
        sbom_data["creationInfo"]["creators"] = ["Tool: example-tool"]
        sbom_data["annotations"] = [
            {
                "annotationType": "OTHER",
                "comment": "cra:vulnerabilityContact=https://example.com/security",
                "annotator": "Tool: example-tool",
                "annotationDate": "2023-01-01T00:00:00Z",
            }
        ]

        result = assess_sbom(sbom_data)

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "pass"

    def test_spdx_missing_support_period(self) -> None:
        """Test SPDX SBOM missing support period."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["packages"][0]["validUntilDate"]

        result = assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-period" in f.id)
        assert support_finding.status == "fail"

    def test_spdx_with_valid_until_date(self) -> None:
        """Test SPDX SBOM with validUntilDate for support period."""
        sbom_data = create_base_spdx_sbom()
        sbom_data["packages"][0]["validUntilDate"] = "2028-12-31T00:00:00Z"

        result = assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-period" in f.id)
        assert support_finding.status == "pass"

    def test_spdx_with_support_period_annotation(self) -> None:
        """Test SPDX SBOM with support period in annotation."""
        sbom_data = create_base_spdx_sbom()
        del sbom_data["packages"][0]["validUntilDate"]
        sbom_data["annotations"] = [
            {
                "annotationType": "OTHER",
                "comment": "cra:supportPeriodEnd=2028-12-31",
                "annotator": "Tool: example-tool",
                "annotationDate": "2023-01-01T00:00:00Z",
            }
        ]

        result = assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-period" in f.id)
        assert support_finding.status == "pass"


class TestErrorHandling:
    """Tests for error handling in the plugin."""

    def test_invalid_json(self) -> None:
        """Test handling of invalid JSON file."""
        plugin = CRACompliancePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert result.metadata.get("error") is True

    def test_unknown_format(self) -> None:
        """Test handling of unknown SBOM format."""
        plugin = CRACompliancePlugin()
        sbom_data = {"some": "data", "without": "format indicators"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert "format" in result.findings[0].description.lower()

    def test_empty_components(self) -> None:
        """Test handling of SBOM with empty components list."""
        plugin = CRACompliancePlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "dependencies": [],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "tools": [{"name": "sbom-generator"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "manufacture": {"contact": [{"email": "test@example.com"}]},
                "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # With empty components, per-component checks pass (nothing to fail)
        # but dependencies should fail
        dep_finding = next(f for f in result.findings if "dependencies" in f.id)
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

        plugin = CRACompliancePlugin()
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
                }
            ],
            "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "tools": [{"name": "tool"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "manufacture": {"contact": [{"email": "test@example.com"}]},
                "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
            },
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            assert finding.metadata is not None
            assert finding.metadata.get("standard") == "CRA"
            assert finding.metadata.get("standard_version") == "2024/2847"

    def test_result_includes_standard_info(self) -> None:
        """Test that assessment result includes standard reference information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["standard_name"] == plugin.STANDARD_NAME
        assert result.metadata["standard_version"] == plugin.STANDARD_VERSION
        assert result.metadata["standard_url"] == plugin.STANDARD_URL


class TestMultipleComponentFailures:
    """Tests for handling multiple component failures."""

    def test_multiple_components_missing_fields(self) -> None:
        """Test SBOM with multiple components missing various fields."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {"name": "comp1"},  # Missing version, supplier, identifier
                {"name": "comp2", "version": "1.0"},  # Missing supplier, identifier
                {"name": "comp3", "version": "1.0", "publisher": "Pub"},  # Missing identifier
            ],
            "dependencies": [{"ref": "comp1", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "tools": [{"name": "tool"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "manufacture": {"contact": [{"email": "test@example.com"}]},
                "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
            },
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # Check that failures are reported for components
        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "fail"
        assert "comp1" in supplier_finding.description
        assert "comp2" in supplier_finding.description

        version_finding = next(f for f in result.findings if "component-version" in f.id)
        assert version_finding.status == "fail"
        assert "comp1" in version_finding.description

    def test_failure_message_lists_all_components(self) -> None:
        """Test that failure messages list all failing components."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [{"name": f"comp{i}"} for i in range(10)],  # 10 components, all missing fields
            "dependencies": [{"ref": "comp0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "tools": [{"name": "tool"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "manufacture": {"contact": [{"email": "test@example.com"}]},
                "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
            },
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # Check that failure message lists all failing components (no truncation)
        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        # All 10 components should be listed
        for i in range(10):
            assert f"comp{i}" in supplier_finding.description


class TestFormatDetection:
    """Tests for SBOM format detection."""

    def test_detect_cyclonedx_with_bomformat(self) -> None:
        """Test detection of CycloneDX format via bomFormat field."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["sbom_format"] == "cyclonedx"

    def test_detect_cyclonedx_without_bomformat(self) -> None:
        """Test detection of CycloneDX format without explicit bomFormat."""
        sbom_data = {
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["sbom_format"] == "cyclonedx"

    def test_detect_spdx_format(self) -> None:
        """Test detection of SPDX format."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [],
            "creationInfo": {"created": "2023-01-01T00:00:00Z"},
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["sbom_format"] == "spdx"


class TestCRASpecificRequirements:
    """Tests for CRA-specific requirements that differ from NTIA/CISA."""

    def test_vulnerability_contact_property_in_metadata(self) -> None:
        """Test CycloneDX with vulnerability contact in metadata properties."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Example",
                    "purl": "pkg:npm/example@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [
                    {"name": "cra:vulnerabilityContact", "value": "https://example.com/security"},
                    {"name": "cra:supportPeriodEnd", "value": "2028-12-31"},
                ],
            },
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "pass"

    def test_support_period_various_property_names(self) -> None:
        """Test support period detection with various property naming conventions."""
        property_names = [
            "cra:supportPeriodEnd",
            "cdx:support:endDate",
            "cdx:supportperiod:enddate",
        ]

        for prop_name in property_names:
            sbom_data = {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "components": [
                    {
                        "name": "example",
                        "version": "1.0.0",
                        "publisher": "Example",
                        "purl": "pkg:npm/example@1.0.0",
                    }
                ],
                "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
                "metadata": {
                    "authors": [{"name": "Author"}],
                    "timestamp": "2023-01-01T00:00:00Z",
                    "manufacture": {"contact": [{"email": "test@example.com"}]},
                    "properties": [{"name": prop_name, "value": "2028-12-31"}],
                },
            }

            plugin = CRACompliancePlugin()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(sbom_data, f)
                f.flush()
                result = plugin.assess("test-sbom-id", Path(f.name))

            support_finding = next(f for f in result.findings if "support-period" in f.id)
            assert support_finding.status == "pass", f"Property name '{prop_name}' should be valid"

    def test_security_contact_external_reference(self) -> None:
        """Test CycloneDX with security-contact external reference."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Example",
                    "purl": "pkg:npm/example@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
            "externalReferences": [{"type": "security-contact", "url": "mailto:security@example.com"}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cra:supportPeriodEnd", "value": "2028-12-31"}],
            },
        }

        plugin = CRACompliancePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        contact_finding = next(f for f in result.findings if "vulnerability-contact" in f.id)
        assert contact_finding.status == "pass"
