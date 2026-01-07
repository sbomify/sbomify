"""EU Cyber Resilience Act (CRA) compliance plugin.

This plugin validates SBOMs against the EU Cyber Resilience Act (Regulation 2024/2847)
requirements for software bill of materials as defined in Annex I Part II and Annex II.

Standard Reference:
    - Name: EU Cyber Resilience Act (CRA) - Regulation (EU) 2024/2847
    - Version: 2024/2847 (23 October 2024)
    - URL: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202402847

The CRA SBOM requirements validated by this plugin:

    Component-Level Requirements (from Annex I Part II point 1):
        1. Component Name - identify components
        2. Component Version - identify components
        3. Supplier/Manufacturer - manufacturer identification (Annex II point 1)
        4. Unique Identifiers - for vulnerability lookup (PURL, CPE)

    Document-Level Requirements:
        5. SBOM Author - SBOM in technical documentation (Annex VII point 2.b)
        6. Timestamp - machine-readable format metadata
        7. Dependencies - "at least top-level dependencies" (Annex I Part II point 1)
        8. Machine-Readable Format - "commonly used and machine-readable format"

    CRA-Specific Requirements:
        9. Vulnerability Contact - single point of contact for vulnerability reporting (Annex II point 2)
        10. Support Period - end-date of support period (Annex II point 7)

Key CRA Quote (Annex I Part II point 1):
    "identify and document vulnerabilities and components contained in products with
    digital elements, including by drawing up a software bill of materials in a commonly
    used and machine-readable format covering at the very least the top-level
    dependencies of the products"
"""

import json
import re
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


class CRACompliancePlugin(AssessmentPlugin):
    """EU Cyber Resilience Act (CRA) SBOM compliance plugin.

    This plugin checks SBOMs for compliance with the CRA requirements for
    software bills of materials as specified in Regulation (EU) 2024/2847.
    It supports both SPDX and CycloneDX formats.

    The CRA is EU law that applies from 11 December 2027, with some provisions
    applying earlier (vulnerability reporting from 11 September 2026).

    Attributes:
        VERSION: Plugin version (semantic versioning).
        STANDARD_NAME: Official name of the standard being checked.
        STANDARD_VERSION: Version identifier of the regulation.
        STANDARD_URL: Official URL to the regulation.
        FORMAT_SPDX: Constant for SPDX format detection.
        FORMAT_CYCLONEDX: Constant for CycloneDX format detection.
        FORMAT_UNKNOWN: Constant for unknown format detection.

    Example:
        >>> plugin = CRACompliancePlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(f"Compliant: {result.summary.fail_count == 0}")
    """

    VERSION = "1.0.0"
    STANDARD_NAME = "EU Cyber Resilience Act (CRA) - Regulation (EU) 2024/2847"
    STANDARD_VERSION = "2024/2847"
    STANDARD_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202402847"

    # SBOM format constants
    FORMAT_SPDX = "spdx"
    FORMAT_CYCLONEDX = "cyclonedx"
    FORMAT_UNKNOWN = "unknown"

    # Finding IDs for each CRA element (prefixed with standard version)
    FINDING_IDS = {
        "component_name": "cra-2024:component-name",
        "component_version": "cra-2024:component-version",
        "supplier": "cra-2024:supplier",
        "unique_identifiers": "cra-2024:unique-identifiers",
        "sbom_author": "cra-2024:sbom-author",
        "timestamp": "cra-2024:timestamp",
        "dependencies": "cra-2024:dependencies",
        "machine_readable": "cra-2024:machine-readable-format",
        "vulnerability_contact": "cra-2024:vulnerability-contact",
        "support_period": "cra-2024:support-period",
    }

    # Human-readable titles for findings
    FINDING_TITLES = {
        "component_name": "Component Name",
        "component_version": "Component Version",
        "supplier": "Supplier/Manufacturer",
        "unique_identifiers": "Unique Identifiers",
        "sbom_author": "SBOM Author",
        "timestamp": "Timestamp",
        "dependencies": "Top-Level Dependencies",
        "machine_readable": "Machine-Readable Format",
        "vulnerability_contact": "Vulnerability Reporting Contact",
        "support_period": "Support Period End Date",
    }

    # Descriptions for each element per CRA requirements
    FINDING_DESCRIPTIONS = {
        "component_name": (
            "Name assigned to identify the software component (Annex I Part II point 1 - identify components)"
        ),
        "component_version": (
            "Version identifier for the software component (Annex I Part II point 1 - identify components)"
        ),
        "supplier": (
            "Name of the entity that creates, defines, and identifies components "
            "(Annex II point 1 - manufacturer identification)"
        ),
        "unique_identifiers": (
            "Identifiers for vulnerability lookup such as PURL or CPE "
            "(Annex I Part II point 1 - for vulnerability tracking)"
        ),
        "sbom_author": (
            "Name of entity that creates the SBOM data (Annex VII point 2.b - SBOM in technical documentation)"
        ),
        "timestamp": (
            "Date and time of SBOM creation in machine-readable format "
            "(Annex I Part II point 1 - machine-readable format)"
        ),
        "dependencies": (
            "Documentation of at least top-level dependencies "
            "(Annex I Part II point 1 - 'at the very least the top-level dependencies')"
        ),
        "machine_readable": (
            "SBOM in commonly used and machine-readable format (CycloneDX or SPDX) "
            "(Annex I Part II point 1 - 'commonly used and machine-readable format')"
        ),
        "vulnerability_contact": (
            "Single point of contact for vulnerability reporting (Annex II point 2 - vulnerability reporting contact)"
        ),
        "support_period": (
            "End-date of the support period for security updates (Annex II point 7 - support period end date)"
        ),
    }

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name, version, and category.
        """
        return PluginMetadata(
            name="cra-compliance-2024",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        """Run CRA compliance check against the SBOM.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.

        Returns:
            AssessmentResult with findings for each of the 10 CRA elements.
        """
        logger.info(f"[CRA-2024] Starting compliance check for SBOM {sbom_id}")

        # Read and parse the SBOM
        try:
            sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"[CRA-2024] Failed to parse SBOM JSON: {e}")
            return self._create_error_result(f"Invalid JSON format: {e}")
        except Exception as e:
            logger.error(f"[CRA-2024] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Detect format and validate
        sbom_format = self._detect_format(sbom_data)
        if sbom_format == self.FORMAT_SPDX:
            findings = self._validate_spdx(sbom_data)
        elif sbom_format == self.FORMAT_CYCLONEDX:
            findings = self._validate_cyclonedx(sbom_data)
        else:
            logger.warning(f"[CRA-2024] Unknown SBOM format for {sbom_id}")
            return self._create_error_result(
                "Unable to detect SBOM format (expected SPDX or CycloneDX). "
                "CRA requires 'commonly used and machine-readable format'."
            )

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

        logger.info(f"[CRA-2024] Completed compliance check for SBOM {sbom_id}: {pass_count} pass, {fail_count} fail")

        return AssessmentResult(
            plugin_name="cra-compliance-2024",
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
            Format string: FORMAT_SPDX, FORMAT_CYCLONEDX, or FORMAT_UNKNOWN.
        """
        if "spdxVersion" in sbom_data:
            return self.FORMAT_SPDX
        elif "bomFormat" in sbom_data and sbom_data.get("bomFormat", "").lower() == "cyclonedx":
            return self.FORMAT_CYCLONEDX
        elif "specVersion" in sbom_data and "components" in sbom_data:
            # CycloneDX without explicit bomFormat
            return self.FORMAT_CYCLONEDX
        return self.FORMAT_UNKNOWN

    def _validate_spdx(self, data: dict[str, Any]) -> list[Finding]:
        """Validate SPDX format SBOM against CRA requirements.

        Args:
            data: Parsed SPDX SBOM dictionary.

        Returns:
            List of findings for each CRA element.
        """
        findings: list[Finding] = []
        packages = data.get("packages", [])
        relationships = data.get("relationships", [])
        creation_info = data.get("creationInfo", {})

        # Track element-level failures across all packages
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        supplier_failures: list[str] = []
        identifier_failures: list[str] = []

        # Check each package for required elements
        for i, package in enumerate(packages):
            package_name = package.get("name", f"Package {i + 1}")

            # 1. Component name
            if not package.get("name"):
                component_name_failures.append(f"Package at index {i}")

            # 2. Component version
            if not package.get("versionInfo"):
                version_failures.append(package_name)

            # 3. Supplier/Manufacturer
            if not package.get("supplier"):
                supplier_failures.append(package_name)

            # 4. Unique identifiers (PURL, externalRefs)
            has_identifier = bool(package.get("externalRefs"))
            if not has_identifier:
                identifier_failures.append(package_name)

        # Create findings for per-package elements

        # 1. Component Name
        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if component_name_failures else "pass",
                details=self._format_failure_details(component_name_failures) if component_name_failures else None,
                remediation="Add name field to all packages.",
            )
        )

        # 2. Component Version
        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=self._format_failure_details(version_failures) if version_failures else None,
                remediation="Add versionInfo field to packages.",
            )
        )

        # 3. Supplier/Manufacturer
        findings.append(
            self._create_finding(
                "supplier",
                status="fail" if supplier_failures else "pass",
                details=self._format_failure_details(supplier_failures) if supplier_failures else None,
                remediation="Add supplier field to packages (e.g., 'Organization: <name>').",
            )
        )

        # 4. Unique Identifiers
        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="fail" if identifier_failures else "pass",
                details=self._format_failure_details(identifier_failures) if identifier_failures else None,
                remediation="Add externalRefs with PURL or CPE identifiers for vulnerability tracking.",
            )
        )

        # 5. SBOM Author (document-level)
        creators = creation_info.get("creators", [])
        findings.append(
            self._create_finding(
                "sbom_author",
                status="pass" if creators else "fail",
                details=None if creators else "No creators found in creationInfo",
                remediation="Add creators field in creationInfo with tool or organization information.",
            )
        )

        # 6. Timestamp (document-level)
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

        # 7. Dependencies (at least top-level)
        has_dependencies = any(
            rel.get("relationshipType", "").upper() in ["DEPENDS_ON", "CONTAINS", "DEPENDENCY_OF"]
            for rel in relationships
        )
        findings.append(
            self._create_finding(
                "dependencies",
                status="pass" if has_dependencies else "fail",
                details=None if has_dependencies else "No dependency relationships found",
                remediation=(
                    "Add relationships section with DEPENDS_ON or CONTAINS relationships "
                    "to document at least top-level dependencies."
                ),
            )
        )

        # 8. Machine-Readable Format (always pass for valid SPDX)
        findings.append(
            self._create_finding(
                "machine_readable",
                status="pass",
                details="SPDX format detected - commonly used and machine-readable",
                remediation=None,
            )
        )

        # 9. Vulnerability Contact
        has_vuln_contact = self._spdx_has_vulnerability_contact(data, creation_info)
        findings.append(
            self._create_finding(
                "vulnerability_contact",
                status="pass" if has_vuln_contact else "fail",
                details=None if has_vuln_contact else "No vulnerability reporting contact found",
                remediation=(
                    "Add vulnerability contact via annotation with 'cra:vulnerabilityContact=<url>' "
                    "or include contact email in creators field."
                ),
            )
        )

        # 10. Support Period
        has_support_period = self._spdx_has_support_period(data, packages)
        findings.append(
            self._create_finding(
                "support_period",
                status="pass" if has_support_period else "fail",
                details=None if has_support_period else "No support period end date found",
                remediation=(
                    "Add support period via annotation with 'cra:supportPeriodEnd=<date>' "
                    "or use validUntilDate field on packages."
                ),
            )
        )

        return findings

    def _spdx_has_vulnerability_contact(self, data: dict[str, Any], creation_info: dict[str, Any]) -> bool:
        """Check if SPDX document has vulnerability contact information.

        Args:
            data: Full SPDX document dictionary.
            creation_info: Creation info section.

        Returns:
            True if vulnerability contact found.
        """
        # Email regex pattern for more robust detection
        email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

        # Check creators for contact information (email or URL)
        creators = creation_info.get("creators", [])
        for creator in creators:
            # Check for email in creator string using regex
            if ("Organization:" in creator or "Person:" in creator) and email_pattern.search(creator):
                return True

        # Check document-level annotations for vulnerability contact
        for annotation in data.get("annotations", []):
            if annotation.get("annotationType") == "OTHER":
                comment = annotation.get("comment", "")
                if "cra:vulnerabilityContact=" in comment or "securityContact=" in comment.lower():
                    return True

        # Check externalDocumentRefs for security contact
        for ext_ref in data.get("externalDocumentRefs", []):
            ref_type = ext_ref.get("externalDocumentId", "").lower()
            if "security" in ref_type or "vulnerability" in ref_type:
                return True

        return False

    def _spdx_has_support_period(self, data: dict[str, Any], packages: list[dict[str, Any]]) -> bool:
        """Check if SPDX document has support period information.

        Args:
            data: Full SPDX document dictionary.
            packages: List of packages.

        Returns:
            True if support period information found.
        """
        # Check packages for validUntilDate
        for package in packages:
            if package.get("validUntilDate"):
                return True

        # Check document-level annotations for support period
        for annotation in data.get("annotations", []):
            if annotation.get("annotationType") == "OTHER":
                comment = annotation.get("comment", "")
                if "cra:supportPeriodEnd=" in comment or "supportPeriod" in comment.lower():
                    return True

        return False

    def _validate_cyclonedx(self, data: dict[str, Any]) -> list[Finding]:
        """Validate CycloneDX format SBOM against CRA requirements.

        Args:
            data: Parsed CycloneDX SBOM dictionary.

        Returns:
            List of findings for each CRA element.
        """
        findings: list[Finding] = []
        components = data.get("components", [])
        dependencies = data.get("dependencies", [])
        metadata = data.get("metadata", {})

        # Track element-level failures across all components
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        supplier_failures: list[str] = []
        identifier_failures: list[str] = []

        # Check each component for required elements
        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i + 1}")

            # 1. Component name
            if not component.get("name"):
                component_name_failures.append(f"Component at index {i}")

            # 2. Component version
            if not component.get("version"):
                version_failures.append(component_name)

            # 3. Supplier/Manufacturer (publisher or supplier.name)
            supplier = component.get("publisher") or component.get("supplier", {}).get("name")
            if not supplier:
                supplier_failures.append(component_name)

            # 4. Unique identifiers (purl, cpe, swid)
            has_identifier = bool(component.get("purl") or component.get("cpe") or component.get("swid"))
            if not has_identifier:
                identifier_failures.append(component_name)

        # Create findings for per-component elements

        # 1. Component Name
        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if component_name_failures else "pass",
                details=self._format_failure_details(component_name_failures) if component_name_failures else None,
                remediation="Add name field to all components.",
            )
        )

        # 2. Component Version
        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=self._format_failure_details(version_failures) if version_failures else None,
                remediation="Add version field to components.",
            )
        )

        # 3. Supplier/Manufacturer
        findings.append(
            self._create_finding(
                "supplier",
                status="fail" if supplier_failures else "pass",
                details=self._format_failure_details(supplier_failures) if supplier_failures else None,
                remediation="Add publisher field or supplier.name to components.",
            )
        )

        # 4. Unique Identifiers
        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="fail" if identifier_failures else "pass",
                details=self._format_failure_details(identifier_failures) if identifier_failures else None,
                remediation="Add purl, cpe, or swid identifiers for vulnerability tracking.",
            )
        )

        # 5. SBOM Author (document-level)
        authors = metadata.get("authors", [])
        tools = metadata.get("tools", [])
        manufacture = metadata.get("manufacture", {})
        has_author = bool(authors or tools or manufacture.get("name"))
        findings.append(
            self._create_finding(
                "sbom_author",
                status="pass" if has_author else "fail",
                details=None if has_author else "No authors, tools, or manufacture info found in metadata",
                remediation="Add authors, tools, or manufacture field in metadata section.",
            )
        )

        # 6. Timestamp (document-level)
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

        # 7. Dependencies (at least top-level)
        has_valid_dependencies = any(dep.get("ref") for dep in dependencies)
        findings.append(
            self._create_finding(
                "dependencies",
                status="pass" if has_valid_dependencies else "fail",
                details=None if has_valid_dependencies else "No valid dependency relationships found",
                remediation=(
                    "Add dependencies section to document at least top-level dependencies "
                    "as required by CRA Annex I Part II."
                ),
            )
        )

        # 8. Machine-Readable Format (always pass for valid CycloneDX)
        findings.append(
            self._create_finding(
                "machine_readable",
                status="pass",
                details="CycloneDX format detected - commonly used and machine-readable",
                remediation=None,
            )
        )

        # 9. Vulnerability Contact
        has_vuln_contact = self._cyclonedx_has_vulnerability_contact(metadata, data)
        findings.append(
            self._create_finding(
                "vulnerability_contact",
                status="pass" if has_vuln_contact else "fail",
                details=None if has_vuln_contact else "No vulnerability reporting contact found",
                remediation=(
                    "Add vulnerability contact via metadata.manufacture.contact, "
                    "metadata.supplier.contact, or externalReferences with type 'issue-tracker'."
                ),
            )
        )

        # 10. Support Period
        has_support_period = self._cyclonedx_has_support_period(metadata)
        findings.append(
            self._create_finding(
                "support_period",
                status="pass" if has_support_period else "fail",
                details=None if has_support_period else "No support period end date found",
                remediation=(
                    "Add support period via metadata.properties with name "
                    "'cra:supportPeriodEnd' or 'cdx:support:endDate'."
                ),
            )
        )

        return findings

    def _cyclonedx_has_vulnerability_contact(self, metadata: dict[str, Any], data: dict[str, Any]) -> bool:
        """Check if CycloneDX document has vulnerability contact information.

        Args:
            metadata: CycloneDX metadata dictionary.
            data: Full CycloneDX document dictionary.

        Returns:
            True if vulnerability contact found.
        """
        # Check manufacture contact
        manufacture = metadata.get("manufacture", {})
        if manufacture.get("contact"):
            return True

        # Check supplier contact
        supplier = metadata.get("supplier", {})
        if supplier.get("contact"):
            return True

        # Check metadata properties for vulnerability contact
        properties = metadata.get("properties", [])
        for prop in properties:
            prop_name = prop.get("name", "").lower()
            if "vulnerability" in prop_name and "contact" in prop_name:
                if prop.get("value"):
                    return True
            if prop_name == "cra:vulnerabilitycontact":
                if prop.get("value"):
                    return True

        # Check externalReferences for issue-tracker or security contact
        ext_refs = data.get("externalReferences", [])
        for ref in ext_refs:
            ref_type = ref.get("type", "").lower()
            if ref_type in ["issue-tracker", "security-contact", "support"]:
                if ref.get("url"):
                    return True

        return False

    def _cyclonedx_has_support_period(self, metadata: dict[str, Any]) -> bool:
        """Check if CycloneDX metadata has support period information.

        Args:
            metadata: CycloneDX metadata dictionary.

        Returns:
            True if support period information found.
        """
        properties = metadata.get("properties", [])
        for prop in properties:
            prop_name = prop.get("name", "").lower()
            if "support" in prop_name and ("end" in prop_name or "period" in prop_name):
                if prop.get("value"):
                    return True
            if prop_name in [
                "cra:supportperiodend",
                "cdx:support:enddate",
                "cdx:supportperiod:enddate",
            ]:
                if prop.get("value"):
                    return True

        # Check lifecycles in metadata (CycloneDX 1.5+)
        lifecycles = metadata.get("lifecycles", [])
        for lifecycle in lifecycles:
            if lifecycle.get("phase") == "end-of-life":
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

    def _format_failure_details(self, failures: list[str]) -> str:
        """Format a list of failures into a details string.

        Args:
            failures: List of failed item names.

        Returns:
            Formatted string with failure details. The UI template handles
            collapsing long lists.
        """
        return f"Missing for: {', '.join(failures)}"

    def _create_finding(
        self,
        element: str,
        status: str,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """Create a finding for a CRA element.

        Args:
            element: Element key (e.g., "component_name").
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
                "standard": "CRA",
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
            id="cra-2024:error",
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
            plugin_name="cra-compliance-2024",
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
