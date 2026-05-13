"""Tests for the BSI TR-03183-2 SBOM compliance plugin.

Tests validation of SBOMs against the BSI Technical Guideline TR-03183-2 v2.1.0
requirements for software bills of materials (EU Cyber Resilience Act compliance).
"""

import json
import tempfile
from pathlib import Path

from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult


def create_base_cyclonedx_sbom() -> dict:
    """Create a base BSI-compliant CycloneDX 1.6 SBOM for testing.

    Returns:
        A dictionary representing a BSI TR-03183-2 compliant CycloneDX SBOM.
    """
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {
                "name": "example-component",
                "version": "1.0.0",
                "manufacturer": {
                    "name": "Example Corp",
                    "url": "https://example.com",
                    "contact": [{"email": "maintainer@example.com"}],
                },
                "purl": "pkg:pypi/example-component@1.0.0",
                "licenses": [{"expression": "MIT", "acknowledgement": "concluded"}],
                "hashes": [{"alg": "SHA-512", "content": "abc123" * 20}],
                "properties": [
                    {"name": "bsi:component:filename", "value": "example-component.whl"},
                    {"name": "bsi:component:executable", "value": "non-executable"},
                    {"name": "bsi:component:archive", "value": "archive"},
                    {"name": "bsi:component:structured", "value": "structured"},
                ],
            }
        ],
        "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
        "compositions": [{"aggregate": "complete", "assemblies": ["pkg:pypi/example-component@1.0.0"]}],
        "metadata": {
            "timestamp": "2024-01-15T12:00:00Z",
            "manufacturer": {
                "name": "SBOM Creator Corp",
                "url": "https://sbom-creator.example.com",
                "contact": [{"email": "sbom@example.com"}],
            },
        },
    }


def create_base_spdx3_sbom() -> dict:
    """Create a base BSI-compliant SPDX 3.0.1 SBOM for testing.

    Uses spec-compliant @context/@graph format with CreationInfo as blank node.

    Returns:
        A dictionary representing a BSI TR-03183-2 compliant SPDX 3.0.1 SBOM.
    """
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
                "creationInfo": "_:creationInfo",
                "name": "SBOM Creator Corp",
                "externalIdentifiers": [{"externalIdentifierType": "email", "identifier": "sbom@example.com"}],
            },
            {
                "type": "Organization",
                "spdxId": "SPDXRef-Maintainer",
                "creationInfo": "_:creationInfo",
                "name": "Example Corp",
                "externalIdentifiers": [{"externalIdentifierType": "email", "identifier": "maintainer@example.com"}],
            },
            {
                "type": "software_Package",
                "spdxId": "SPDXRef-Package-1",
                "creationInfo": "_:creationInfo",
                "name": "example-package",
                "software_packageVersion": "1.0.0",
                "originatedBy": ["SPDXRef-Maintainer"],
                "externalIdentifiers": [
                    {"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/example@1.0.0"}
                ],
            },
            {
                "type": "software_File",
                "spdxId": "SPDXRef-File-1",
                "creationInfo": "_:creationInfo",
                "name": "example-package.whl",
                "verifiedUsing": [{"type": "Hash", "algorithm": "sha512", "hashValue": "abc123" * 20}],
                "software_additionalPurpose": ["archive", "container"],
            },
            {
                "type": "Relationship",
                "spdxId": "SPDXRef-Rel-1",
                "creationInfo": "_:creationInfo",
                "from": "SPDXRef-Package-1",
                "relationshipType": "hasDistributionArtifact",
                "to": ["SPDXRef-File-1"],
            },
            {
                "type": "Relationship",
                "spdxId": "SPDXRef-Rel-2",
                "creationInfo": "_:creationInfo",
                "from": "SPDXRef-Package-1",
                "relationshipType": "dependsOn",
                "to": [],
                "completeness": "complete",
            },
            {
                "type": "Relationship",
                "spdxId": "SPDXRef-Rel-3",
                "creationInfo": "_:creationInfo",
                "from": "SPDXRef-Package-1",
                "relationshipType": "hasConcludedLicense",
                "to": ["SPDXRef-License-1"],
            },
            {
                "type": "simpleLicensing_LicenseExpression",
                "spdxId": "SPDXRef-License-1",
                "creationInfo": "_:creationInfo",
                "simpleLicensing_licenseExpression": "MIT",
            },
            {
                "type": "SpdxDocument",
                "spdxId": "SPDXRef-Document",
                "creationInfo": "_:creationInfo",
                "name": "BSI Test SBOM",
                "dataLicense": "CC0-1.0",
                "profileConformance": ["core", "software", "simpleLicensing"],
                "element": [
                    "SPDXRef-Creator",
                    "SPDXRef-Maintainer",
                    "SPDXRef-Package-1",
                    "SPDXRef-File-1",
                    "SPDXRef-Rel-1",
                    "SPDXRef-Rel-2",
                    "SPDXRef-Rel-3",
                    "SPDXRef-License-1",
                ],
                "rootElement": ["SPDXRef-Package-1"],
            },
        ],
    }


def create_base_spdx2_sbom() -> dict:
    """Create a base SPDX 2.3 SBOM for testing (will fail format check).

    Returns:
        A dictionary representing an SPDX 2.3 SBOM.
    """
    return {
        "spdxVersion": "SPDX-2.3",
        "packages": [
            {
                "SPDXID": "SPDXRef-Package",
                "name": "example-package",
                "supplier": "Organization: Example Corp (maintainer@example.com)",
                "versionInfo": "1.0.0",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": "pkg:pypi/example-package@1.0.0",
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
            "creators": ["Tool: example-tool", "Organization: Example Corp (security@example.com)"],
            "created": "2024-01-15T00:00:00Z",
        },
    }


def assess_sbom(sbom_data: dict, dependency_status: dict | None = None) -> AssessmentResult:
    """Write SBOM to temp file and assess it.

    Args:
        sbom_data: The SBOM dictionary to assess.
        dependency_status: Optional dependency status to pass to the plugin.

    Returns:
        AssessmentResult from the BSI plugin.
    """
    plugin = BSICompliancePlugin()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sbom_data, f)
        f.flush()
        sbom_path = Path(f.name)

    try:
        result = plugin.assess("test-sbom-id", sbom_path, dependency_status)
    finally:
        sbom_path.unlink()

    return result


def get_finding(result: AssessmentResult, finding_id: str) -> dict | None:
    """Get a finding by its ID from the assessment result.

    Args:
        result: The assessment result.
        finding_id: The finding ID to look for.

    Returns:
        The finding dict if found, None otherwise.
    """
    for finding in result.findings:
        if finding.id == finding_id:
            return finding
    return None


class TestBSIPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self):
        """Test that plugin metadata is correctly configured."""
        plugin = BSICompliancePlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "bsi-tr03183-v2.1-compliance"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_constants(self):
        """Test that plugin constants are correctly defined."""
        assert BSICompliancePlugin.VERSION == "1.0.0"
        assert BSICompliancePlugin.STANDARD_NAME == "BSI TR-03183-2: Cyber Resilience Requirements - Part 2: SBOM"
        assert BSICompliancePlugin.STANDARD_VERSION == "2.1.0"
        assert "bsi.bund.de" in BSICompliancePlugin.STANDARD_URL


class TestFormatVersionValidation:
    """Tests for SBOM format version validation."""

    def test_cyclonedx_16_passes(self):
        """CycloneDX 1.6 should pass format check."""
        sbom = create_base_cyclonedx_sbom()
        sbom["specVersion"] = "1.6"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_17_passes(self):
        """CycloneDX 1.7 should pass format check."""
        sbom = create_base_cyclonedx_sbom()
        sbom["specVersion"] = "1.7"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_15_fails(self):
        """CycloneDX 1.5 should fail format check."""
        sbom = create_base_cyclonedx_sbom()
        sbom["specVersion"] = "1.5"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "fail"
        assert "1.6" in finding.description

    def test_cyclonedx_14_fails(self):
        """CycloneDX 1.4 should fail format check."""
        sbom = create_base_cyclonedx_sbom()
        sbom["specVersion"] = "1.4"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "fail"

    def test_spdx_301_passes(self):
        """SPDX 3.0.1 should pass format check."""
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx_23_fails(self):
        """SPDX 2.3 should fail format check."""
        sbom = create_base_spdx2_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "fail"
        assert "3.0.1" in finding.description


class TestSBOMLevelValidation:
    """Tests for SBOM-level required fields."""

    def test_sbom_creator_with_email_passes(self):
        """SBOM creator with valid email should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert finding is not None
        assert finding.status == "pass"

    def test_sbom_creator_with_url_passes(self):
        """SBOM creator with valid URL should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["metadata"]["manufacturer"] = {
            "name": "Example Corp",
            "url": "https://example.com",
        }
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert finding is not None
        assert finding.status == "pass"

    def test_sbom_creator_missing_fails(self):
        """Missing SBOM creator should fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["metadata"]["manufacturer"] = {"name": "Example Corp"}
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert finding is not None
        assert finding.status == "fail"

    def test_sbom_creator_from_authors_email_passes(self):
        """SBOM creator found via metadata.authors[].email should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["metadata"]["manufacturer"] = {"name": "No Contact"}
        sbom["metadata"]["authors"] = [{"name": "Dev", "email": "dev@example.com"}]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert finding is not None
        assert finding.status == "pass"

    def test_sbom_creator_from_supplier_url_passes(self):
        """SBOM creator found via metadata.supplier.url should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["metadata"]["manufacturer"] = {"name": "No Contact"}
        sbom["metadata"]["supplier"] = {
            "name": "Supplier Corp",
            "url": ["https://supplier.example.com"],
        }
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert finding is not None
        assert finding.status == "pass"

    def test_sbom_creator_no_email_no_url_anywhere_fails(self):
        """No email or URL in manufacturer, supplier, or authors should fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["metadata"]["manufacturer"] = {"name": "No Contact"}
        sbom["metadata"]["supplier"] = {"name": "No URL"}
        sbom["metadata"]["authors"] = [{"name": "No Email"}]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert finding is not None
        assert finding.status == "fail"

    def test_timestamp_valid_passes(self):
        """Valid ISO-8601 timestamp should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:timestamp")
        assert finding is not None
        assert finding.status == "pass"

    def test_timestamp_missing_fails(self):
        """Missing timestamp should fail."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["metadata"]["timestamp"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:timestamp")
        assert finding is not None
        assert finding.status == "fail"


class TestComponentLevelValidation:
    """Tests for component-level required fields."""

    def test_component_name_present_passes(self):
        """Component with name should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-name")
        assert finding is not None
        assert finding.status == "pass"

    def test_component_name_missing_fails(self):
        """Component without name should fail."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["name"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-name")
        assert finding is not None
        assert finding.status == "fail"

    def test_component_version_present_passes(self):
        """Component with version should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-version")
        assert finding is not None
        assert finding.status == "pass"

    def test_component_version_missing_fails(self):
        """Component without version should fail."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["version"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-version")
        assert finding is not None
        assert finding.status == "fail"

    def test_component_creator_with_email_passes(self):
        """Component creator with valid email should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-creator")
        assert finding is not None
        assert finding.status == "pass"

    def test_component_creator_with_url_passes(self):
        """Component creator with valid URL should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["manufacturer"] = {
            "name": "Example Corp",
            "url": "https://example.com",
        }
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-creator")
        assert finding is not None
        assert finding.status == "pass"

    def test_component_creator_missing_fails(self):
        """Component without creator contact should fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["manufacturer"] = {"name": "Example Corp"}
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-creator")
        assert finding is not None
        assert finding.status == "fail"


class TestBSIPropertyValidation:
    """Tests for BSI-specific property validation."""

    def test_filename_property_present_passes(self):
        """Component with filename property should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:filename")
        assert finding is not None
        assert finding.status == "pass"

    def test_filename_property_missing_fails(self):
        """Component without filename property should fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["properties"] = [
            p for p in sbom["components"][0]["properties"] if p["name"] != "bsi:component:filename"
        ]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:filename")
        assert finding is not None
        assert finding.status == "fail"

    def test_executable_property_executable_passes(self):
        """Component with executable property 'executable' should pass."""
        sbom = create_base_cyclonedx_sbom()
        for prop in sbom["components"][0]["properties"]:
            if prop["name"] == "bsi:component:executable":
                prop["value"] = "executable"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:executable-property")
        assert finding is not None
        assert finding.status == "pass"

    def test_executable_property_non_executable_passes(self):
        """Component with executable property 'non-executable' should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:executable-property")
        assert finding is not None
        assert finding.status == "pass"

    def test_executable_property_invalid_fails(self):
        """Component with invalid executable property should fail."""
        sbom = create_base_cyclonedx_sbom()
        for prop in sbom["components"][0]["properties"]:
            if prop["name"] == "bsi:component:executable":
                prop["value"] = "invalid"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:executable-property")
        assert finding is not None
        assert finding.status == "fail"

    def test_archive_property_archive_passes(self):
        """Component with archive property 'archive' should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:archive-property")
        assert finding is not None
        assert finding.status == "pass"

    def test_archive_property_no_archive_passes(self):
        """Component with archive property 'no archive' should pass."""
        sbom = create_base_cyclonedx_sbom()
        for prop in sbom["components"][0]["properties"]:
            if prop["name"] == "bsi:component:archive":
                prop["value"] = "no archive"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:archive-property")
        assert finding is not None
        assert finding.status == "pass"

    def test_structured_property_structured_passes(self):
        """Component with structured property 'structured' should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:structured-property")
        assert finding is not None
        assert finding.status == "pass"

    def test_structured_property_unstructured_passes(self):
        """Component with structured property 'unstructured' should pass."""
        sbom = create_base_cyclonedx_sbom()
        for prop in sbom["components"][0]["properties"]:
            if prop["name"] == "bsi:component:structured":
                prop["value"] = "unstructured"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:structured-property")
        assert finding is not None
        assert finding.status == "pass"


class TestLicenceValidation:
    """Tests for distribution licence validation."""

    def test_spdx_expression_passes(self):
        """SPDX licence expression should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:distribution-licences")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx_id_passes(self):
        """SPDX licence ID should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["licenses"] = [{"license": {"id": "MIT"}}]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:distribution-licences")
        assert finding is not None
        assert finding.status == "pass"

    def test_licence_missing_fails(self):
        """Component without licence should fail."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["licenses"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:distribution-licences")
        assert finding is not None
        assert finding.status == "fail"


class TestHashValidation:
    """Tests for SHA-512 hash validation."""

    def test_sha512_hash_present_passes(self):
        """Component with SHA-512 hash should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:hash-value")
        assert finding is not None
        assert finding.status == "pass"

    def test_sha512_in_external_refs_passes(self):
        """SHA-512 hash in externalReferences should pass."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["hashes"]
        sbom["components"][0]["externalReferences"] = [
            {
                "type": "distribution",
                "url": "https://example.com/package.whl",
                "hashes": [{"alg": "SHA-512", "content": "abc123" * 20}],
            }
        ]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:hash-value")
        assert finding is not None
        assert finding.status == "pass"

    def test_sha256_only_gives_warning(self):
        """Component with only SHA-256 hash should give warning (SHA-512 recommended)."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["hashes"] = [{"alg": "SHA-256", "content": "abc123" * 10}]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:hash-value")
        assert finding is not None
        assert finding.status == "warning"
        assert "SHA-512" in finding.description

    def test_hash_missing_fails(self):
        """Component without hash should fail."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["hashes"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:hash-value")
        assert finding is not None
        assert finding.status == "fail"


class TestDependencyValidation:
    """Tests for dependency and completeness validation."""

    def test_dependencies_with_completeness_passes(self):
        """Dependencies with completeness indicator should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:dependencies")
        assert finding is not None
        assert finding.status == "pass"

    def test_dependencies_incomplete_passes(self):
        """Dependencies marked as incomplete should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["compositions"] = [{"aggregate": "incomplete"}]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:dependencies")
        assert finding is not None
        assert finding.status == "pass"

    def test_dependencies_unknown_passes(self):
        """Dependencies marked as unknown should pass."""
        sbom = create_base_cyclonedx_sbom()
        sbom["compositions"] = [{"aggregate": "unknown"}]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:dependencies")
        assert finding is not None
        assert finding.status == "pass"

    def test_dependencies_without_completeness_fails(self):
        """Dependencies without completeness indicator should fail."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["compositions"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:dependencies")
        assert finding is not None
        assert finding.status == "fail"

    def test_no_dependencies_fails(self):
        """SBOM without dependency info should fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["dependencies"] = []
        del sbom["compositions"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:dependencies")
        assert finding is not None
        assert finding.status == "fail"


class TestUniqueIdentifiersValidation:
    """Tests for unique identifiers (purl, CPE, SWID) validation."""

    def test_purl_present_passes(self):
        """Component with purl should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:unique-identifiers")
        assert finding is not None
        assert finding.status == "pass"

    def test_cpe_present_passes(self):
        """Component with CPE should pass."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["purl"]
        sbom["components"][0]["cpe"] = "cpe:2.3:a:example:component:1.0.0:*:*:*:*:*:*:*"
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:unique-identifiers")
        assert finding is not None
        assert finding.status == "pass"

    def test_no_identifier_warns(self):
        """Component without identifier should give warning."""
        sbom = create_base_cyclonedx_sbom()
        del sbom["components"][0]["purl"]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:unique-identifiers")
        assert finding is not None
        assert finding.status == "warning"


class TestAdditionalDataFields:
    """Tests for BSI §5.2.3 / §5.2.4 additional-data-fields (MUST if exists)."""

    # --- SBOM-URI (§5.2.3) ---

    def test_cyclonedx_sbom_uri_pass_with_serialnumber(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["serialNumber"] = "urn:uuid:3e671687-395b-41f5-a30f-a58921a69b79"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_sbom_uri_warns_without_serialnumber(self):
        sbom = create_base_cyclonedx_sbom()
        sbom.pop("serialNumber", None)
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "warning"

    def test_cyclonedx_sbom_uri_warns_on_non_urn_serialnumber(self):
        """Per CDX schema, serialNumber MUST be ``urn:uuid:<uuid>``. Arbitrary
        strings must not be treated as a valid SBOM URI."""
        sbom = create_base_cyclonedx_sbom()
        sbom["serialNumber"] = "not-a-urn-uuid"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "warning"

    # --- Source code URI (§5.2.4) ---

    def test_cyclonedx_source_code_uri_pass_via_vcs_ref(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["externalReferences"] = [
            {"type": "vcs", "url": "https://github.com/example/example-component"}
        ]
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_source_code_uri_warns_without_ref(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0].pop("externalReferences", None)
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "warning"

    # --- URI of deployable form (§5.2.4) ---

    def test_cyclonedx_deployable_uri_pass_via_distribution_ref(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["externalReferences"] = [
            {"type": "distribution", "url": "https://example.com/example-component.whl"}
        ]
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_deployable_uri_warns_without_distribution_ref(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0].pop("externalReferences", None)
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "warning"

    # --- Original licences (§5.2.4) ---

    def test_cyclonedx_original_licences_pass_via_declared_acknowledgement(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["licenses"] = [{"expression": "MIT", "acknowledgement": "declared"}]
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_original_licences_pass_via_bsi_property(self):
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["properties"].append({"name": "bsi:component:effectiveLicence", "value": "MIT"})
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "pass"

    def test_cyclonedx_original_licences_warns_when_only_concluded(self):
        sbom = create_base_cyclonedx_sbom()
        # Base fixture only has acknowledgement="concluded" (effective licence).
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "warning"

    def test_cyclonedx_original_licences_pass_via_associatedLicences_bsi_property(self):
        """BSI taxonomy legacy property bsi:component:associatedLicences is
        also accepted as an original-licence signal, alongside the newer
        bsi:component:effectiveLicence."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"][0]["properties"].append({"name": "bsi:component:associatedLicences", "value": "MIT"})
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "pass"

    # --- SPDX 3.x BSI §5.2.3 / §5.2.4 paths --------------------------------

    def test_spdx3_sbom_uri_pass_when_spdxdocument_has_id(self):
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx3_sbom_uri_warns_when_no_spdxdocument_present(self):
        sbom = create_base_spdx3_sbom()
        # Remove the SpdxDocument element entirely.
        sbom["@graph"] = [e for e in sbom["@graph"] if e.get("type") != "SpdxDocument"]
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx3_source_code_uri_pass_via_software_sourceInfo(self):
        sbom = create_base_spdx3_sbom()
        for element in sbom["@graph"]:
            if element.get("type") == "software_Package":
                element["software_sourceInfo"] = "https://example.com/source"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx3_source_code_uri_pass_via_external_identifier(self):
        sbom = create_base_spdx3_sbom()
        for element in sbom["@graph"]:
            if element.get("type") == "software_Package":
                element.setdefault("externalIdentifiers", []).append(
                    {
                        "externalIdentifierType": "vcs",
                        "identifier": "https://github.com/example/repo",
                    }
                )
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx3_source_code_uri_warns_when_absent(self):
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx3_deployable_uri_pass_via_software_downloadLocation(self):
        sbom = create_base_spdx3_sbom()
        for element in sbom["@graph"]:
            if element.get("type") == "software_Package":
                element["software_downloadLocation"] = "https://example.com/pkg.whl"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx3_deployable_uri_warns_when_absent(self):
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx3_original_licences_pass_via_hasDeclaredLicense(self):
        sbom = create_base_spdx3_sbom()
        sbom["@graph"].append(
            {
                "type": "Relationship",
                "spdxId": "SPDXRef-Rel-Declared",
                "from": "SPDXRef-Package-1",
                "relationshipType": "hasDeclaredLicense",
                "to": ["SPDXRef-License-1"],
            }
        )
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx3_original_licences_warns_when_only_concluded(self):
        sbom = create_base_spdx3_sbom()
        # Base fixture has hasConcludedLicense but no hasDeclaredLicense.
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "warning"

    # --- SPDX 2.x BSI §5.2.3 / §5.2.4 paths --------------------------------

    def test_spdx2_sbom_uri_pass_via_documentNamespace(self):
        sbom = create_base_spdx2_sbom()
        sbom["documentNamespace"] = "https://example.com/docs/abc-1.0"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx_2_2_assessed_same_as_2_3(self):
        """An SPDX 2.2 document must produce the same finding IDs + statuses
        as the same content under spdxVersion: "SPDX-2.3". The BSI plugin
        dispatches both through the shared SPDX 2.x code path; pin the
        behaviour so a future schema tightening on 2.2 doesn't silently
        drop compliance signals from uploads that use that version.
        """
        sbom_23 = create_base_spdx2_sbom()
        sbom_23["documentNamespace"] = "https://example.com/docs/same-base"
        result_23 = assess_sbom(sbom_23)

        sbom_22 = create_base_spdx2_sbom()
        sbom_22["spdxVersion"] = "SPDX-2.2"
        sbom_22["documentNamespace"] = "https://example.com/docs/same-base"
        # SPDX 2.2 requires packages to carry the three licence fields
        # (kept optional in 2.3). Populate them so the document validates
        # against the 2.2-specific schema.
        for pkg in sbom_22["packages"]:
            pkg.setdefault("downloadLocation", "NOASSERTION")
            pkg.setdefault("copyrightText", "NOASSERTION")
            pkg.setdefault("licenseConcluded", "NOASSERTION")
            pkg.setdefault("licenseDeclared", "NOASSERTION")
        result_22 = assess_sbom(sbom_22)

        findings_23 = {f.id: f.status for f in result_23.findings}
        findings_22 = {f.id: f.status for f in result_22.findings}
        assert findings_22 == findings_23, f"SPDX 2.2 vs 2.3 diverged: 22={findings_22}, 23={findings_23}"

    def test_spdx2_sbom_uri_warns_without_documentNamespace(self):
        sbom = create_base_spdx2_sbom()
        sbom.pop("documentNamespace", None)
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:sbom-uri")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx2_source_code_uri_pass_via_sourceInfo(self):
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["sourceInfo"] = "https://github.com/example/repo"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx2_source_code_uri_pass_via_externalRefs_vcs(self):
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0].setdefault("externalRefs", []).append(
            {
                "referenceCategory": "SOURCE_CODE",
                "referenceType": "vcs",
                "referenceLocator": "git+https://github.com/example/repo",
            }
        )
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx2_source_code_uri_warns_when_absent(self):
        sbom = create_base_spdx2_sbom()
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:source-code-uri")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx2_deployable_uri_pass_via_downloadLocation(self):
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["downloadLocation"] = "https://pypi.org/simple/example/"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx2_deployable_uri_rejects_noassertion_placeholder(self):
        """NOASSERTION / NONE placeholders do not count as a deployable URI."""
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["downloadLocation"] = "NOASSERTION"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx2_deployable_uri_rejects_none_placeholder(self):
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["downloadLocation"] = "NONE"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:uri-deployable-form")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx2_original_licences_pass_via_licenseDeclared(self):
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["licenseDeclared"] = "MIT"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx2_original_licences_rejects_noassertion(self):
        """licenseDeclared = NOASSERTION does not count as an original licence."""
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["licenseDeclared"] = "NOASSERTION"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "warning"

    def test_spdx2_original_licences_rejects_none(self):
        """licenseDeclared = NONE does not count as an original licence.

        Per SPDX 2.3 Clause 7, NONE means "no license information whatsoever",
        which is distinct from NOASSERTION (no determination made). BSI §5.2.4
        requires the original licence to be provided when it exists — both
        placeholders signal the absence of useful data and must be rejected.
        """
        sbom = create_base_spdx2_sbom()
        sbom["packages"][0]["licenseDeclared"] = "NONE"
        result = assess_sbom(sbom)
        finding = get_finding(result, "bsi-tr03183:original-licences")
        assert finding is not None
        assert finding.status == "warning"


class TestVulnerabilityCheck:
    """Tests for vulnerability exclusion check (BSI §3.1)."""

    def test_sbom_without_vulnerabilities_passes(self):
        """SBOM without vulnerabilities should pass."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:no-vulnerabilities")
        assert finding is not None
        assert finding.status == "pass"

    def test_sbom_with_vulnerabilities_fails(self):
        """SBOM with embedded vulnerabilities should fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["vulnerabilities"] = [
            {
                "id": "CVE-2024-12345",
                "source": {"name": "NVD"},
                "ratings": [{"severity": "high"}],
            }
        ]
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:no-vulnerabilities")
        assert finding is not None
        assert finding.status == "fail"
        assert "CSAF" in finding.remediation or "VEX" in finding.remediation


class TestAttestationCheck:
    """Tests for attestation requirement cross-check."""

    def test_attestation_check_finding_present(self):
        """Attestation check finding should be present."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        # Without dependency_status, this will be a warning
        assert finding.status == "warning"

    def test_attestation_check_no_dependency_status_warns(self):
        """Attestation check without dependency status should warn."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom, dependency_status=None)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "warning"
        assert "Dependency status not available" in finding.description

    def test_attestation_check_with_passing_plugin_passes(self):
        """Attestation check with passing attestation plugin should pass."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": True,
                "passing_plugins": ["sbom-verification"],
                "failed_plugins": [],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"
        assert "sbom-verification" in finding.description

    def test_attestation_check_with_failed_plugin_fails(self):
        """Attestation check with only failed attestation plugins should fail."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": False,
                "passing_plugins": [],
                "failed_plugins": ["sbom-verification"],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "fail"
        assert "did not pass" in finding.description
        assert "sbom-verification" in finding.description

    def test_attestation_check_no_plugins_run_fails(self):
        """Attestation check with no attestation plugins run should fail."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": False,
                "passing_plugins": [],
                "failed_plugins": [],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "fail"
        assert "No attestation plugin has been run" in finding.description

    def test_attestation_check_recommends_plugins(self):
        """Attestation check should recommend attestation plugins."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        # Should mention attestation plugins in remediation
        if finding.remediation:
            assert "attestation" in finding.remediation.lower()

    def test_attestation_check_multiple_passing_plugins(self):
        """Attestation check passes with multiple passing attestation plugins."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": True,
                "passing_plugins": ["sbom-verification", "sigstore-attestation"],
                "failed_plugins": [],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"
        assert "sbom-verification" in finding.description
        assert "sigstore-attestation" in finding.description

    def test_attestation_check_mixed_passing_and_failing(self):
        """Attestation check passes if at least one plugin passes (OR logic)."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": True,
                "passing_plugins": ["sbom-verification"],
                "failed_plugins": ["other-attestation"],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"
        assert "sbom-verification" in finding.description

    def test_attestation_check_with_requires_all_ignored(self):
        """Attestation check only uses requires_one_of, ignores requires_all."""
        sbom = create_base_cyclonedx_sbom()
        # Even with requires_all failing, attestation passes if requires_one_of is satisfied
        dependency_status = {
            "requires_one_of": {
                "satisfied": True,
                "passing_plugins": ["sbom-verification"],
                "failed_plugins": [],
            },
            "requires_all": {
                "satisfied": False,
                "passing_plugins": [],
                "failed_plugins": ["some-other-plugin"],
            },
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"


class TestSPDX3Validation:
    """Tests for SPDX 3.0.1+ validation."""

    def test_spdx3_compliant_sbom_passes_required_checks(self):
        """A compliant SPDX 3.0.1 SBOM should pass required checks."""
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)

        # Check format version passes
        format_finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert format_finding is not None
        assert format_finding.status == "pass"

        # Check SBOM creator passes
        creator_finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert creator_finding is not None
        assert creator_finding.status == "pass"

        # Check timestamp passes
        timestamp_finding = get_finding(result, "bsi-tr03183:timestamp")
        assert timestamp_finding is not None
        assert timestamp_finding.status == "pass"

    def test_spdx3_package_name_validated(self):
        """SPDX 3.0.1 package name should be validated."""
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-name")
        assert finding is not None
        assert finding.status == "pass"

    def test_spdx3_package_version_validated(self):
        """SPDX 3.0.1 package version should be validated."""
        sbom = create_base_spdx3_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-version")
        assert finding is not None
        assert finding.status == "pass"


class TestSPDX2LegacyValidation:
    """Tests for SPDX 2.x legacy validation."""

    def test_spdx2_fails_format_check(self):
        """SPDX 2.x should fail format version check."""
        sbom = create_base_spdx2_sbom()
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:sbom-format")
        assert finding is not None
        assert finding.status == "fail"

    def test_spdx2_still_validates_basic_fields(self):
        """SPDX 2.x should still validate basic fields even though format fails."""
        sbom = create_base_spdx2_sbom()
        result = assess_sbom(sbom)

        # Should still check SBOM creator
        creator_finding = get_finding(result, "bsi-tr03183:sbom-creator")
        assert creator_finding is not None

        # Should still check timestamp
        timestamp_finding = get_finding(result, "bsi-tr03183:timestamp")
        assert timestamp_finding is not None

    def test_spdx2_bsi_specific_fields_fail(self):
        """BSI-specific fields should fail for SPDX 2.x."""
        sbom = create_base_spdx2_sbom()
        result = assess_sbom(sbom)

        # These fields are not available in SPDX 2.x
        for field_id in [
            "bsi-tr03183:filename",
            "bsi-tr03183:executable-property",
            "bsi-tr03183:archive-property",
            "bsi-tr03183:structured-property",
        ]:
            finding = get_finding(result, field_id)
            assert finding is not None
            assert finding.status == "fail"
            assert "SPDX 2.x" in finding.description or "3.0.1" in finding.remediation


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_json_returns_error(self):
        """Invalid JSON should return error result."""
        plugin = BSICompliancePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            sbom_path = Path(f.name)

        try:
            result = plugin.assess("test-sbom-id", sbom_path, dependency_status=None)
        finally:
            sbom_path.unlink()

        assert result.summary.error_count == 1
        assert any(f.status == "error" for f in result.findings)

    def test_unknown_format_returns_error(self):
        """Unknown SBOM format should return error."""
        sbom = {"unknown": "format", "no": "version"}
        result = assess_sbom(sbom)

        assert result.summary.error_count == 1
        assert any(f.status == "error" for f in result.findings)


class TestAssessmentSummary:
    """Tests for assessment summary calculations."""

    def test_summary_counts_correct(self):
        """Summary should have correct counts."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        total = (
            result.summary.pass_count
            + result.summary.fail_count
            + result.summary.warning_count
            + result.summary.error_count
        )
        # Note: info status findings are not counted in the standard counters
        assert result.summary.total_findings >= total

    def test_fully_compliant_sbom_has_mostly_passes(self):
        """Fully compliant SBOM should have mostly passes."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        assert result.summary.pass_count > result.summary.fail_count
        assert result.summary.error_count == 0

    def test_metadata_includes_standard_info(self):
        """Result metadata should include standard information."""
        sbom = create_base_cyclonedx_sbom()
        result = assess_sbom(sbom)

        assert result.metadata["standard_name"] == BSICompliancePlugin.STANDARD_NAME
        assert result.metadata["standard_version"] == BSICompliancePlugin.STANDARD_VERSION
        assert result.metadata["standard_url"] == BSICompliancePlugin.STANDARD_URL
        assert result.metadata["sbom_format"] == "cyclonedx"
        assert result.metadata["sbom_format_version"] == "1.6"


class TestMultipleComponents:
    """Tests for SBOMs with multiple components."""

    def test_multiple_components_all_valid(self):
        """All components should be validated."""
        sbom = create_base_cyclonedx_sbom()
        # Add a second component
        second_component = {
            "name": "second-component",
            "version": "2.0.0",
            "manufacturer": {
                "name": "Example Corp",
                "url": "https://example.com",
            },
            "purl": "pkg:pypi/second-component@2.0.0",
            "licenses": [{"expression": "Apache-2.0"}],
            "hashes": [{"alg": "SHA-512", "content": "def456" * 20}],
            "properties": [
                {"name": "bsi:component:filename", "value": "second-component.whl"},
                {"name": "bsi:component:executable", "value": "executable"},
                {"name": "bsi:component:archive", "value": "archive"},
                {"name": "bsi:component:structured", "value": "structured"},
            ],
        }
        sbom["components"].append(second_component)
        result = assess_sbom(sbom)

        # All component-level checks should pass
        assert get_finding(result, "bsi-tr03183:component-name").status == "pass"
        assert get_finding(result, "bsi-tr03183:component-version").status == "pass"
        assert get_finding(result, "bsi-tr03183:component-creator").status == "pass"

    def test_one_invalid_component_fails(self):
        """One invalid component should cause failure."""
        sbom = create_base_cyclonedx_sbom()
        # Add an invalid component (missing required fields)
        sbom["components"].append(
            {
                "name": "invalid-component",
                # Missing: version, manufacturer, licenses, hashes, properties
            }
        )
        result = assess_sbom(sbom)

        # Component-level checks should fail
        assert get_finding(result, "bsi-tr03183:component-version").status == "fail"
        assert get_finding(result, "bsi-tr03183:component-creator").status == "fail"


class TestMalformedInputHandling:
    """Regression tests for malformed SBOM field types."""

    def test_spdx2_malformed_relationship_type_as_list(self) -> None:
        """relationshipType as list should not crash."""
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "packages": [{"SPDXID": "SPDXRef-Pkg", "name": "test", "supplier": "Org: T", "versionInfo": "1.0"}],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": ["DEPENDS_ON"],
                    "relatedSpdxElement": "SPDXRef-Pkg",
                }
            ],
            "creationInfo": {"creators": ["Tool: test"], "created": "2023-01-01T00:00:00Z"},
        }
        result = assess_sbom(sbom)
        assert result.summary.error_count == 0

    def test_spdx2_malformed_reference_type_as_list(self) -> None:
        """referenceType as list should not crash."""
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Pkg",
                    "name": "test",
                    "supplier": "Org: T",
                    "versionInfo": "1.0",
                    "externalRefs": [{"referenceType": ["purl"]}],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Pkg",
                }
            ],
            "creationInfo": {"creators": ["Tool: test"], "created": "2023-01-01T00:00:00Z"},
        }
        result = assess_sbom(sbom)
        assert result.summary.error_count == 0


class TestFormatFailureDetails:
    """Tests for BSI plugin _format_failure_details truncation."""

    def test_small_list_shows_all(self):
        plugin = BSICompliancePlugin({})
        result = plugin._format_failure_details(["a", "b", "c"])
        assert result == "Missing for: a, b, c"

    def test_exactly_max_shown_shows_all(self):
        plugin = BSICompliancePlugin({})
        result = plugin._format_failure_details(["a", "b", "c", "d", "e"])
        assert result == "Missing for: a, b, c, d, e"

    def test_large_list_truncated_with_count(self):
        plugin = BSICompliancePlugin({})
        packages = [f"pkg{i}" for i in range(200)]
        result = plugin._format_failure_details(packages)
        assert result.startswith("Missing for:")
        assert "pkg0" in result
        assert "pkg4" in result
        assert "pkg5" not in result
        assert "(200 total; 195 more)" in result

    def test_custom_max_shown(self):
        plugin = BSICompliancePlugin({})
        result = plugin._format_failure_details(["a", "b", "c", "d"], max_shown=2)
        assert result == "Missing for: a, b (4 total; 2 more)"


class TestFileTypeComponentSkipped:
    """BSI must skip type=file / File-entry components across per-component checks.

    BSI TR-03183-2 §5.2.2 applies to software components. Generators like syft
    emit scan-input artifacts (e.g. lockfiles) as type=file in CycloneDX or with
    "-File-" in the SPDXID in SPDX, which lack version/creator/licence/properties
    by design. These entries should not contribute to failure counts.
    """

    def test_cyclonedx_file_type_skipped_across_all_component_checks(self):
        """A type=file component without any BSI fields should not cause failures."""
        sbom = create_base_cyclonedx_sbom()
        # Add a bare file-type component alongside the valid library component.
        sbom["components"].append(
            {
                "name": "uv.lock",
                "type": "file",
                "hashes": [{"alg": "SHA-256", "content": "def456" * 20}],
            }
        )
        result = assess_sbom(sbom)

        # All per-component BSI checks should still pass because the only
        # non-compliant entry is a file-type component that must be skipped.
        for finding_id in (
            "bsi-tr03183:component-version",
            "bsi-tr03183:component-creator",
            "bsi-tr03183:filename",
            "bsi-tr03183:distribution-licences",
            "bsi-tr03183:hash-value",
            "bsi-tr03183:executable-property",
            "bsi-tr03183:archive-property",
            "bsi-tr03183:structured-property",
        ):
            finding = get_finding(result, finding_id)
            assert finding is not None, f"{finding_id} missing from result"
            assert finding.status == "pass", f"{finding_id} should pass but got {finding.status}: {finding.description}"

    def test_cyclonedx_file_type_component_name_still_validated(self):
        """Component Name is universal — file-type entries without a name still fail."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"].append({"type": "file"})
        result = assess_sbom(sbom)

        finding = get_finding(result, "bsi-tr03183:component-name")
        assert finding is not None
        assert finding.status == "fail", "nameless file-type entry should still fail name check"

    def test_spdx2_file_entry_skipped_in_version_and_creator_checks(self):
        """SPDX 2.x File-entries (SPDXID contains -File-) must be skipped for
        the component-version and component-creator checks when versionInfo and
        supplier data are not applicable to file inputs."""
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {
                "created": "2024-01-15T12:00:00Z",
                "creators": ["Tool: test", "Organization: Example Corp (sbom@example.com)"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.2.3",
                    "supplier": "Organization: Django",
                    "downloadLocation": "NOASSERTION",
                },
                {
                    # No versionInfo, no supplier — File entry should be skipped
                    "SPDXID": "SPDXRef-DocumentRoot-File-uv.lock",
                    "name": "uv.lock",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                },
                {
                    "spdxElementId": "SPDXRef-Package-django",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                },
            ],
        }
        result = assess_sbom(sbom)

        version = get_finding(result, "bsi-tr03183:component-version")
        creator = get_finding(result, "bsi-tr03183:component-creator")
        assert version is not None and version.status == "pass", (
            f"File entry without versionInfo should be skipped: {version.description if version else None}"
        )
        assert creator is not None and creator.status == "pass", (
            f"File entry without supplier should be skipped: {creator.description if creator else None}"
        )

    def test_library_with_missing_fields_still_fails_alongside_file_type(self):
        """Regression guard: the skip must only apply to type=file.

        If a real library component is missing version/creator/filename etc and
        a file-type entry coexists, the library failures must still surface — we
        must not accidentally widen the skip.
        """
        sbom = create_base_cyclonedx_sbom()
        sbom["components"].append(
            {
                "name": "broken-lib",
                "type": "library",
                "purl": "pkg:pypi/broken-lib@unknown",
                # No version, no manufacturer, no filename, no licence, no hashes
            }
        )
        sbom["components"].append({"name": "uv.lock", "type": "file"})
        result = assess_sbom(sbom)

        for finding_id in (
            "bsi-tr03183:component-version",
            "bsi-tr03183:component-creator",
        ):
            finding = get_finding(result, finding_id)
            assert finding is not None, f"{finding_id} missing"
            assert finding.status == "fail", (
                f"{finding_id} must fail for library missing the field (got {finding.status})"
            )
            assert "broken-lib" in (finding.description or ""), (
                f"{finding_id} description should mention broken-lib: {finding.description}"
            )
            assert "uv.lock" not in (finding.description or ""), (
                f"{finding_id} description must NOT mention file-type uv.lock: {finding.description}"
            )

    def test_cyclonedx_multiple_file_type_components_all_skipped(self):
        """All file-type components should be skipped, not just the first one."""
        sbom = create_base_cyclonedx_sbom()
        sbom["components"].extend(
            [
                {"name": "uv.lock", "type": "file"},
                {"name": "poetry.lock", "type": "FILE"},  # case-insensitive
                {"name": "package-lock.json", "type": "File"},
            ]
        )
        result = assess_sbom(sbom)

        for finding_id in (
            "bsi-tr03183:component-version",
            "bsi-tr03183:component-creator",
            "bsi-tr03183:filename",
            "bsi-tr03183:distribution-licences",
            "bsi-tr03183:hash-value",
            "bsi-tr03183:executable-property",
            "bsi-tr03183:archive-property",
            "bsi-tr03183:structured-property",
        ):
            finding = get_finding(result, finding_id)
            assert finding is not None, f"{finding_id} missing"
            assert finding.status == "pass", (
                f"{finding_id} should pass with 3 file-type entries (got {finding.status}): {finding.description}"
            )
