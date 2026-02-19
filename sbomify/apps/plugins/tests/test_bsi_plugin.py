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
                "passing_plugins": ["github-attestation"],
                "failed_plugins": [],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"
        assert "github-attestation" in finding.description

    def test_attestation_check_with_failed_plugin_fails(self):
        """Attestation check with only failed attestation plugins should fail."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": False,
                "passing_plugins": [],
                "failed_plugins": ["github-attestation"],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "fail"
        assert "did not pass" in finding.description
        assert "github-attestation" in finding.description

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
                "passing_plugins": ["github-attestation", "sigstore-attestation"],
                "failed_plugins": [],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"
        assert "github-attestation" in finding.description
        assert "sigstore-attestation" in finding.description

    def test_attestation_check_mixed_passing_and_failing(self):
        """Attestation check passes if at least one plugin passes (OR logic)."""
        sbom = create_base_cyclonedx_sbom()
        dependency_status = {
            "requires_one_of": {
                "satisfied": True,
                "passing_plugins": ["github-attestation"],
                "failed_plugins": ["other-attestation"],
            }
        }
        result = assess_sbom(sbom, dependency_status=dependency_status)

        finding = get_finding(result, "bsi-tr03183:attestation-check")
        assert finding is not None
        assert finding.status == "pass"
        assert "github-attestation" in finding.description

    def test_attestation_check_with_requires_all_ignored(self):
        """Attestation check only uses requires_one_of, ignores requires_all."""
        sbom = create_base_cyclonedx_sbom()
        # Even with requires_all failing, attestation passes if requires_one_of is satisfied
        dependency_status = {
            "requires_one_of": {
                "satisfied": True,
                "passing_plugins": ["github-attestation"],
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
