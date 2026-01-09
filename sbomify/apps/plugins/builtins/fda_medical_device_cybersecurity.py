"""FDA Medical Device Cybersecurity SBOM compliance plugin.

This plugin validates SBOMs against the FDA guidance "Cybersecurity in Medical
Devices: Quality System Considerations and Content of Premarket Submissions"
(June 2025).

Standard Reference:
    - Name: FDA Cybersecurity in Medical Devices
    - Version: 2025-06 (June 2025)
    - URL: https://www.fda.gov/media/119933/download

The FDA guidance requires SBOMs to include:
    1. NTIA Minimum Elements (7 elements from NTIA 2021 report)
    2. FDA-specific Additional Elements (Section V.A.4.b):
        - Software Support Level: Whether software is actively maintained,
          no longer maintained, or abandoned
        - End-of-Support Date: The component's end-of-support date

CLE (Common Lifecycle Enumeration) data is expected to be injected by the
sbomify GitHub Action and validated by this plugin.

CLE Format Support:
    - CycloneDX: Component properties with cdx:cle namespace
        - cdx:cle:supportStatus (active, deprecated, eol, abandoned, unknown)
        - cdx:cle:endOfSupport (ISO-8601 date)
    - SPDX 2.3: Native validUntilDate field + annotations
        - validUntilDate for end-of-support
        - Annotation with cle:supportStatus=<status>
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


# Valid CLE support status values
CLE_SUPPORT_STATUS_VALUES = {"active", "deprecated", "eol", "abandoned", "unknown"}


class FDAMedicalDevicePlugin(AssessmentPlugin):
    """FDA Medical Device Cybersecurity SBOM compliance plugin.

    This plugin checks SBOMs for compliance with FDA guidance Section V.A.4.b,
    which requires NTIA minimum elements plus lifecycle information (support
    status and end-of-support dates) for each software component.

    The plugin validates CLE (Common Lifecycle Enumeration) data that should
    be injected by the sbomify GitHub Action.

    Attributes:
        VERSION: Plugin version (semantic versioning).
        STANDARD_NAME: Official name of the standard being checked.
        STANDARD_VERSION: Version identifier of the standard (YYYY-MM format).
        STANDARD_URL: Official URL to the standard documentation.

    Example:
        >>> plugin = FDAMedicalDevicePlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(f"Compliant: {result.summary.fail_count == 0}")
    """

    VERSION = "1.0.0"
    STANDARD_NAME = "FDA Cybersecurity in Medical Devices"
    STANDARD_VERSION = "2025-06"  # June 2025 guidance
    STANDARD_URL = "https://www.fda.gov/media/119933/download"

    # Finding IDs for each element (prefixed with standard version)
    # NTIA elements (7)
    NTIA_FINDING_IDS = {
        "supplier_name": "fda-2025:ntia:supplier-name",
        "component_name": "fda-2025:ntia:component-name",
        "version": "fda-2025:ntia:version",
        "unique_identifiers": "fda-2025:ntia:unique-identifiers",
        "dependency_relationship": "fda-2025:ntia:dependency-relationship",
        "sbom_author": "fda-2025:ntia:sbom-author",
        "timestamp": "fda-2025:ntia:timestamp",
    }

    # FDA-specific CLE elements (2)
    FDA_FINDING_IDS = {
        "support_status": "fda-2025:cle:support-status",
        "end_of_support": "fda-2025:cle:end-of-support",
    }

    # Human-readable titles for all findings
    FINDING_TITLES = {
        # NTIA elements
        "supplier_name": "Supplier Name (NTIA)",
        "component_name": "Component Name (NTIA)",
        "version": "Component Version (NTIA)",
        "unique_identifiers": "Unique Identifiers (NTIA)",
        "dependency_relationship": "Dependency Relationship (NTIA)",
        "sbom_author": "SBOM Author (NTIA)",
        "timestamp": "Timestamp (NTIA)",
        # FDA-specific CLE elements
        "support_status": "Software Support Status (CLE)",
        "end_of_support": "End-of-Support Date (CLE)",
    }

    # Descriptions for each element
    FINDING_DESCRIPTIONS = {
        # NTIA elements
        "supplier_name": "Name of entity that creates, defines, and identifies components",
        "component_name": "Designation assigned to a unit of software by the original supplier",
        "version": "Identifier used by supplier to specify a change from previous version",
        "unique_identifiers": "Other identifiers for component lookup (PURL, CPE, SWID, etc.)",
        "dependency_relationship": (
            "Characterizes the relationship that an upstream component is included in software"
        ),
        "sbom_author": "Name of entity that creates the SBOM data for this component",
        "timestamp": "Record of date and time of SBOM data assembly",
        # FDA-specific CLE elements
        "support_status": (
            "Software support level indicating whether the software is actively maintained, "
            "no longer maintained, or abandoned (FDA V.A.4.b)"
        ),
        "end_of_support": (
            "The software component's end-of-support date when security patches will no "
            "longer be provided (FDA V.A.4.b)"
        ),
    }

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name, version, and category.
        """
        return PluginMetadata(
            name="fda-medical-device-2025",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        """Run FDA Medical Device Cybersecurity compliance check against the SBOM.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.

        Returns:
            AssessmentResult with findings for all 9 elements (7 NTIA + 2 CLE).
        """
        logger.info(f"[FDA-2025] Starting compliance check for SBOM {sbom_id}")

        # Read and parse the SBOM
        try:
            sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"[FDA-2025] Failed to parse SBOM JSON: {e}")
            return self._create_error_result(f"Invalid JSON format: {e}")
        except Exception as e:
            logger.error(f"[FDA-2025] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Detect format and validate
        sbom_format = self._detect_format(sbom_data)
        if sbom_format == "spdx":
            findings = self._validate_spdx(sbom_data)
        elif sbom_format == "cyclonedx":
            findings = self._validate_cyclonedx(sbom_data)
        else:
            logger.warning(f"[FDA-2025] Unknown SBOM format for {sbom_id}")
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

        logger.info(f"[FDA-2025] Completed compliance check for SBOM {sbom_id}: {pass_count} pass, {fail_count} fail")

        return AssessmentResult(
            plugin_name="fda-medical-device-2025",
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
        """Validate SPDX format SBOM against FDA requirements.

        Args:
            data: Parsed SPDX SBOM dictionary.

        Returns:
            List of findings for each element (7 NTIA + 2 CLE).
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
        support_status_failures: list[str] = []
        end_of_support_failures: list[str] = []

        # Check each package for required elements
        for i, package in enumerate(packages):
            package_name = package.get("name", f"Package {i + 1}")

            # === NTIA Elements ===

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

            # === FDA CLE Elements ===

            # 8. Support status (from annotations)
            has_support_status = self._spdx_has_support_status(package, data)
            if not has_support_status:
                support_status_failures.append(package_name)

            # 9. End of support date (validUntilDate)
            if not package.get("validUntilDate"):
                end_of_support_failures.append(package_name)

        # Create findings for per-package NTIA elements
        findings.append(
            self._create_finding(
                "supplier_name",
                is_ntia=True,
                status="fail" if supplier_failures else "pass",
                details=f"Missing for: {', '.join(supplier_failures)}" if supplier_failures else None,
                remediation="Add supplier field to packages. Use 'NOASSERTION' if supplier is unknown.",
            )
        )

        findings.append(
            self._create_finding(
                "component_name",
                is_ntia=True,
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all packages.",
            )
        )

        findings.append(
            self._create_finding(
                "version",
                is_ntia=True,
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add versionInfo field to packages. Use 'NOASSERTION' if version is unknown.",
            )
        )

        findings.append(
            self._create_finding(
                "unique_identifiers",
                is_ntia=True,
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
                is_ntia=True,
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
                is_ntia=True,
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
                is_ntia=True,
                status="pass" if timestamp_valid else "fail",
                details=None
                if timestamp_valid
                else ("Missing timestamp" if not timestamp else "Invalid ISO-8601 format"),
                remediation="Add created field in creationInfo with ISO-8601 timestamp.",
            )
        )

        # Create findings for FDA CLE elements
        findings.append(
            self._create_finding(
                "support_status",
                is_ntia=False,
                status="fail" if support_status_failures else "pass",
                details=f"Missing for: {', '.join(support_status_failures)}" if support_status_failures else None,
                remediation=(
                    "Add CLE support status via annotation with comment 'cle:supportStatus=<status>' "
                    "where status is one of: active, deprecated, eol, abandoned, unknown. "
                    "Use sbomify GitHub Action to inject CLE data."
                ),
            )
        )

        findings.append(
            self._create_finding(
                "end_of_support",
                is_ntia=False,
                status="fail" if end_of_support_failures else "pass",
                details=f"Missing for: {', '.join(end_of_support_failures)}" if end_of_support_failures else None,
                remediation=(
                    "Add validUntilDate field to packages with ISO-8601 date. "
                    "Use sbomify GitHub Action to inject CLE data."
                ),
            )
        )

        return findings

    def _spdx_has_support_status(self, package: dict[str, Any], data: dict[str, Any]) -> bool:
        """Check if an SPDX package has CLE support status annotation.

        Support status can be provided via:
        - Package annotation with comment containing 'cle:supportStatus=<status>'
        - Document-level annotation referencing the package SPDXID

        Args:
            package: SPDX package dictionary.
            data: Full SPDX document dictionary.

        Returns:
            True if valid support status annotation found.
        """
        package_spdxid = package.get("SPDXID", "")

        # Check package-level annotations
        for annotation in package.get("annotations", []):
            if self._parse_spdx_support_status_annotation(annotation):
                return True

        # Check document-level annotations that reference this package
        for annotation in data.get("annotations", []):
            if annotation.get("annotationType") == "OTHER":
                # Check if annotation references this package
                referenced_id = annotation.get("spdxElementId", "")
                if referenced_id == package_spdxid:
                    if self._parse_spdx_support_status_annotation(annotation):
                        return True

        return False

    def _parse_spdx_support_status_annotation(self, annotation: dict[str, Any]) -> bool:
        """Parse an SPDX annotation for CLE support status.

        Args:
            annotation: SPDX annotation dictionary.

        Returns:
            True if valid cle:supportStatus found in annotation comment.
        """
        if annotation.get("annotationType") != "OTHER":
            return False

        comment = annotation.get("comment", "")
        # Look for cle:supportStatus=<value>
        if "cle:supportStatus=" in comment:
            # Extract the status value
            for part in comment.split():
                if part.startswith("cle:supportStatus="):
                    status = part.split("=", 1)[1].lower().strip()
                    if status in CLE_SUPPORT_STATUS_VALUES:
                        return True
        return False

    def _validate_cyclonedx(self, data: dict[str, Any]) -> list[Finding]:
        """Validate CycloneDX format SBOM against FDA requirements.

        Args:
            data: Parsed CycloneDX SBOM dictionary.

        Returns:
            List of findings for each element (7 NTIA + 2 CLE).
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
        support_status_failures: list[str] = []
        end_of_support_failures: list[str] = []

        # Check each component for required elements
        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i + 1}")

            # === NTIA Elements ===

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

            # === FDA CLE Elements ===

            # 8. Support status (from properties cdx:cle:supportStatus)
            has_support_status = self._cyclonedx_has_cle_property(component, "cdx:cle:supportStatus")
            if not has_support_status:
                support_status_failures.append(component_name)

            # 9. End of support date (from properties cdx:cle:endOfSupport)
            has_end_of_support = self._cyclonedx_has_cle_property(component, "cdx:cle:endOfSupport")
            if not has_end_of_support:
                end_of_support_failures.append(component_name)

        # Create findings for per-component NTIA elements
        findings.append(
            self._create_finding(
                "supplier_name",
                is_ntia=True,
                status="fail" if supplier_failures else "pass",
                details=f"Missing for: {', '.join(supplier_failures)}" if supplier_failures else None,
                remediation="Add publisher field or supplier.name to components.",
            )
        )

        findings.append(
            self._create_finding(
                "component_name",
                is_ntia=True,
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all components.",
            )
        )

        findings.append(
            self._create_finding(
                "version",
                is_ntia=True,
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add version field to components.",
            )
        )

        findings.append(
            self._create_finding(
                "unique_identifiers",
                is_ntia=True,
                status="fail" if unique_id_failures else "pass",
                details=f"Missing for: {', '.join(unique_id_failures)}" if unique_id_failures else None,
                remediation="Add purl, cpe, or swid to components.",
            )
        )

        # 5. Dependency relationships (document-level)
        # Check for at least one valid dependency entry with a ref
        has_valid_dependencies = any(dep.get("ref") for dep in dependencies)
        findings.append(
            self._create_finding(
                "dependency_relationship",
                is_ntia=True,
                status="pass" if has_valid_dependencies else "fail",
                details=None if has_valid_dependencies else "No valid dependency relationships found",
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
                is_ntia=True,
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
                is_ntia=True,
                status="pass" if timestamp_valid else "fail",
                details=None
                if timestamp_valid
                else ("Missing timestamp" if not timestamp else "Invalid ISO-8601 format"),
                remediation="Add timestamp field in metadata with ISO-8601 format.",
            )
        )

        # Create findings for FDA CLE elements
        findings.append(
            self._create_finding(
                "support_status",
                is_ntia=False,
                status="fail" if support_status_failures else "pass",
                details=f"Missing for: {', '.join(support_status_failures)}" if support_status_failures else None,
                remediation=(
                    "Add CLE support status via component property 'cdx:cle:supportStatus' "
                    "with value: active, deprecated, eol, abandoned, or unknown. "
                    "Use sbomify GitHub Action to inject CLE data."
                ),
            )
        )

        findings.append(
            self._create_finding(
                "end_of_support",
                is_ntia=False,
                status="fail" if end_of_support_failures else "pass",
                details=f"Missing for: {', '.join(end_of_support_failures)}" if end_of_support_failures else None,
                remediation=(
                    "Add CLE end-of-support date via component property 'cdx:cle:endOfSupport' "
                    "with ISO-8601 date value. Use sbomify GitHub Action to inject CLE data."
                ),
            )
        )

        return findings

    def _cyclonedx_has_cle_property(self, component: dict[str, Any], property_name: str) -> bool:
        """Check if a CycloneDX component has a specific CLE property.

        Args:
            component: CycloneDX component dictionary.
            property_name: The property name to look for (e.g., "cdx:cle:supportStatus").

        Returns:
            True if property found with a non-empty value.
        """
        properties = component.get("properties", [])
        for prop in properties:
            if prop.get("name") == property_name:
                value = prop.get("value", "").strip()
                if value:
                    # For supportStatus, validate the value
                    if property_name == "cdx:cle:supportStatus":
                        return value.lower() in CLE_SUPPORT_STATUS_VALUES
                    return True
        return False

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
        is_ntia: bool,
        status: str,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """Create a finding for an FDA/NTIA element.

        Args:
            element: Element key (e.g., "supplier_name", "support_status").
            is_ntia: True if this is an NTIA element, False if FDA-specific.
            status: Status string ("pass" or "fail").
            details: Additional details about the finding.
            remediation: Suggested fix for failures.

        Returns:
            Finding object for the element.
        """
        description = self.FINDING_DESCRIPTIONS[element]
        if details:
            description = f"{description}. {details}"

        finding_id = self.NTIA_FINDING_IDS.get(element) or self.FDA_FINDING_IDS.get(element)

        return Finding(
            id=finding_id,
            title=self.FINDING_TITLES[element],
            description=description,
            status=status,
            severity="info" if status == "pass" else "medium",
            remediation=remediation if status == "fail" else None,
            metadata={
                "standard": "FDA",
                "standard_version": self.STANDARD_VERSION,
                "element": element,
                "element_source": "NTIA" if is_ntia else "FDA-CLE",
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
            id="fda-2025:error",
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
            plugin_name="fda-medical-device-2025",
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
