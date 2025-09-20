"""
Unit tests for NTIA validator module.

Tests the NTIA minimum elements validation for both SPDX and CycloneDX formats.
"""

import json
import pytest
from datetime import datetime, timezone

from sbomify.apps.sboms.ntia_validator import (
    NTIAValidator,
    NTIAComplianceStatus,
    NTIAValidationError,
    NTIAValidationResult,
    validate_sbom_ntia_compliance,
)


class TestNTIAValidator:
    """Test cases for NTIA validator."""

    def setup_method(self):
        """Setup test fixtures."""
        self.validator = NTIAValidator()

    def test_spdx_compliant_sbom(self):
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
                            "referenceLocator": "pkg:pypi/example-package@1.0.0"
                        }
                    ]
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package"
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "spdx")

        assert result.is_compliant is True
        assert result.status == NTIAComplianceStatus.COMPLIANT
        assert len(result.errors) == 0

    def test_spdx_non_compliant_missing_supplier(self):
        """Test validation of SPDX SBOM missing supplier information."""
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
                            "referenceLocator": "pkg:pypi/example-package@1.0.0"
                        }
                    ]
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package"
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "spdx")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.NON_COMPLIANT
        assert len(result.errors) == 1
        assert result.errors[0].field == "supplier"
        assert "missing supplier" in result.errors[0].message.lower()

    def test_spdx_missing_all_required_fields(self):
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
            }
        }

        result = self.validator.validate_sbom(sbom_data, "spdx")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.NON_COMPLIANT
        assert len(result.errors) >= 7  # Should have multiple errors

        error_fields = [error.field for error in result.errors]
        assert "component_name" in error_fields
        assert "supplier" in error_fields
        assert "version" in error_fields
        assert "unique_id" in error_fields
        assert "dependencies" in error_fields
        assert "sbom_author" in error_fields
        assert "timestamp" in error_fields

    def test_cyclonedx_compliant_sbom(self):
        """Test validation of a compliant CycloneDX SBOM."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0"
                }
            ],
            "dependencies": [
                {
                    "ref": "pkg:pypi/example-component@1.0.0",
                    "dependsOn": []
                }
            ],
            "metadata": {
                "authors": [
                    {
                        "name": "Example Developer"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "cyclonedx")

        assert result.is_compliant is True
        assert result.status == NTIAComplianceStatus.COMPLIANT
        assert len(result.errors) == 0

    def test_cyclonedx_non_compliant_missing_version(self):
        """Test validation of CycloneDX SBOM missing version information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0"
                }
            ],
            "dependencies": [
                {
                    "ref": "pkg:pypi/example-component@1.0.0",
                    "dependsOn": []
                }
            ],
            "metadata": {
                "authors": [
                    {
                        "name": "Example Developer"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "cyclonedx")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.NON_COMPLIANT
        assert len(result.errors) == 1
        assert result.errors[0].field == "version"
        assert "missing version" in result.errors[0].message.lower()

    def test_cyclonedx_with_supplier_object(self):
        """Test CycloneDX SBOM with supplier object instead of publisher."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "supplier": {
                        "name": "Example Corp"
                    },
                    "purl": "pkg:pypi/example-component@1.0.0"
                }
            ],
            "dependencies": [
                {
                    "ref": "pkg:pypi/example-component@1.0.0",
                    "dependsOn": []
                }
            ],
            "metadata": {
                "tools": [
                    {
                        "name": "example-tool"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "cyclonedx")

        assert result.is_compliant is True
        assert result.status == NTIAComplianceStatus.COMPLIANT
        assert len(result.errors) == 0

    def test_invalid_timestamp_format(self):
        """Test validation with invalid timestamp format."""
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
                            "referenceLocator": "pkg:pypi/example-package@1.0.0"
                        }
                    ]
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package"
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "invalid-timestamp"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "spdx")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.NON_COMPLIANT
        timestamp_errors = [error for error in result.errors if error.field == "timestamp"]
        assert len(timestamp_errors) == 1
        assert "not in valid ISO-8601 format" in timestamp_errors[0].message

    def test_unsupported_format(self):
        """Test validation with unsupported SBOM format."""
        sbom_data = {"some": "data"}

        result = self.validator.validate_sbom(sbom_data, "unsupported")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.NON_COMPLIANT
        assert len(result.errors) == 1
        assert result.errors[0].field == "format"
        assert "Unsupported SBOM format" in result.errors[0].message

    def test_validation_exception_handling(self):
        """Test that validation exceptions are handled gracefully."""
        # Pass None to trigger an exception
        result = self.validator.validate_sbom(None, "spdx")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.UNKNOWN
        assert len(result.errors) == 1
        assert result.errors[0].field == "validation"

    def test_convenience_function_with_json_string(self):
        """Test the convenience function with JSON string input."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0"
                }
            ],
            "dependencies": [
                {
                    "ref": "pkg:pypi/example-component@1.0.0",
                    "dependsOn": []
                }
            ],
            "metadata": {
                "authors": [
                    {
                        "name": "Example Developer"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

        json_string = json.dumps(sbom_data)
        result = validate_sbom_ntia_compliance(json_string, "cyclonedx")

        assert result.is_compliant is True
        assert result.status == NTIAComplianceStatus.COMPLIANT

    def test_convenience_function_with_invalid_json(self):
        """Test the convenience function with invalid JSON."""
        invalid_json = "{ invalid json"

        result = validate_sbom_ntia_compliance(invalid_json, "cyclonedx")

        assert result.is_compliant is False
        assert result.status == NTIAComplianceStatus.UNKNOWN
        assert len(result.errors) == 1
        assert result.errors[0].field == "format"
        assert "Invalid JSON format" in result.errors[0].message

    def test_spdx_with_files_checksums(self):
        """Test SPDX SBOM with file checksums as unique identifiers."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    # No externalRefs, but files with checksums should satisfy unique ID requirement
                }
            ],
            "files": [
                {
                    "fileName": "./example.py",
                    "checksums": [
                        {
                            "algorithm": "SHA1",
                            "checksumValue": "da39a3ee5e6b4b0d3255bfef95601890afd80709"
                        }
                    ]
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": "SPDXRef-Package"
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "spdx")

        assert result.is_compliant is True
        assert result.status == NTIAComplianceStatus.COMPLIANT

    def test_cyclonedx_with_hashes(self):
        """Test CycloneDX SBOM with hashes as unique identifiers."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    # No purl, but hashes should satisfy unique ID requirement
                    "hashes": [
                        {
                            "alg": "SHA-256",
                            "content": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                        }
                    ]
                }
            ],
            "dependencies": [
                {
                    "ref": "example-component",
                    "dependsOn": []
                }
            ],
            "metadata": {
                "authors": [
                    {
                        "name": "Example Developer"
                    }
                ],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(sbom_data, "cyclonedx")

        assert result.is_compliant is True
        assert result.status == NTIAComplianceStatus.COMPLIANT

    def test_validation_result_properties(self):
        """Test NTIAValidationResult properties."""
        errors = [
            NTIAValidationError(field="test", message="Test error", suggestion="Fix it"),
            NTIAValidationError(field="test2", message="Test error 2", suggestion="Fix it too")
        ]

        result = NTIAValidationResult(
            is_compliant=False,
            status=NTIAComplianceStatus.NON_COMPLIANT,
            errors=errors
        )

        assert result.error_count == 2
        assert isinstance(result.checked_at, datetime)

    @pytest.mark.parametrize("status_value,expected_enum", [
        ("compliant", NTIAComplianceStatus.COMPLIANT),
        ("non_compliant", NTIAComplianceStatus.NON_COMPLIANT),
        ("unknown", NTIAComplianceStatus.UNKNOWN),
    ])
    def test_compliance_status_enum(self, status_value, expected_enum):
        """Test NTIAComplianceStatus enum values."""
        assert NTIAComplianceStatus(status_value) == expected_enum

    def test_empty_packages_and_components(self):
        """Test validation with empty packages/components lists."""
        # SPDX with empty packages
        spdx_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [],
            "relationships": [],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(spdx_data, "spdx")
        assert result.is_compliant is False

        # CycloneDX with empty components
        cyclonedx_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "dependencies": [],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z"
            }
        }

        result = self.validator.validate_sbom(cyclonedx_data, "cyclonedx")
        assert result.is_compliant is False