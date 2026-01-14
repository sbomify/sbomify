"""NTIA Minimum Elements compliance plugin (NTIA 2021 Standard).

This plugin validates SBOMs against the NTIA Minimum Elements for a Software
Bill of Materials as defined in the July 2021 report.

Standard Reference:
    - Name: NTIA Minimum Elements for a Software Bill of Materials (SBOM)
    - Version: 2021-07 (July 2021)
    - Official URL: https://www.ntia.gov/report/2021/minimum-elements-software-bill-materials-sbom

sbomify Compliance Guide:
    - Overview: https://sbomify.com/compliance/ntia-minimum-elements/
    - Schema Crosswalk: https://sbomify.com/compliance/schema-crosswalk/

The seven NTIA minimum data fields are:
    1. Supplier Name - Name of entity that creates, defines, and identifies components
    2. Component Name - Designation assigned to a unit of software by the original supplier
    3. Version - Identifier used by supplier to specify a change from previous version
    4. Unique Identifiers - Other identifiers for lookup (PURL, CPE, SWID, etc.)
    5. Dependency Relationship - Characterizes upstream component X included in software Y
    6. Author of SBOM Data - Name of entity that creates the SBOM data
    7. Timestamp - Record of date and time of SBOM data assembly

Note: CISA released an updated draft in August 2025 with additional elements
(Component Hash, License, Tool Name, Generation Context). When finalized,
that will be implemented as a separate CISAMinimumElementsPlugin.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.sdk.base import AssessmentPlugin
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import (
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.logging import getLogger

logger = getLogger(__name__)


class NTIAMinimumElementsPlugin(AssessmentPlugin):
    """NTIA Minimum Elements compliance plugin (NTIA 2021 Standard).

    This plugin checks SBOMs for compliance with the seven minimum data fields
    defined in the NTIA July 2021 report. It supports both SPDX and CycloneDX formats.

    Attributes:
        VERSION: Plugin version (semantic versioning).
        STANDARD_NAME: Official name of the standard being checked.
        STANDARD_VERSION: Version identifier of the standard (YYYY-MM format).
        STANDARD_URL: Official URL to the standard documentation.

    Example:
        >>> plugin = NTIAMinimumElementsPlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(f"Compliant: {result.summary.fail_count == 0}")
    """

    VERSION = "1.0.0"
    STANDARD_NAME = "NTIA Minimum Elements for a Software Bill of Materials (SBOM)"
    STANDARD_VERSION = "2021-07"  # July 2021 report
    STANDARD_URL = "https://www.ntia.gov/report/2021/minimum-elements-software-bill-materials-sbom"

    # Finding IDs for each NTIA element (prefixed with standard version)
    FINDING_IDS = {
        "supplier_name": "ntia-2021:supplier-name",
        "component_name": "ntia-2021:component-name",
        "version": "ntia-2021:version",
        "unique_identifiers": "ntia-2021:unique-identifiers",
        "dependency_relationship": "ntia-2021:dependency-relationship",
        "sbom_author": "ntia-2021:sbom-author",
        "timestamp": "ntia-2021:timestamp",
    }

    # Human-readable titles for findings
    FINDING_TITLES = {
        "supplier_name": "Supplier Name",
        "component_name": "Component Name",
        "version": "Component Version",
        "unique_identifiers": "Unique Identifiers",
        "dependency_relationship": "Dependency Relationship",
        "sbom_author": "SBOM Author",
        "timestamp": "Timestamp",
    }

    # Descriptions for each element per NTIA standard
    FINDING_DESCRIPTIONS = {
        "supplier_name": "Name of entity that creates, defines, and identifies components",
        "component_name": "Designation assigned to a unit of software by the original supplier",
        "version": "Identifier used by supplier to specify a change from previous version",
        "unique_identifiers": "Other identifiers for component lookup (PURL, CPE, SWID, etc.)",
        "dependency_relationship": "Characterizes the relationship that an upstream component is included in software",
        "sbom_author": "Name of entity that creates the SBOM data for this component",
        "timestamp": "Record of date and time of SBOM data assembly",
    }

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name, version, and category.
        """
        return PluginMetadata(
            name="ntia-minimum-elements-2021",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        """Run NTIA Minimum Elements compliance check against the SBOM.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.

        Returns:
            AssessmentResult with findings for each of the 7 NTIA elements.
        """
        logger.info(f"[NTIA-2021] Starting compliance check for SBOM {sbom_id}")

        # Read and parse the SBOM
        try:
            sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"[NTIA-2021] Failed to parse SBOM JSON: {e}")
            return self._create_error_result(f"Invalid JSON format: {e}")
        except Exception as e:
            logger.error(f"[NTIA-2021] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Detect format and validate
        sbom_format = self._detect_format(sbom_data)
        if sbom_format == "spdx":
            findings = self._validate_spdx(sbom_data)
        elif sbom_format == "cyclonedx":
            findings = self._validate_cyclonedx(sbom_data)
        else:
            logger.warning(f"[NTIA-2021] Unknown SBOM format for {sbom_id}")
            return self._create_error_result("Unable to detect SBOM format (expected SPDX or CycloneDX)")

        # Calculate summary
        pass_count = sum(1 for f in findings if f.status == "pass")
        fail_count = sum(1 for f in findings if f.status == "fail")

        summary = AssessmentSummary(
            total_findings=len(findings),
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=0,
            error_count=0,
        )

        logger.info(f"[NTIA-2021] Completed compliance check for SBOM {sbom_id}: {pass_count} pass, {fail_count} fail")

        return AssessmentResult(
            plugin_name="ntia-minimum-elements-2021",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
                "sbom_format": sbom_format,
            },
        )

    def _detect_format(self, sbom_data: dict[str, Any]) -> str:
        """Detect SBOM format from the data.

        Args:
            sbom_data: Parsed SBOM dictionary.

        Returns:
            Format string: "spdx", "cyclonedx", or "unknown".
        """
        if "spdxVersion" in sbom_data:
            return "spdx"
        elif "bomFormat" in sbom_data and sbom_data.get("bomFormat", "").lower() == "cyclonedx":
            return "cyclonedx"
        elif "specVersion" in sbom_data and "components" in sbom_data:
            # CycloneDX without explicit bomFormat
            return "cyclonedx"
        return "unknown"

    def _validate_spdx(self, data: dict[str, Any]) -> list[Finding]:
        """Validate SPDX format SBOM against NTIA minimum elements.

        Args:
            data: Parsed SPDX SBOM dictionary.

        Returns:
            List of findings for each NTIA element.
        """
        findings: list[Finding] = []
        packages = data.get("packages", [])
        relationships = data.get("relationships", [])
        creation_info = data.get("creationInfo", {})

        # Track element-level failures across all packages
        supplier_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        unique_id_failures: list[str] = []

        # Check each package for required elements
        for i, package in enumerate(packages):
            package_name = package.get("name", f"Package {i + 1}")

            # 1. Supplier name
            if not package.get("supplier"):
                supplier_failures.append(package_name)

            # 2. Component name
            if not package.get("name"):
                component_name_failures.append(f"Package at index {i}")

            # 3. Version
            if not package.get("versionInfo"):
                version_failures.append(package_name)

            # 4. Unique identifiers (PURL, CPE, SWID via externalRefs)
            # Only accept externalRefs with valid identifier types
            # Note: checksums are for "Component Hash" (RECOMMENDED), not "Unique Identifiers" (MINIMUM)
            valid_identifier_types = {"purl", "cpe22Type", "cpe23Type", "swid"}
            has_unique_id = package.get("purl") or any(
                ref.get("referenceType") in valid_identifier_types for ref in package.get("externalRefs", [])
            )
            if not has_unique_id:
                unique_id_failures.append(package_name)

        # Create findings for per-package elements
        findings.append(
            self._create_finding(
                "supplier_name",
                status="fail" if supplier_failures else "pass",
                details=f"Missing for: {', '.join(supplier_failures)}" if supplier_failures else None,
                remediation="Add supplier field to packages. Use 'NOASSERTION' if supplier is unknown.",
            )
        )

        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all packages.",
            )
        )

        findings.append(
            self._create_finding(
                "version",
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add versionInfo field to packages. Use 'NOASSERTION' if version is unknown.",
            )
        )

        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="fail" if unique_id_failures else "pass",
                details=f"Missing for: {', '.join(unique_id_failures)}" if unique_id_failures else None,
                remediation="Add externalRefs with PURL, CPE, or other identifiers.",
            )
        )

        # 5. Dependency relationships (document-level)
        has_dependencies = any(
            rel.get("relationshipType", "").upper() in ["DEPENDS_ON", "CONTAINS"] for rel in relationships
        )
        findings.append(
            self._create_finding(
                "dependency_relationship",
                status="pass" if has_dependencies else "fail",
                details=None if has_dependencies else "No DEPENDS_ON or CONTAINS relationships found",
                remediation="Add relationships section with DEPENDS_ON or CONTAINS relationships.",
            )
        )

        # 6. SBOM author (document-level)
        creators = creation_info.get("creators", [])
        findings.append(
            self._create_finding(
                "sbom_author",
                status="pass" if creators else "fail",
                details=None if creators else "No creators found in creationInfo",
                remediation="Add creators field in creationInfo section with tool or person information.",
            )
        )

        # 7. Timestamp (document-level)
        timestamp = creation_info.get("created")
        timestamp_valid = self._validate_timestamp(timestamp)
        findings.append(
            self._create_finding(
                "timestamp",
                status="pass" if timestamp_valid else "fail",
                details=None
                if timestamp_valid
                else ("Missing timestamp" if not timestamp else "Invalid ISO-8601 format"),
                remediation="Add created field in creationInfo with ISO-8601 timestamp.",
            )
        )

        return findings

    def _validate_cyclonedx(self, data: dict[str, Any]) -> list[Finding]:
        """Validate CycloneDX format SBOM against NTIA minimum elements.

        Args:
            data: Parsed CycloneDX SBOM dictionary.

        Returns:
            List of findings for each NTIA element.
        """
        findings: list[Finding] = []
        components = data.get("components", [])
        dependencies = data.get("dependencies", [])
        metadata = data.get("metadata", {})

        # Track element-level failures across all components
        supplier_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        unique_id_failures: list[str] = []

        # Check each component for required elements
        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i + 1}")

            # 1. Supplier name (publisher or supplier.name)
            supplier = component.get("publisher") or component.get("supplier", {}).get("name")
            if not supplier:
                supplier_failures.append(component_name)

            # 2. Component name
            if not component.get("name"):
                component_name_failures.append(f"Component at index {i}")

            # 3. Version
            if not component.get("version"):
                version_failures.append(component_name)

            # 4. Unique identifiers (PURL, CPE, SWID)
            # Note: hashes are for "Component Hash" (RECOMMENDED), not "Unique Identifiers" (MINIMUM)
            has_unique_id = component.get("purl") or component.get("cpe") or component.get("swid")
            if not has_unique_id:
                unique_id_failures.append(component_name)

        # Create findings for per-component elements
        findings.append(
            self._create_finding(
                "supplier_name",
                status="fail" if supplier_failures else "pass",
                details=f"Missing for: {', '.join(supplier_failures)}" if supplier_failures else None,
                remediation="Add publisher field or supplier.name to components.",
            )
        )

        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all components.",
            )
        )

        findings.append(
            self._create_finding(
                "version",
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add version field to components.",
            )
        )

        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="fail" if unique_id_failures else "pass",
                details=f"Missing for: {', '.join(unique_id_failures)}" if unique_id_failures else None,
                remediation="Add purl, cpe, or swid to components.",
            )
        )

        # 5. Dependency relationships (document-level)
        findings.append(
            self._create_finding(
                "dependency_relationship",
                status="pass" if dependencies else "fail",
                details=None if dependencies else "No dependencies section found",
                remediation="Add dependencies section with dependency relationships.",
            )
        )

        # 6. SBOM author (document-level)
        # NTIA "Author of SBOM Data" = "the entity that creates the SBOM"
        # Tools are software, not entities - only check metadata.authors
        authors = metadata.get("authors", [])
        has_author = bool(authors)
        findings.append(
            self._create_finding(
                "sbom_author",
                status="pass" if has_author else "fail",
                details=None if has_author else "No authors found in metadata",
                remediation="Add authors field in metadata section with organization or person information.",
            )
        )

        # 7. Timestamp (document-level)
        timestamp = metadata.get("timestamp")
        timestamp_valid = self._validate_timestamp(timestamp)
        findings.append(
            self._create_finding(
                "timestamp",
                status="pass" if timestamp_valid else "fail",
                details=None
                if timestamp_valid
                else ("Missing timestamp" if not timestamp else "Invalid ISO-8601 format"),
                remediation="Add timestamp field in metadata with ISO-8601 format.",
            )
        )

        return findings

    def _validate_timestamp(self, timestamp: str | None) -> bool:
        """Validate that a timestamp is in valid ISO-8601 format.

        Args:
            timestamp: Timestamp string to validate.

        Returns:
            True if valid ISO-8601 format, False otherwise.
        """
        if not timestamp:
            return False
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return True
        except (ValueError, TypeError):
            return False

    def _create_finding(
        self,
        element: str,
        status: str,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """Create a finding for an NTIA element.

        Args:
            element: Element key (e.g., "supplier_name").
            status: Status string ("pass" or "fail").
            details: Additional details about the finding.
            remediation: Suggested fix for failures.

        Returns:
            Finding object for the element.
        """
        description = self.FINDING_DESCRIPTIONS[element]
        if details:
            description = f"{description}. {details}"

        return Finding(
            id=self.FINDING_IDS[element],
            title=self.FINDING_TITLES[element],
            description=description,
            status=status,
            severity="info" if status == "pass" else "medium",
            remediation=remediation if status == "fail" else None,
            metadata={
                "standard": "NTIA",
                "standard_version": self.STANDARD_VERSION,
                "element": element,
            },
        )

    def _create_error_result(self, error_message: str) -> AssessmentResult:
        """Create an error result when assessment cannot be completed.

        Args:
            error_message: Description of the error.

        Returns:
            AssessmentResult with error finding.
        """
        finding = Finding(
            id="ntia-2021:error",
            title="Assessment Error",
            description=error_message,
            status="error",
            severity="high",
        )

        summary = AssessmentSummary(
            total_findings=1,
            pass_count=0,
            fail_count=0,
            warning_count=0,
            error_count=1,
        )

        return AssessmentResult(
            plugin_name="ntia-minimum-elements-2021",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
                "error": True,
            },
        )
