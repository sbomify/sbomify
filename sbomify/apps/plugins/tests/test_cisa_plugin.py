"""Tests for the CISA 2025 Minimum Elements compliance plugin.

Tests validation of SBOMs against the CISA Minimum Elements for a Software
Bill of Materials as defined in the August 2025 public comment draft.
"""

import json
import tempfile
from pathlib import Path

from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult


class TestCISAPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = CISAMinimumElementsPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "cisa-minimum-elements-2025"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_standard_info(self) -> None:
        """Test that plugin has correct standard information."""
        plugin = CISAMinimumElementsPlugin()

        assert (
            plugin.STANDARD_NAME
            == "CISA 2025 Minimum Elements for a Software Bill of Materials (SBOM) - Public Comment Draft"
        )
        assert plugin.STANDARD_VERSION == "2025-08-draft"
        assert (
            plugin.STANDARD_URL
            == "https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf"
        )

    def test_finding_ids_match_standard(self) -> None:
        """Test that finding IDs are properly formatted with standard version."""
        plugin = CISAMinimumElementsPlugin()

        for key, finding_id in plugin.FINDING_IDS.items():
            assert finding_id.startswith("cisa-2025:"), f"Finding ID {finding_id} should start with 'cisa-2025:'"

    def test_all_eleven_elements_have_finding_ids(self) -> None:
        """Test that all 11 CISA 2025 elements have finding IDs."""
        plugin = CISAMinimumElementsPlugin()

        expected_elements = {
            "sbom_author",
            "software_producer",
            "component_name",
            "component_version",
            "software_identifiers",
            "component_hash",
            "license",
            "dependency_relationship",
            "tool_name",
            "timestamp",
            "generation_context",
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
                    "hashes": [{"alg": "SHA-256", "content": "abc123def456"}],
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "tools": [{"name": "sbom-generator", "version": "1.0.0"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cdx:sbom:generationContext", "value": "build"}],
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 11  # All 11 CISA elements
        assert result.summary.total_findings == 11

    def test_cyclonedx_missing_software_producer(self) -> None:
        """Test CycloneDX SBOM missing software producer information."""
        sbom_data = self._create_base_cyclonedx_sbom()
        # Remove publisher and supplier
        del sbom_data["components"][0]["publisher"]

        result = self._assess_sbom(sbom_data)

        producer_finding = next(f for f in result.findings if "software-producer" in f.id)
        assert producer_finding.status == "fail"

    def test_cyclonedx_missing_component_version(self) -> None:
        """Test CycloneDX SBOM missing component version."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["version"]

        result = self._assess_sbom(sbom_data)

        version_finding = next(f for f in result.findings if "component-version" in f.id)
        assert version_finding.status == "fail"

    def test_cyclonedx_missing_software_identifiers(self) -> None:
        """Test CycloneDX SBOM missing software identifiers."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["purl"]

        result = self._assess_sbom(sbom_data)

        identifier_finding = next(f for f in result.findings if "software-identifiers" in f.id)
        assert identifier_finding.status == "fail"

    def test_cyclonedx_missing_component_hash(self) -> None:
        """Test CycloneDX SBOM missing component hash (NEW element)."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["hashes"]

        result = self._assess_sbom(sbom_data)

        hash_finding = next(f for f in result.findings if "component-hash" in f.id)
        assert hash_finding.status == "fail"

    def test_cyclonedx_missing_license(self) -> None:
        """Test CycloneDX SBOM missing license (NEW element)."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["licenses"]

        result = self._assess_sbom(sbom_data)

        license_finding = next(f for f in result.findings if f.id == "cisa-2025:license")
        assert license_finding.status == "fail"

    def test_cyclonedx_missing_dependencies(self) -> None:
        """Test CycloneDX SBOM missing dependency relationships."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["dependencies"]

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency-relationship" in f.id)
        assert dep_finding.status == "fail"

    def test_cyclonedx_missing_sbom_author(self) -> None:
        """Test CycloneDX SBOM missing SBOM author."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["authors"]
        del sbom_data["metadata"]["tools"]

        result = self._assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_cyclonedx_missing_tool_name(self) -> None:
        """Test CycloneDX SBOM missing tool name (NEW element)."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["tools"]

        result = self._assess_sbom(sbom_data)

        tool_finding = next(f for f in result.findings if "tool-name" in f.id)
        assert tool_finding.status == "fail"

    def test_cyclonedx_missing_timestamp(self) -> None:
        """Test CycloneDX SBOM missing timestamp."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["timestamp"]

        result = self._assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if "timestamp" in f.id)
        assert timestamp_finding.status == "fail"

    def test_cyclonedx_missing_generation_context(self) -> None:
        """Test CycloneDX SBOM missing generation context (NEW element)."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["metadata"]["properties"]

        result = self._assess_sbom(sbom_data)

        context_finding = next(f for f in result.findings if "generation-context" in f.id)
        assert context_finding.status == "fail"

    def test_cyclonedx_with_supplier_object(self) -> None:
        """Test CycloneDX SBOM with supplier.name instead of publisher."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["publisher"]
        sbom_data["components"][0]["supplier"] = {"name": "Example Corp"}

        result = self._assess_sbom(sbom_data)

        producer_finding = next(f for f in result.findings if "software-producer" in f.id)
        assert producer_finding.status == "pass"

    def test_cyclonedx_with_cpe_identifier(self) -> None:
        """Test CycloneDX SBOM with CPE instead of PURL."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["purl"]
        sbom_data["components"][0]["cpe"] = "cpe:2.3:a:example:component:1.0.0:*:*:*:*:*:*:*"

        result = self._assess_sbom(sbom_data)

        identifier_finding = next(f for f in result.findings if "software-identifiers" in f.id)
        assert identifier_finding.status == "pass"

    def test_cyclonedx_with_swid_identifier(self) -> None:
        """Test CycloneDX SBOM with SWID instead of PURL."""
        sbom_data = self._create_base_cyclonedx_sbom()
        del sbom_data["components"][0]["purl"]
        sbom_data["components"][0]["swid"] = {"tagId": "example-swid-tag"}

        result = self._assess_sbom(sbom_data)

        identifier_finding = next(f for f in result.findings if "software-identifiers" in f.id)
        assert identifier_finding.status == "pass"

    def test_cyclonedx_tools_1_5_format(self) -> None:
        """Test CycloneDX 1.5+ tools format with components array."""
        sbom_data = self._create_base_cyclonedx_sbom()
        sbom_data["metadata"]["tools"] = {"components": [{"name": "sbom-tool", "version": "2.0.0"}]}

        result = self._assess_sbom(sbom_data)

        tool_finding = next(f for f in result.findings if "tool-name" in f.id)
        assert tool_finding.status == "pass"

    def test_cyclonedx_generation_context_values(self) -> None:
        """Test all valid generation context values."""
        valid_contexts = ["before_build", "build", "post_build", "source", "analyzed"]

        for context in valid_contexts:
            sbom_data = self._create_base_cyclonedx_sbom()
            sbom_data["metadata"]["properties"] = [{"name": "cdx:sbom:generationContext", "value": context}]

            result = self._assess_sbom(sbom_data)

            context_finding = next(f for f in result.findings if "generation-context" in f.id)
            assert context_finding.status == "pass", f"Context '{context}' should be valid"

    def test_cyclonedx_invalid_generation_context(self) -> None:
        """Test invalid generation context value."""
        sbom_data = self._create_base_cyclonedx_sbom()
        sbom_data["metadata"]["properties"] = [{"name": "cdx:sbom:generationContext", "value": "invalid_context"}]

        result = self._assess_sbom(sbom_data)

        context_finding = next(f for f in result.findings if "generation-context" in f.id)
        assert context_finding.status == "fail"

    def _create_base_cyclonedx_sbom(self) -> dict:
        """Create a base compliant CycloneDX SBOM for testing."""
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "hashes": [{"alg": "SHA-256", "content": "abc123def456"}],
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "tools": [{"name": "sbom-generator", "version": "1.0.0"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cdx:sbom:generationContext", "value": "build"}],
            },
        }

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = CISAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


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
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "checksums": [{"algorithm": "SHA256", "checksumValue": "abc123def456"}],
                    "licenseConcluded": "MIT",
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
                "creators": ["Tool: example-tool (1.0.0)", "Person: Developer"],
                "created": "2023-01-01T00:00:00Z",
            },
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "comment": "cisa:generationContext=build",
                    "annotator": "Tool: example-tool",
                    "annotationDate": "2023-01-01T00:00:00Z",
                }
            ],
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 11

    def test_spdx_missing_software_producer(self) -> None:
        """Test SPDX SBOM missing software producer (supplier)."""
        sbom_data = self._create_base_spdx_sbom()
        del sbom_data["packages"][0]["supplier"]

        result = self._assess_sbom(sbom_data)

        producer_finding = next(f for f in result.findings if "software-producer" in f.id)
        assert producer_finding.status == "fail"

    def test_spdx_missing_component_hash(self) -> None:
        """Test SPDX SBOM missing component hash (checksums)."""
        sbom_data = self._create_base_spdx_sbom()
        del sbom_data["packages"][0]["checksums"]

        result = self._assess_sbom(sbom_data)

        hash_finding = next(f for f in result.findings if "component-hash" in f.id)
        assert hash_finding.status == "fail"

    def test_spdx_missing_license(self) -> None:
        """Test SPDX SBOM missing license."""
        sbom_data = self._create_base_spdx_sbom()
        del sbom_data["packages"][0]["licenseConcluded"]

        result = self._assess_sbom(sbom_data)

        license_finding = next(f for f in result.findings if f.id == "cisa-2025:license")
        assert license_finding.status == "fail"

    def test_spdx_with_license_declared(self) -> None:
        """Test SPDX SBOM with licenseDeclared instead of licenseConcluded."""
        sbom_data = self._create_base_spdx_sbom()
        del sbom_data["packages"][0]["licenseConcluded"]
        sbom_data["packages"][0]["licenseDeclared"] = "Apache-2.0"

        result = self._assess_sbom(sbom_data)

        license_finding = next(f for f in result.findings if f.id == "cisa-2025:license")
        assert license_finding.status == "pass"

    def test_spdx_noassertion_license_passes(self) -> None:
        """Test SPDX SBOM with NOASSERTION license passes validation.

        CISA says: "If the SBOM author is not aware of the license information,
        then the SBOM author should indicate that license information is unknown."
        NOASSERTION explicitly indicates unknown license, so it should pass.
        """
        sbom_data = self._create_base_spdx_sbom()
        sbom_data["packages"][0]["licenseConcluded"] = "NOASSERTION"

        result = self._assess_sbom(sbom_data)

        license_finding = next(f for f in result.findings if f.id == "cisa-2025:license")
        assert license_finding.status == "pass"

    def test_spdx_missing_tool_name(self) -> None:
        """Test SPDX SBOM missing Tool: entry in creators."""
        sbom_data = self._create_base_spdx_sbom()
        sbom_data["creationInfo"]["creators"] = ["Person: Developer"]

        result = self._assess_sbom(sbom_data)

        tool_finding = next(f for f in result.findings if "tool-name" in f.id)
        assert tool_finding.status == "fail"

    def test_spdx_missing_generation_context(self) -> None:
        """Test SPDX SBOM missing generation context annotation."""
        sbom_data = self._create_base_spdx_sbom()
        del sbom_data["annotations"]

        result = self._assess_sbom(sbom_data)

        context_finding = next(f for f in result.findings if "generation-context" in f.id)
        assert context_finding.status == "fail"

    def test_spdx_with_contains_relationship(self) -> None:
        """Test SPDX SBOM with CONTAINS relationship."""
        sbom_data = self._create_base_spdx_sbom()
        sbom_data["relationships"][0]["relationshipType"] = "CONTAINS"

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency-relationship" in f.id)
        assert dep_finding.status == "pass"

    def test_spdx_with_descendant_of_relationship(self) -> None:
        """Test SPDX SBOM with DESCENDANT_OF relationship (for forks/backports)."""
        sbom_data = self._create_base_spdx_sbom()
        sbom_data["relationships"][0]["relationshipType"] = "DESCENDANT_OF"

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency-relationship" in f.id)
        assert dep_finding.status == "pass"

    def test_spdx_invalid_timestamp_format(self) -> None:
        """Test SPDX SBOM with invalid timestamp format."""
        sbom_data = self._create_base_spdx_sbom()
        sbom_data["creationInfo"]["created"] = "invalid-timestamp"

        result = self._assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if "timestamp" in f.id)
        assert timestamp_finding.status == "fail"

    def test_spdx_generation_context_values(self) -> None:
        """Test all valid generation context values in SPDX."""
        valid_contexts = ["before_build", "build", "post_build", "source", "analyzed"]

        for context in valid_contexts:
            sbom_data = self._create_base_spdx_sbom()
            sbom_data["annotations"][0]["comment"] = f"cisa:generationContext={context}"

            result = self._assess_sbom(sbom_data)

            context_finding = next(f for f in result.findings if "generation-context" in f.id)
            assert context_finding.status == "pass", f"Context '{context}' should be valid"

    def _create_base_spdx_sbom(self) -> dict:
        """Create a base compliant SPDX SBOM for testing."""
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
                    "checksums": [{"algorithm": "SHA256", "checksumValue": "abc123def456"}],
                    "licenseConcluded": "MIT",
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
                "creators": ["Tool: example-tool (1.0.0)", "Person: Developer"],
                "created": "2023-01-01T00:00:00Z",
            },
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "comment": "cisa:generationContext=build",
                    "annotator": "Tool: example-tool",
                    "annotationDate": "2023-01-01T00:00:00Z",
                }
            ],
        }

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = CISAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestErrorHandling:
    """Tests for error handling in the plugin."""

    def test_invalid_json(self) -> None:
        """Test handling of invalid JSON file."""
        plugin = CISAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert result.metadata.get("error") is True

    def test_unknown_format(self) -> None:
        """Test handling of unknown SBOM format."""
        plugin = CISAMinimumElementsPlugin()
        sbom_data = {"some": "data", "without": "format indicators"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert "format" in result.findings[0].description.lower()

    def test_empty_components(self) -> None:
        """Test handling of SBOM with empty components list."""
        plugin = CISAMinimumElementsPlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "dependencies": [],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "tools": [{"name": "sbom-generator"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cdx:sbom:generationContext", "value": "build"}],
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

        plugin = CISAMinimumElementsPlugin()
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
                    "hashes": [{"alg": "SHA-256", "content": "abc123"}],
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            ],
            "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "tools": [{"name": "tool"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cdx:sbom:generationContext", "value": "build"}],
            },
        }

        plugin = CISAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            assert finding.metadata is not None
            assert finding.metadata.get("standard") == "CISA"
            assert finding.metadata.get("standard_version") == "2025-08-draft"

    def test_result_includes_standard_info(self) -> None:
        """Test that assessment result includes standard reference information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = CISAMinimumElementsPlugin()
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
                {"name": "comp1"},  # Missing version, producer, hash, license, identifier
                {"name": "comp2", "version": "1.0"},  # Missing producer, hash, license, identifier
                {"name": "comp3", "version": "1.0", "publisher": "Pub"},  # Missing hash, license, identifier
            ],
            "dependencies": [{"ref": "comp1", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "tools": [{"name": "tool"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cdx:sbom:generationContext", "value": "build"}],
            },
        }

        plugin = CISAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # Check that failures are reported for components
        producer_finding = next(f for f in result.findings if "software-producer" in f.id)
        assert producer_finding.status == "fail"
        assert "comp1" in producer_finding.description
        assert "comp2" in producer_finding.description

        version_finding = next(f for f in result.findings if "component-version" in f.id)
        assert version_finding.status == "fail"
        assert "comp1" in version_finding.description

    def test_failure_message_truncation(self) -> None:
        """Test that failure messages are truncated when many components fail."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [{"name": f"comp{i}"} for i in range(10)],  # 10 components, all missing fields
            "dependencies": [{"ref": "comp0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "tools": [{"name": "tool"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "properties": [{"name": "cdx:sbom:generationContext", "value": "build"}],
            },
        }

        plugin = CISAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # Check that failure message indicates "and X more"
        producer_finding = next(f for f in result.findings if "software-producer" in f.id)
        assert "and 5 more" in producer_finding.description


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

        plugin = CISAMinimumElementsPlugin()
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

        plugin = CISAMinimumElementsPlugin()
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

        plugin = CISAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["sbom_format"] == "spdx"
