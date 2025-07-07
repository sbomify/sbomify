"""
NTIA Minimum Elements Validator for SBOM compliance checking.

This module provides validation logic for checking Software Bill of Materials (SBOM)
compliance against the NTIA minimum elements as defined in the NTIA report.

The seven NTIA minimum elements are:
1. Supplier name
2. Component name
3. Version of the component
4. Other unique identifiers
5. Dependency relationship
6. Author of SBOM data
7. Timestamp

Supports both SPDX and CycloneDX formats.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NTIAComplianceStatus(str, Enum):
    """NTIA compliance status enumeration."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"


class NTIAValidationError(BaseModel):
    """Model for NTIA validation errors."""

    field: str = Field(..., description="The NTIA field that failed validation")
    message: str = Field(..., description="Human-readable error message")
    suggestion: str = Field(..., description="Suggestion for fixing the issue")


class NTIAValidationResult(BaseModel):
    """Model for NTIA validation results."""

    is_compliant: bool = Field(..., description="Whether the SBOM is NTIA compliant")
    status: NTIAComplianceStatus = Field(..., description="Overall compliance status")
    errors: List[NTIAValidationError] = Field(default_factory=list, description="List of validation errors")
    checked_at: datetime = Field(default_factory=datetime.now, description="When the validation was performed")

    @property
    def error_count(self) -> int:
        """Return the number of validation errors."""
        return len(self.errors)


class NTIAValidator:
    """NTIA minimum elements validator for SBOM compliance checking."""

    def __init__(self):
        """Initialize the NTIA validator."""
        self.logger = logging.getLogger(__name__)

    def validate_sbom(self, sbom_data: Dict[str, Any], sbom_format: str) -> NTIAValidationResult:
        """
        Validate an SBOM against NTIA minimum elements.

        Args:
            sbom_data: The parsed SBOM data as a dictionary
            sbom_format: The SBOM format ('spdx' or 'cyclonedx')

        Returns:
            NTIAValidationResult with compliance status and any errors
        """
        self.logger.info(f"Starting NTIA validation for {sbom_format.upper()} SBOM")

        try:
            if sbom_format.lower() == "spdx":
                return self._validate_spdx(sbom_data)
            elif sbom_format.lower() == "cyclonedx":
                return self._validate_cyclonedx(sbom_data)
            else:
                error = NTIAValidationError(
                    field="format",
                    message=f"Unsupported SBOM format: {sbom_format}",
                    suggestion="Please use SPDX or CycloneDX format",
                )
                return NTIAValidationResult(
                    is_compliant=False, status=NTIAComplianceStatus.NON_COMPLIANT, errors=[error]
                )
        except Exception as e:
            self.logger.error(f"Error during NTIA validation: {str(e)}", exc_info=True)
            error = NTIAValidationError(
                field="validation",
                message=f"Validation failed due to error: {str(e)}",
                suggestion="Please check if the SBOM is properly formatted and try again",
            )
            return NTIAValidationResult(is_compliant=False, status=NTIAComplianceStatus.UNKNOWN, errors=[error])

    def _validate_spdx(self, data: Dict[str, Any]) -> NTIAValidationResult:
        """Validate SPDX format SBOM against NTIA minimum elements."""
        errors = []
        packages = data.get("packages", [])
        relationships = data.get("relationships", [])
        creation_info = data.get("creationInfo", {})

        self.logger.debug(f"Validating SPDX SBOM with {len(packages)} packages and {len(relationships)} relationships")

        # Check each package for required elements
        for i, package in enumerate(packages):
            package_name = package.get("name", f"Package {i+1}")

            # 1. Supplier name
            if not package.get("supplier"):
                errors.append(
                    NTIAValidationError(
                        field="supplier",
                        message=f"Package '{package_name}' is missing supplier information",
                        suggestion="Add supplier field to the package. Use 'NOASSERTION' if supplier is unknown.",
                    )
                )

            # 2. Component name
            if not package.get("name"):
                errors.append(
                    NTIAValidationError(
                        field="component_name",
                        message=f"Package at index {i} is missing component name",
                        suggestion="Add a name field to the package.",
                    )
                )

            # 3. Version
            if not package.get("versionInfo"):
                errors.append(
                    NTIAValidationError(
                        field="version",
                        message=f"Package '{package_name}' is missing version information",
                        suggestion="Add versionInfo field to the package. Use 'NOASSERTION' if version is unknown.",
                    )
                )

            # 4. Unique identifiers
            has_unique_id = (
                package.get("externalRefs")
                or package.get("purl")
                or any(file.get("checksums") for file in data.get("files", []))
            )
            if not has_unique_id:
                errors.append(
                    NTIAValidationError(
                        field="unique_id",
                        message=f"Package '{package_name}' is missing unique identifiers",
                        suggestion="Add externalRefs with PURL, CPE, or other identifiers, or include file checksums.",
                    )
                )

        # 5. Dependency relationships
        has_dependencies = any(
            rel.get("relationshipType", "").lower() in ["depends_on", "contains", "depends-on"] for rel in relationships
        )
        if not has_dependencies:
            errors.append(
                NTIAValidationError(
                    field="dependencies",
                    message="No dependency relationships found in SPDX document",
                    suggestion="Add relationships section with DEPENDS_ON or CONTAINS relationships between packages.",
                )
            )

        # 6. SBOM author
        creators = creation_info.get("creators", [])
        if not creators:
            errors.append(
                NTIAValidationError(
                    field="sbom_author",
                    message="SBOM author/creator information is missing",
                    suggestion="Add creators field in creationInfo section with tool or person information.",
                )
            )

        # 7. Timestamp
        created_timestamp = creation_info.get("created")
        if not created_timestamp:
            errors.append(
                NTIAValidationError(
                    field="timestamp",
                    message="SBOM creation timestamp is missing",
                    suggestion="Add created field in creationInfo section with ISO-8601 timestamp.",
                )
            )
        else:
            try:
                # Validate timestamp format
                datetime.fromisoformat(created_timestamp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                errors.append(
                    NTIAValidationError(
                        field="timestamp",
                        message="SBOM creation timestamp is not in valid ISO-8601 format",
                        suggestion="Use ISO-8601 timestamp format (e.g., '2023-01-01T00:00:00Z').",
                    )
                )

        is_compliant = len(errors) == 0
        status = NTIAComplianceStatus.COMPLIANT if is_compliant else NTIAComplianceStatus.NON_COMPLIANT

        self.logger.info(f"SPDX NTIA validation completed. Compliant: {is_compliant}, Errors: {len(errors)}")

        return NTIAValidationResult(is_compliant=is_compliant, status=status, errors=errors)

    def _validate_cyclonedx(self, data: Dict[str, Any]) -> NTIAValidationResult:
        """Validate CycloneDX format SBOM against NTIA minimum elements."""
        errors = []
        components = data.get("components", [])
        dependencies = data.get("dependencies", [])
        metadata = data.get("metadata", {})

        self.logger.debug(
            f"Validating CycloneDX SBOM with {len(components)} components and {len(dependencies)} dependencies"
        )

        # Check each component for required elements
        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i+1}")

            # 1. Supplier name
            supplier = component.get("publisher") or component.get("supplier", {}).get("name")
            if not supplier:
                errors.append(
                    NTIAValidationError(
                        field="supplier",
                        message=f"Component '{component_name}' is missing supplier information",
                        suggestion="Add publisher field or supplier.name to the component.",
                    )
                )

            # 2. Component name
            if not component.get("name"):
                errors.append(
                    NTIAValidationError(
                        field="component_name",
                        message=f"Component at index {i} is missing component name",
                        suggestion="Add a name field to the component.",
                    )
                )

            # 3. Version
            if not component.get("version"):
                errors.append(
                    NTIAValidationError(
                        field="version",
                        message=f"Component '{component_name}' is missing version information",
                        suggestion="Add version field to the component.",
                    )
                )

            # 4. Unique identifiers
            has_unique_id = (
                component.get("purl") or component.get("cpe") or component.get("swid") or component.get("hashes")
            )
            if not has_unique_id:
                errors.append(
                    NTIAValidationError(
                        field="unique_id",
                        message=f"Component '{component_name}' is missing unique identifiers",
                        suggestion="Add purl, cpe, swid, or hashes to the component.",
                    )
                )

        # 5. Dependency relationships
        if not dependencies:
            errors.append(
                NTIAValidationError(
                    field="dependencies",
                    message="No dependency graph found in dependencies section",
                    suggestion="Add dependencies section with dependency relationships between components.",
                )
            )

        # 6. SBOM author
        authors = metadata.get("authors", [])
        tools = metadata.get("tools", [])
        if not authors and not tools:
            errors.append(
                NTIAValidationError(
                    field="sbom_author",
                    message="SBOM author information is missing",
                    suggestion="Add authors or tools field in metadata section.",
                )
            )

        # 7. Timestamp
        timestamp = metadata.get("timestamp")
        if not timestamp:
            errors.append(
                NTIAValidationError(
                    field="timestamp",
                    message="SBOM creation timestamp is missing",
                    suggestion="Add timestamp field in metadata section with ISO-8601 timestamp.",
                )
            )
        else:
            try:
                # Validate timestamp format
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                errors.append(
                    NTIAValidationError(
                        field="timestamp",
                        message="SBOM creation timestamp is not in valid ISO-8601 format",
                        suggestion="Use ISO-8601 timestamp format (e.g., '2023-01-01T00:00:00Z').",
                    )
                )

        is_compliant = len(errors) == 0
        status = NTIAComplianceStatus.COMPLIANT if is_compliant else NTIAComplianceStatus.NON_COMPLIANT

        self.logger.info(f"CycloneDX NTIA validation completed. Compliant: {is_compliant}, Errors: {len(errors)}")

        return NTIAValidationResult(is_compliant=is_compliant, status=status, errors=errors)


def validate_sbom_ntia_compliance(sbom_data: Union[str, Dict[str, Any]], sbom_format: str) -> NTIAValidationResult:
    """
    Convenience function to validate SBOM NTIA compliance.

    Args:
        sbom_data: SBOM data as JSON string or dictionary
        sbom_format: SBOM format ('spdx' or 'cyclonedx')

    Returns:
        NTIAValidationResult with compliance status and errors
    """
    if isinstance(sbom_data, str):
        try:
            sbom_data = json.loads(sbom_data)
        except json.JSONDecodeError as e:
            error = NTIAValidationError(
                field="format",
                message=f"Invalid JSON format: {str(e)}",
                suggestion="Please provide valid JSON formatted SBOM data",
            )
            return NTIAValidationResult(is_compliant=False, status=NTIAComplianceStatus.UNKNOWN, errors=[error])

    validator = NTIAValidator()
    return validator.validate_sbom(sbom_data, sbom_format)
