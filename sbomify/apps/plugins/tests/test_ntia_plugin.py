"""Tests for the NTIA Minimum Elements 2021 compliance plugin.

Tests validation of SBOMs against the NTIA Minimum Elements for a Software
Bill of Materials as defined in the July 2021 report.
"""

import json
import tempfile
from pathlib import Path

from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult


class TestNTIAPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = NTIAMinimumElementsPlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "ntia-minimum-elements-2021"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_standard_info(self) -> None:
        """Test that plugin has correct standard information."""
        plugin = NTIAMinimumElementsPlugin()

        assert plugin.STANDARD_NAME == "NTIA Minimum Elements for a Software Bill of Materials (SBOM)"
        assert plugin.STANDARD_VERSION == "2021-07"
        # Using exact URL match to avoid CodeQL incomplete URL substring sanitization warning
        assert plugin.STANDARD_URL == "https://www.ntia.gov/report/2021/minimum-elements-software-bill-materials-sbom"

    def test_finding_ids_match_standard(self) -> None:
        """Test that finding IDs are properly formatted with standard version."""
        plugin = NTIAMinimumElementsPlugin()

        for key, finding_id in plugin.FINDING_IDS.items():
            assert finding_id.startswith("ntia-2021:"), f"Finding ID {finding_id} should start with 'ntia-2021:'"


class TestCycloneDXValidation:
    """Tests for CycloneDX SBOM validation."""

    def test_compliant_cyclonedx_sbom(self) -> None:
        """Test validation of a compliant CycloneDX SBOM."""
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
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 7  # All 7 NTIA elements
        assert result.summary.total_findings == 7

    def test_cyclonedx_missing_supplier(self) -> None:
        """Test CycloneDX SBOM missing supplier information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    # Missing publisher and supplier
                    "purl": "pkg:pypi/example-component@1.0.0",
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
        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "fail"

    def test_cyclonedx_missing_version(self) -> None:
        """Test CycloneDX SBOM missing version information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
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
        version_finding = next(f for f in result.findings if "version" in f.id)
        assert version_finding.status == "fail"

    def test_cyclonedx_missing_dependencies(self) -> None:
        """Test CycloneDX SBOM missing dependency relationships."""
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
            # Missing dependencies section
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency" in f.id)
        assert dep_finding.status == "fail"

    def test_cyclonedx_missing_author(self) -> None:
        """Test CycloneDX SBOM missing SBOM author."""
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
                # Missing authors and tools
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_cyclonedx_missing_timestamp(self) -> None:
        """Test CycloneDX SBOM missing timestamp."""
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
                # Missing timestamp
            },
        }

        result = self._assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if "timestamp" in f.id)
        assert timestamp_finding.status == "fail"

    def test_cyclonedx_with_tools_instead_of_authors(self) -> None:
        """Test CycloneDX SBOM with only tools field fails author requirement.

        NTIA "Author of SBOM Data" = "the entity that creates the SBOM".
        Tools are software, not entities - they should not satisfy the author requirement.
        """
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
                "tools": [{"name": "sbom-generator"}],  # Using tools instead of authors
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_cyclonedx_with_supplier_object(self) -> None:
        """Test CycloneDX SBOM with supplier.name instead of publisher."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "supplier": {"name": "Example Corp"},  # Using supplier.name
                    "purl": "pkg:pypi/example-component@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "pass"

    def test_cyclonedx_with_hashes_as_unique_id(self) -> None:
        """Test CycloneDX SBOM with only hashes fails unique identifier requirement.

        Hashes are for "Component Hash" (RECOMMENDED), not "Unique Identifiers" (MINIMUM).
        Valid unique identifiers are: PURL, CPE, SWID.
        """
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "hashes": [{"alg": "SHA-256", "content": "abc123"}],  # Using hashes instead of purl
                }
            ],
            "dependencies": [{"ref": "example-component", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        unique_id_finding = next(f for f in result.findings if "unique-identifier" in f.id)
        assert unique_id_finding.status == "fail"

    def test_cyclonedx_with_cpe_as_unique_id(self) -> None:
        """Test CycloneDX SBOM with CPE satisfies unique identifier requirement."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "cpe": "cpe:2.3:a:example:component:1.0.0:*:*:*:*:*:*:*",
                }
            ],
            "dependencies": [{"ref": "example-component", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        unique_id_finding = next(f for f in result.findings if "unique-identifier" in f.id)
        assert unique_id_finding.status == "pass"

    def test_cyclonedx_with_swid_as_unique_id(self) -> None:
        """Test CycloneDX SBOM with SWID satisfies unique identifier requirement."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "swid": {"tagId": "example.com+example-component@1.0.0"},
                }
            ],
            "dependencies": [{"ref": "example-component", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        unique_id_finding = next(f for f in result.findings if "unique-identifier" in f.id)
        assert unique_id_finding.status == "pass"

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = NTIAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestSPDXValidation:
    """Tests for SPDX SBOM validation."""

    def test_compliant_spdx_sbom(self) -> None:
        """Test validation of a compliant SPDX SBOM."""
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
        assert result.summary.pass_count == 7

    def test_spdx_missing_supplier(self) -> None:
        """Test SPDX SBOM missing supplier information."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    # Missing supplier
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
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier" in f.id)
        assert supplier_finding.status == "fail"

    def test_spdx_missing_all_required_fields(self) -> None:
        """Test SPDX SBOM missing all required fields."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    # Missing name, supplier, version, unique identifiers
                }
            ],
            # Missing relationships
            "creationInfo": {
                # Missing creators and timestamp
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count >= 6  # Most elements should fail

    def test_spdx_with_contains_relationship(self) -> None:
        """Test SPDX SBOM with CONTAINS relationship satisfies dependency requirement."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:pypi/example@1.0.0"}],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "CONTAINS",  # Using CONTAINS instead of DEPENDS_ON
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency" in f.id)
        assert dep_finding.status == "pass"

    def test_spdx_invalid_timestamp_format(self) -> None:
        """Test SPDX SBOM with invalid timestamp format."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:pypi/example@1.0.0"}],
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
                "created": "invalid-timestamp",  # Invalid format
            },
        }

        result = self._assess_sbom(sbom_data)

        timestamp_finding = next(f for f in result.findings if "timestamp" in f.id)
        assert timestamp_finding.status == "fail"

    def test_spdx_with_invalid_external_ref_type(self) -> None:
        """Test SPDX SBOM with invalid externalRef type fails unique identifier requirement.

        Only purl, cpe22Type, cpe23Type, and swid are valid identifier types.
        Other reference types (like security advisory, URL, etc.) should not count.
        """
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
                            "referenceCategory": "SECURITY",
                            "referenceType": "advisory",  # Invalid type for unique identifier
                            "referenceLocator": "https://example.com/advisory/123",
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

        unique_id_finding = next(f for f in result.findings if "unique-identifier" in f.id)
        assert unique_id_finding.status == "fail"

    def test_spdx_with_cpe_external_ref(self) -> None:
        """Test SPDX SBOM with CPE externalRef satisfies unique identifier requirement."""
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
                            "referenceCategory": "SECURITY",
                            "referenceType": "cpe23Type",
                            "referenceLocator": "cpe:2.3:a:example:package:1.0.0:*:*:*:*:*:*:*",
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

        unique_id_finding = next(f for f in result.findings if "unique-identifier" in f.id)
        assert unique_id_finding.status == "pass"

    def test_spdx_with_swid_external_ref(self) -> None:
        """Test SPDX SBOM with SWID externalRef satisfies unique identifier requirement."""
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
                            "referenceType": "swid",
                            "referenceLocator": "swid:example.com+example-package@1.0.0",
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

        unique_id_finding = next(f for f in result.findings if "unique-identifier" in f.id)
        assert unique_id_finding.status == "pass"

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = NTIAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestErrorHandling:
    """Tests for error handling in the plugin."""

    def test_invalid_json(self) -> None:
        """Test handling of invalid JSON file."""
        plugin = NTIAMinimumElementsPlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert result.metadata.get("error") is True

    def test_unknown_format(self) -> None:
        """Test handling of unknown SBOM format."""
        plugin = NTIAMinimumElementsPlugin()
        sbom_data = {"some": "data", "without": "format indicators"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert "format" in result.findings[0].description.lower()

    def test_empty_components(self) -> None:
        """Test handling of SBOM with empty components list."""
        plugin = NTIAMinimumElementsPlugin()
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

        plugin = NTIAMinimumElementsPlugin()
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
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            assert finding.metadata is not None
            assert finding.metadata.get("standard") == "NTIA"
            assert finding.metadata.get("standard_version") == "2021-07"

    def test_result_includes_standard_info(self) -> None:
        """Test that assessment result includes standard reference information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = NTIAMinimumElementsPlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["standard_name"] == plugin.STANDARD_NAME
        assert result.metadata["standard_version"] == plugin.STANDARD_VERSION
        assert result.metadata["standard_url"] == plugin.STANDARD_URL
