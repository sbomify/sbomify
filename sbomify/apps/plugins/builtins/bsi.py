"""BSI TR-03183-2 SBOM compliance plugin.

This plugin validates SBOMs against the German Federal Office for Information
Security (BSI) Technical Guideline TR-03183-2 v2.1.0 requirements for Software
Bill of Materials.

Standard Reference:
    - Name: BSI TR-03183-2: Cyber Resilience Requirements - Part 2: SBOM
    - Version: 2.1.0 (2025-08-20)
    - Official URL: https://bsi.bund.de/dok/TR-03183-en

sbomify Compliance Guide:
    - Overview: https://sbomify.com/compliance/eu-cra/
    - Schema Crosswalk: https://sbomify.com/compliance/schema-crosswalk/

BSI TR-03183-2 Requirements:

    Format Requirements (§4):
        - MUST be JSON or XML format
        - MUST use CycloneDX v1.6+ OR SPDX v3.0.1+

    Required SBOM-level fields (§5.2.1):
        1. Creator of the SBOM - Email address OR URL
        2. Timestamp - Date and time of SBOM compilation

    Required component-level fields (§5.2.2):
        1. Component creator - Email address OR URL
        2. Component name
        3. Component version (or file modification date RFC 3339)
        4. Filename of the component (actual filename, not path)
        5. Dependencies on other components (with completeness indicator)
        6. Distribution licences (SPDX identifiers/expressions)
        7. Hash value of deployable component (SHA-512)
        8. Executable property (executable/non-executable)
        9. Archive property (archive/no archive)
        10. Structured property (structured/unstructured)

    Additional fields - MUST if exists (§5.2.3, §5.2.4):
        - SBOM-URI
        - Source code URI
        - URI of deployable form
        - Other unique identifiers (CPE, purl)
        - Original licences

    Critical Requirements:
        - SBOM MUST NOT contain vulnerability information (§3.1)
        - Licences MUST use SPDX identifiers (§6.1)

BSI CycloneDX Property Taxonomy:
    https://github.com/BSI-Bund/tr-03183-cyclonedx-property-taxonomy
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging import version as pkg_version

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

# Minimum required format versions per BSI TR-03183-2 v2.1.0 §4
MIN_CYCLONEDX_VERSION = "1.6"
MIN_SPDX_VERSION = "3.0.1"

# BSI property taxonomy prefix
BSI_PROPERTY_PREFIX = "bsi:component:"

# Email pattern for creator validation
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def _is_valid_email(value: str) -> bool:
    """Check if value is a valid email address."""
    return bool(EMAIL_PATTERN.match(value))


def _is_valid_url(value: str) -> bool:
    """Check if value is a valid URL."""
    return bool(URL_PATTERN.match(value))


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string into a tuple of integers for comparison."""
    # Remove common prefixes
    version_str = version_str.lstrip("v").lstrip("V")
    # Handle SPDX format "SPDX-X.Y.Z"
    if version_str.upper().startswith("SPDX-"):
        version_str = version_str[5:]
    # Split and convert to integers
    parts = []
    for part in version_str.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _version_gte(version: str, min_version: str) -> bool:
    """Check if version is greater than or equal to min_version."""
    try:
        return pkg_version.parse(version) >= pkg_version.parse(min_version)
    except Exception:
        # Fallback to simple tuple comparison
        return _parse_version(version) >= _parse_version(min_version)


class BSICompliancePlugin(AssessmentPlugin):
    """BSI TR-03183-2 SBOM compliance plugin.

    This plugin checks SBOMs for compliance with the BSI Technical Guideline
    TR-03183-2 v2.1.0 requirements for software bills of materials. It supports
    both SPDX 3.0.1+ and CycloneDX 1.6+ formats.

    BSI TR-03183-2 is the authoritative technical interpretation of the EU Cyber
    Resilience Act (CRA) SBOM requirements from Germany's Federal Office for
    Information Security.

    Attributes:
        VERSION: Plugin version (semantic versioning).
        STANDARD_NAME: Official name of the standard being checked.
        STANDARD_VERSION: Version identifier of the guideline.
        STANDARD_URL: Official URL to the guideline.
    """

    VERSION = "1.0.0"
    STANDARD_NAME = "BSI TR-03183-2: Cyber Resilience Requirements - Part 2: SBOM"
    STANDARD_VERSION = "2.1.0"
    STANDARD_URL = "https://bsi.bund.de/dok/TR-03183-en"

    # SBOM format constants
    FORMAT_SPDX = "spdx"
    FORMAT_CYCLONEDX = "cyclonedx"
    FORMAT_UNKNOWN = "unknown"

    # Finding IDs for each BSI element (prefixed with standard)
    FINDING_IDS = {
        # Format requirement
        "sbom_format": "bsi-tr03183:sbom-format",
        # Required SBOM-level (§5.2.1)
        "sbom_creator": "bsi-tr03183:sbom-creator",
        "timestamp": "bsi-tr03183:timestamp",
        # Required component-level (§5.2.2)
        "component_creator": "bsi-tr03183:component-creator",
        "component_name": "bsi-tr03183:component-name",
        "component_version": "bsi-tr03183:component-version",
        "filename": "bsi-tr03183:filename",
        "dependencies": "bsi-tr03183:dependencies",
        "distribution_licences": "bsi-tr03183:distribution-licences",
        "hash_value": "bsi-tr03183:hash-value",
        "executable_property": "bsi-tr03183:executable-property",
        "archive_property": "bsi-tr03183:archive-property",
        "structured_property": "bsi-tr03183:structured-property",
        # Additional MUST if exists (§5.2.3, §5.2.4)
        "unique_identifiers": "bsi-tr03183:unique-identifiers",
        # Critical restrictions
        "no_vulnerabilities": "bsi-tr03183:no-vulnerabilities",
        # Attestation cross-check (requires one of attestation plugins)
        "attestation_check": "bsi-tr03183:attestation-check",
    }

    # Human-readable titles for findings
    FINDING_TITLES = {
        "sbom_format": "SBOM Format Version",
        "sbom_creator": "SBOM Creator",
        "timestamp": "Timestamp",
        "component_creator": "Component Creator",
        "component_name": "Component Name",
        "component_version": "Component Version",
        "filename": "Component Filename",
        "dependencies": "Dependencies with Completeness",
        "distribution_licences": "Distribution Licences",
        "hash_value": "Hash Value (SHA-512)",
        "executable_property": "Executable Property",
        "archive_property": "Archive Property",
        "structured_property": "Structured Property",
        "unique_identifiers": "Unique Identifiers",
        "no_vulnerabilities": "No Embedded Vulnerabilities",
        "attestation_check": "Digital Signature Attestation",
    }

    # Descriptions for each element per BSI requirements
    FINDING_DESCRIPTIONS = {
        "sbom_format": (
            f"SBOM MUST be in JSON or XML format using CycloneDX v{MIN_CYCLONEDX_VERSION}+ "
            f"or SPDX v{MIN_SPDX_VERSION}+ (BSI TR-03183-2 §4)"
        ),
        "sbom_creator": ("Email address or URL of the entity that created the SBOM (BSI TR-03183-2 §5.2.1 Table 2)"),
        "timestamp": ("Date and time of the SBOM data compilation in ISO-8601 format (BSI TR-03183-2 §5.2.1 Table 2)"),
        "component_creator": (
            "Email address or URL of the entity that created and maintains the component "
            "(BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "component_name": (
            "Name assigned to the component by the component creator, or actual filename if none "
            "(BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "component_version": (
            "Version identifier used by the creator, or file modification date per RFC 3339 "
            "(BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "filename": ("The actual filename of the component (not its file system path) (BSI TR-03183-2 §5.2.2 Table 3)"),
        "dependencies": (
            "Enumeration of all direct dependencies with completeness indicator "
            "(complete/incomplete/unknown) (BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "distribution_licences": (
            "Distribution licence(s) using SPDX identifiers or expressions (BSI TR-03183-2 §5.2.2 Table 3, §6.1)"
        ),
        "hash_value": (
            "Cryptographically secure SHA-512 hash of the deployable component (BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "executable_property": (
            "Indicates whether the component is executable (executable/non-executable) (BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "archive_property": (
            "Indicates whether the component is an archive (archive/no archive) (BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "structured_property": (
            "Indicates whether the component is structured (structured/unstructured) (BSI TR-03183-2 §5.2.2 Table 3)"
        ),
        "unique_identifiers": (
            "Other identifiers for vulnerability lookup (CPE, purl) - MUST be provided if they exist "
            "(BSI TR-03183-2 §5.2.4 Table 5)"
        ),
        "no_vulnerabilities": (
            "SBOM MUST NOT contain vulnerability information. Use CSAF or VEX documents instead "
            "(BSI TR-03183-2 §3.1, §8.1.14)"
        ),
        "attestation_check": (
            "SBOM integrity MUST be verified via digital signature. Run one of the attestation plugins "
            "to verify SBOM provenance and integrity (BSI TR-03183-2 §3.2, CRA Article 10)"
        ),
    }

    # Required attestation plugins - at least one must pass for BSI compliance
    REQUIRED_ATTESTATION_PLUGINS = ["github-attestation"]

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name, version, and category.
        """
        return PluginMetadata(
            name="bsi-tr03183-v2.1-compliance",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
    ) -> AssessmentResult:
        """Run BSI TR-03183-2 compliance check against the SBOM.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Dependency status provided by the orchestrator,
                used for attestation requirement check.

        Returns:
            AssessmentResult with findings for each BSI element.
        """
        logger.info(f"[BSI-TR03183] Starting compliance check for SBOM {sbom_id}")

        # Read and parse the SBOM
        try:
            sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"[BSI-TR03183] Failed to parse SBOM JSON: {e}")
            return self._create_error_result(f"Invalid JSON format: {e}")
        except Exception as e:
            logger.error(f"[BSI-TR03183] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Detect format and version
        sbom_format, format_version = self._detect_format_and_version(sbom_data)

        if sbom_format == self.FORMAT_UNKNOWN:
            logger.warning(f"[BSI-TR03183] Unknown SBOM format for {sbom_id}")
            return self._create_error_result(
                "Unable to detect SBOM format (expected SPDX 3.0.1+ or CycloneDX 1.6+). "
                "BSI TR-03183-2 requires these specific format versions."
            )

        # Validate format version and collect findings
        findings: list[Finding] = []

        # Check format version requirement
        format_finding = self._check_format_version(sbom_format, format_version)
        findings.append(format_finding)

        # If format version fails, we still validate other fields but note the SBOM is non-compliant
        if sbom_format == self.FORMAT_SPDX:
            findings.extend(self._validate_spdx(sbom_data, format_version))
        else:  # CycloneDX
            findings.extend(self._validate_cyclonedx(sbom_data, format_version))

        # Check attestation requirement using orchestrator-provided dependency status
        findings.append(self._check_attestation_requirement(dependency_status))

        # Calculate summary
        pass_count = sum(1 for f in findings if f.status == "pass")
        fail_count = sum(1 for f in findings if f.status == "fail")
        warning_count = sum(1 for f in findings if f.status == "warning")

        summary = AssessmentSummary(
            total_findings=len(findings),
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            error_count=0,
        )

        logger.info(
            f"[BSI-TR03183] Completed compliance check for SBOM {sbom_id}: "
            f"{pass_count} pass, {fail_count} fail, {warning_count} warning"
        )

        return AssessmentResult(
            plugin_name="bsi-tr03183-v2.1-compliance",
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
                "sbom_format_version": format_version,
            },
        )

    def _detect_format_and_version(self, sbom_data: dict[str, Any]) -> tuple[str, str]:
        """Detect SBOM format and version from the data.

        Args:
            sbom_data: Parsed SBOM dictionary.

        Returns:
            Tuple of (format_string, version_string).
        """
        # Check for SPDX
        if "spdxVersion" in sbom_data:
            version = sbom_data.get("spdxVersion", "")
            # SPDX version format: "SPDX-X.Y" or "SPDX-X.Y.Z"
            if version.upper().startswith("SPDX-"):
                version = version[5:]
            return self.FORMAT_SPDX, version

        # Check for CycloneDX
        if "bomFormat" in sbom_data and sbom_data.get("bomFormat", "").lower() == "cyclonedx":
            return self.FORMAT_CYCLONEDX, sbom_data.get("specVersion", "")
        elif "specVersion" in sbom_data and "components" in sbom_data:
            # CycloneDX without explicit bomFormat
            return self.FORMAT_CYCLONEDX, sbom_data.get("specVersion", "")

        return self.FORMAT_UNKNOWN, ""

    def _check_format_version(self, sbom_format: str, version: str) -> Finding:
        """Check if SBOM format version meets BSI requirements.

        Args:
            sbom_format: The detected format (spdx or cyclonedx).
            version: The format version string.

        Returns:
            Finding for format version compliance.
        """
        if sbom_format == self.FORMAT_SPDX:
            min_version = MIN_SPDX_VERSION
            format_name = "SPDX"
        else:
            min_version = MIN_CYCLONEDX_VERSION
            format_name = "CycloneDX"

        is_valid = _version_gte(version, min_version)

        if is_valid:
            return self._create_finding(
                "sbom_format",
                status="pass",
                details=f"{format_name} {version} meets minimum requirement of {min_version}",
            )
        else:
            return self._create_finding(
                "sbom_format",
                status="fail",
                details=f"{format_name} {version} does not meet minimum requirement of {min_version}",
                remediation=(
                    f"BSI TR-03183-2 §4 requires {format_name} version {min_version} or higher. "
                    f"Please regenerate your SBOM using a compliant format version."
                ),
            )

    def _validate_cyclonedx(self, data: dict[str, Any], format_version: str) -> list[Finding]:
        """Validate CycloneDX format SBOM against BSI requirements.

        Args:
            data: Parsed CycloneDX SBOM dictionary.
            format_version: The CycloneDX version.

        Returns:
            List of findings for each BSI element.
        """
        findings: list[Finding] = []
        components = data.get("components", [])
        dependencies = data.get("dependencies", [])
        compositions = data.get("compositions", [])
        metadata = data.get("metadata", {})

        # === SBOM-level required fields (§5.2.1) ===

        # 1. SBOM Creator (email or URL)
        sbom_creator = self._get_cyclonedx_sbom_creator(metadata)
        findings.append(
            self._create_finding(
                "sbom_creator",
                status="pass" if sbom_creator else "fail",
                details=None if sbom_creator else "No valid email address or URL found for SBOM creator",
                remediation=(
                    "Add manufacturer.contact[].email or manufacturer.url in metadata section "
                    "with a valid email address or URL."
                ),
            )
        )

        # 2. Timestamp
        timestamp = metadata.get("timestamp")
        timestamp_valid = self._validate_timestamp(timestamp)
        timestamp_details = None
        if not timestamp_valid:
            timestamp_details = "Missing timestamp" if not timestamp else "Invalid ISO-8601 format"
        findings.append(
            self._create_finding(
                "timestamp",
                status="pass" if timestamp_valid else "fail",
                details=timestamp_details,
                remediation="Add timestamp in ISO-8601 format (e.g., 2024-01-15T12:00:00Z).",
            )
        )

        # === Component-level required fields (§5.2.2) ===
        # Track failures across all components
        name_failures: list[str] = []
        version_failures: list[str] = []
        creator_failures: list[str] = []
        filename_failures: list[str] = []
        licence_failures: list[str] = []
        hash_failures: list[str] = []  # No hash at all
        hash_warnings: list[str] = []  # Has hash but not SHA-512
        executable_failures: list[str] = []
        archive_failures: list[str] = []
        structured_failures: list[str] = []
        identifier_warnings: list[str] = []

        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i + 1}")

            # 1. Component name
            if not component.get("name"):
                name_failures.append(f"Component at index {i}")

            # 2. Component version
            if not component.get("version"):
                version_failures.append(component_name)

            # 3. Component creator (email or URL)
            creator = self._get_cyclonedx_component_creator(component)
            if not creator:
                creator_failures.append(component_name)

            # 4. Filename (BSI property)
            filename = self._get_bsi_property(component, "filename")
            if not filename:
                filename_failures.append(component_name)

            # 5. Distribution licences (SPDX identifiers)
            has_valid_licence = self._has_valid_cyclonedx_licence(component)
            if not has_valid_licence:
                licence_failures.append(component_name)

            # 6. Hash value (SHA-512 preferred, other hashes acceptable with warning)
            hash_status = self._check_component_hash(component)
            if hash_status == "none":
                hash_failures.append(component_name)
            elif hash_status == "other":
                hash_warnings.append(component_name)

            # 7. Executable property
            executable = self._get_bsi_property(component, "executable")
            if executable not in ("executable", "non-executable"):
                executable_failures.append(component_name)

            # 8. Archive property
            archive = self._get_bsi_property(component, "archive")
            if archive not in ("archive", "no archive"):
                archive_failures.append(component_name)

            # 9. Structured property
            structured = self._get_bsi_property(component, "structured")
            if structured not in ("structured", "unstructured"):
                structured_failures.append(component_name)

            # Additional: Unique identifiers (MUST if exists)
            # We check if purl/cpe exist elsewhere but not in the component
            has_identifier = bool(component.get("purl") or component.get("cpe") or component.get("swid"))
            if not has_identifier:
                identifier_warnings.append(component_name)

        # Create findings for component-level fields

        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if name_failures else "pass",
                details=self._format_failure_details(name_failures) if name_failures else None,
                remediation="Add name field to all components.",
            )
        )

        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=self._format_failure_details(version_failures) if version_failures else None,
                remediation="Add version field to components (or file modification date per RFC 3339).",
            )
        )

        findings.append(
            self._create_finding(
                "component_creator",
                status="fail" if creator_failures else "pass",
                details=self._format_failure_details(creator_failures) if creator_failures else None,
                remediation="Add manufacturer.contact[].email or manufacturer.url to each component.",
            )
        )

        findings.append(
            self._create_finding(
                "filename",
                status="fail" if filename_failures else "pass",
                details=self._format_failure_details(filename_failures) if filename_failures else None,
                remediation=(
                    f'Add property with name="{BSI_PROPERTY_PREFIX}filename" and the actual filename '
                    "to each component's properties array."
                ),
            )
        )

        findings.append(
            self._create_finding(
                "distribution_licences",
                status="fail" if licence_failures else "pass",
                details=self._format_failure_details(licence_failures) if licence_failures else None,
                remediation=(
                    "Add licenses array with expression field using SPDX identifiers "
                    '(e.g., {"expression": "MIT", "acknowledgement": "concluded"}).'
                ),
            )
        )

        # Determine hash status: fail if no hash, warning if non-SHA-512, pass if SHA-512
        if hash_failures:
            hash_status = "fail"
            hash_details = f"No hash found for: {', '.join(hash_failures)}"
        elif hash_warnings:
            hash_status = "warning"
            hash_details = (
                f"Non-SHA-512 hash found (acceptable but not ideal) for: {', '.join(hash_warnings)}. "
                "BSI TR-03183-2 recommends SHA-512."
            )
        else:
            hash_status = "pass"
            hash_details = None

        findings.append(
            self._create_finding(
                "hash_value",
                status=hash_status,
                details=hash_details,
                remediation=(
                    "Add hashes with alg='SHA-512' for each component. "
                    "Other algorithms (SHA-256, etc.) are acceptable but SHA-512 is recommended."
                ),
            )
        )

        findings.append(
            self._create_finding(
                "executable_property",
                status="fail" if executable_failures else "pass",
                details=self._format_failure_details(executable_failures) if executable_failures else None,
                remediation=(
                    f'Add property with name="{BSI_PROPERTY_PREFIX}executable" and value '
                    '"executable" or "non-executable" to each component.'
                ),
            )
        )

        findings.append(
            self._create_finding(
                "archive_property",
                status="fail" if archive_failures else "pass",
                details=self._format_failure_details(archive_failures) if archive_failures else None,
                remediation=(
                    f'Add property with name="{BSI_PROPERTY_PREFIX}archive" and value '
                    '"archive" or "no archive" to each component.'
                ),
            )
        )

        findings.append(
            self._create_finding(
                "structured_property",
                status="fail" if structured_failures else "pass",
                details=self._format_failure_details(structured_failures) if structured_failures else None,
                remediation=(
                    f'Add property with name="{BSI_PROPERTY_PREFIX}structured" and value '
                    '"structured" or "unstructured" to each component.'
                ),
            )
        )

        # Dependencies with completeness indicator
        has_deps, has_completeness = self._check_cyclonedx_dependencies(dependencies, compositions, components)
        dep_status = "pass" if (has_deps and has_completeness) else "fail"
        dep_details = None
        if not has_deps:
            dep_details = "No valid dependency relationships found"
        elif not has_completeness:
            dep_details = "Dependencies found but missing completeness indicator in compositions"

        findings.append(
            self._create_finding(
                "dependencies",
                status=dep_status,
                details=dep_details,
                remediation=(
                    "Add dependencies array with ref and dependsOn fields. Also add compositions "
                    'array with aggregate field set to "complete", "incomplete", or "unknown".'
                ),
            )
        )

        # Unique identifiers (warning if missing, as it's "MUST if exists")
        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="pass" if not identifier_warnings else "warning",
                details=(
                    self._format_failure_details(identifier_warnings)
                    if identifier_warnings
                    else "All components have unique identifiers"
                ),
                remediation=(
                    "Add purl, cpe, or swid identifiers to components. Per BSI TR-03183-2 §5.2.4, "
                    "these MUST be provided if they exist for the component."
                ),
            )
        )

        # Check for embedded vulnerabilities (MUST NOT have any per BSI §3.1)
        findings.append(self._check_cyclonedx_vulnerabilities(data))

        # Note: Attestation check is added in assess() method after validation
        # because it requires the sbom_id parameter

        return findings

    def _validate_spdx(self, data: dict[str, Any], format_version: str) -> list[Finding]:
        """Validate SPDX format SBOM against BSI requirements.

        Note: BSI TR-03183-2 v2.1.0 requires SPDX 3.0.1+, which has a different
        structure than SPDX 2.x. This method handles both for informational
        purposes, but SPDX 2.x will fail the format version check.

        Args:
            data: Parsed SPDX SBOM dictionary.
            format_version: The SPDX version.

        Returns:
            List of findings for each BSI element.
        """
        # Check if this is SPDX 3.x (graph-based) or 2.x (document-based)
        is_spdx3 = _version_gte(format_version, "3.0")

        if is_spdx3:
            return self._validate_spdx3(data)
        else:
            # SPDX 2.x - will fail format check but we still validate what we can
            return self._validate_spdx2_legacy(data)

    def _validate_spdx3(self, data: dict[str, Any]) -> list[Finding]:
        """Validate SPDX 3.0.1+ format SBOM against BSI requirements.

        SPDX 3.0 uses a graph-based model with elements array containing
        different types (SpdxDocument, software_Package, software_File, etc.)

        Args:
            data: Parsed SPDX 3.x SBOM dictionary.

        Returns:
            List of findings for each BSI element.
        """
        findings: list[Finding] = []

        # SPDX 3.x has an "elements" array with different types
        elements = data.get("@graph", data.get("spdxDocument", {}).get("elements", []))
        if not elements:
            elements = data.get("elements", [])

        # Extract elements by type
        creation_info = None
        packages: list[dict] = []
        files: list[dict] = []
        relationships: list[dict] = []
        persons_orgs: dict[str, dict] = {}

        for element in elements:
            elem_type = element.get("type", element.get("@type", ""))
            if "CreationInfo" in elem_type:
                creation_info = element
            elif "software_Package" in elem_type or "Package" in elem_type:
                packages.append(element)
            elif "software_File" in elem_type or "File" in elem_type:
                files.append(element)
            elif "Relationship" in elem_type:
                relationships.append(element)
            elif "Person" in elem_type or "Organization" in elem_type:
                spdx_id = element.get("spdxId", element.get("@id", ""))
                if spdx_id:
                    persons_orgs[spdx_id] = element

        # === SBOM-level required fields ===

        # 1. SBOM Creator
        sbom_creator = self._get_spdx3_sbom_creator(creation_info, persons_orgs)
        findings.append(
            self._create_finding(
                "sbom_creator",
                status="pass" if sbom_creator else "fail",
                details=None if sbom_creator else "No valid email or URL found for SBOM creator in CreationInfo",
                remediation=(
                    "Add createdBy reference to a Person or Organization element with "
                    "externalIdentifiers containing email or URL."
                ),
            )
        )

        # 2. Timestamp
        timestamp = creation_info.get("created") if creation_info else None
        timestamp_valid = self._validate_timestamp(timestamp)
        timestamp_details = None
        if not timestamp_valid:
            timestamp_details = "Missing timestamp" if not timestamp else "Invalid ISO-8601 format"
        findings.append(
            self._create_finding(
                "timestamp",
                status="pass" if timestamp_valid else "fail",
                details=timestamp_details,
                remediation="Add created field in CreationInfo with ISO-8601 format.",
            )
        )

        # === Component-level required fields ===
        name_failures: list[str] = []
        version_failures: list[str] = []
        creator_failures: list[str] = []
        filename_failures: list[str] = []
        licence_failures: list[str] = []
        hash_failures: list[str] = []  # No hash at all
        hash_warnings: list[str] = []  # Has hash but not SHA-512
        executable_failures: list[str] = []
        archive_failures: list[str] = []
        structured_failures: list[str] = []
        identifier_warnings: list[str] = []

        for i, package in enumerate(packages):
            pkg_name = package.get("name", f"Package {i + 1}")

            # 1. Component name
            if not package.get("name"):
                name_failures.append(f"Package at index {i}")

            # 2. Component version
            if not package.get("software_packageVersion"):
                version_failures.append(pkg_name)

            # 3. Component creator
            creator = self._get_spdx3_component_creator(package, persons_orgs)
            if not creator:
                creator_failures.append(pkg_name)

            # 4-9. Filename, hash, executable, archive, structured
            # These require checking related File elements via relationships
            pkg_id = package.get("spdxId", package.get("@id", ""))
            related_files = self._get_spdx3_related_files(pkg_id, relationships, files)

            if not related_files:
                filename_failures.append(pkg_name)
                hash_failures.append(pkg_name)
                executable_failures.append(pkg_name)
                archive_failures.append(pkg_name)
                structured_failures.append(pkg_name)
            else:
                for file_elem in related_files:
                    if not file_elem.get("name"):
                        filename_failures.append(pkg_name)

                    # Check hash (SHA-512 preferred, other hashes acceptable with warning)
                    hash_status = self._check_spdx3_file_hash(file_elem)
                    if hash_status == "none":
                        hash_failures.append(pkg_name)
                    elif hash_status == "other":
                        hash_warnings.append(pkg_name)

                    # Check additionalPurpose for BSI properties
                    purposes = file_elem.get("software_additionalPurpose", [])
                    non_exec_types = ["source", "documentation", "data"]
                    is_exec = "executable" in purposes
                    is_non_exec = any(p in purposes for p in non_exec_types)
                    if not is_exec and not is_non_exec:
                        executable_failures.append(pkg_name)
                    if "archive" not in purposes and "container" not in purposes:
                        archive_failures.append(pkg_name)
                    if "container" not in purposes and "firmware" not in purposes:
                        structured_failures.append(pkg_name)

            # Licence
            has_licence = self._has_spdx3_licence(package, relationships)
            if not has_licence:
                licence_failures.append(pkg_name)

            # Unique identifiers
            has_identifier = self._has_spdx3_identifier(package)
            if not has_identifier:
                identifier_warnings.append(pkg_name)

        # Create findings (same pattern as CycloneDX)
        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if name_failures else "pass",
                details=self._format_failure_details(name_failures) if name_failures else None,
                remediation="Add name field to all software_Package elements.",
            )
        )

        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=self._format_failure_details(version_failures) if version_failures else None,
                remediation="Add software_packageVersion field to packages.",
            )
        )

        findings.append(
            self._create_finding(
                "component_creator",
                status="fail" if creator_failures else "pass",
                details=self._format_failure_details(creator_failures) if creator_failures else None,
                remediation="Add originatedBy reference to Person/Organization with email or URL.",
            )
        )

        findings.append(
            self._create_finding(
                "filename",
                status="fail" if filename_failures else "pass",
                details=self._format_failure_details(filename_failures) if filename_failures else None,
                remediation="Add software_File elements with name field via hasDistributionArtifact relationship.",
            )
        )

        findings.append(
            self._create_finding(
                "distribution_licences",
                status="fail" if licence_failures else "pass",
                details=self._format_failure_details(licence_failures) if licence_failures else None,
                remediation="Add hasConcludedLicense relationship to simpleLicensing_LicenseExpression element.",
            )
        )

        # Determine hash status: fail if no hash, warning if non-SHA-512, pass if SHA-512
        if hash_failures:
            hash_status = "fail"
            hash_details = f"No hash found for: {', '.join(hash_failures)}"
        elif hash_warnings:
            hash_status = "warning"
            hash_details = (
                f"Non-SHA-512 hash found (acceptable but not ideal) for: {', '.join(hash_warnings)}. "
                "BSI TR-03183-2 recommends SHA-512."
            )
        else:
            hash_status = "pass"
            hash_details = None

        findings.append(
            self._create_finding(
                "hash_value",
                status=hash_status,
                details=hash_details,
                remediation=(
                    "Add verifiedUsing with algorithm sha512 to software_File elements. "
                    "Other algorithms (sha256, etc.) are acceptable but SHA-512 is recommended."
                ),
            )
        )

        findings.append(
            self._create_finding(
                "executable_property",
                status="fail" if executable_failures else "pass",
                details=self._format_failure_details(executable_failures) if executable_failures else None,
                remediation='Add "executable" to software_additionalPurpose array if component is executable.',
            )
        )

        findings.append(
            self._create_finding(
                "archive_property",
                status="fail" if archive_failures else "pass",
                details=self._format_failure_details(archive_failures) if archive_failures else None,
                remediation='Add "archive" to software_additionalPurpose array if component is an archive.',
            )
        )

        findings.append(
            self._create_finding(
                "structured_property",
                status="fail" if structured_failures else "pass",
                details=self._format_failure_details(structured_failures) if structured_failures else None,
                remediation='Add "container" or "firmware" to software_additionalPurpose to indicate structure.',
            )
        )

        # Dependencies with completeness
        has_deps, has_completeness = self._check_spdx3_dependencies(relationships)
        dep_status = "pass" if (has_deps and has_completeness) else "fail"
        dep_details = None
        if not has_deps:
            dep_details = "No valid dependency relationships found"
        elif not has_completeness:
            dep_details = "Dependencies found but missing completeness indicator"

        findings.append(
            self._create_finding(
                "dependencies",
                status=dep_status,
                details=dep_details,
                remediation=(
                    "Add Relationship elements with relationshipType 'dependsOn' or 'contains' "
                    "and completeness field set to 'complete', 'incomplete', or 'noAssertion'."
                ),
            )
        )

        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="pass" if not identifier_warnings else "warning",
                details=self._format_failure_details(identifier_warnings) if identifier_warnings else None,
                remediation="Add externalIdentifiers with cpe22, cpe23, swid, or packageURL types.",
            )
        )

        # Check for embedded vulnerabilities (MUST NOT have any per BSI §3.1)
        findings.append(self._check_spdx_vulnerabilities(data))

        # Note: Attestation check is added in assess() method after validation

        return findings

    def _validate_spdx2_legacy(self, data: dict[str, Any]) -> list[Finding]:
        """Validate SPDX 2.x format SBOM (legacy, non-compliant with BSI 2.1.0).

        This provides informational findings for SPDX 2.x SBOMs, which will
        already fail the format version check.

        Args:
            data: Parsed SPDX 2.x SBOM dictionary.

        Returns:
            List of findings with warnings about SPDX 2.x limitations.
        """
        findings: list[Finding] = []
        packages = data.get("packages", [])
        relationships = data.get("relationships", [])
        creation_info = data.get("creationInfo", {})

        # SBOM Creator
        creators = creation_info.get("creators", [])
        has_creator_contact = False
        for creator in creators:
            if "@" in creator or "http" in creator.lower():
                has_creator_contact = True
                break

        findings.append(
            self._create_finding(
                "sbom_creator",
                status="pass" if has_creator_contact else "fail",
                details=None if has_creator_contact else "No email or URL found in creators",
                remediation="Add creator with email or URL in creationInfo.creators array.",
            )
        )

        # Timestamp
        timestamp = creation_info.get("created")
        timestamp_valid = self._validate_timestamp(timestamp)
        findings.append(
            self._create_finding(
                "timestamp",
                status="pass" if timestamp_valid else "fail",
                details=None if timestamp_valid else ("Missing" if not timestamp else "Invalid format"),
                remediation="Add created field in creationInfo with ISO-8601 timestamp.",
            )
        )

        # Component-level - mark most as fail with note about SPDX 2.x limitations
        name_failures = [p.get("name", f"Package {i}") for i, p in enumerate(packages) if not p.get("name")]
        version_failures = [p.get("name", f"Package {i}") for i, p in enumerate(packages) if not p.get("versionInfo")]
        supplier_failures = [p.get("name", f"Package {i}") for i, p in enumerate(packages) if not p.get("supplier")]

        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if name_failures else "pass",
                details=self._format_failure_details(name_failures) if name_failures else None,
                remediation="Add name field to all packages.",
            )
        )

        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=self._format_failure_details(version_failures) if version_failures else None,
                remediation="Add versionInfo field to packages.",
            )
        )

        findings.append(
            self._create_finding(
                "component_creator",
                status="fail" if supplier_failures else "pass",
                details=self._format_failure_details(supplier_failures) if supplier_failures else None,
                remediation="Add supplier field with email or URL to packages.",
            )
        )

        # BSI-specific fields not directly available in SPDX 2.x
        spdx2_limitation = "SPDX 2.x does not directly support this BSI requirement. Upgrade to SPDX 3.0.1+."

        spdx2_unsupported_fields = [
            "filename",
            "distribution_licences",
            "hash_value",
            "executable_property",
            "archive_property",
            "structured_property",
        ]
        for field in spdx2_unsupported_fields:
            findings.append(
                self._create_finding(
                    field,
                    status="fail",
                    details=spdx2_limitation,
                    remediation=f"Upgrade to SPDX 3.0.1+ to properly represent {field.replace('_', ' ')}.",
                )
            )

        # Dependencies
        has_deps = any(
            rel.get("relationshipType", "").upper() in ["DEPENDS_ON", "CONTAINS", "DEPENDENCY_OF"]
            for rel in relationships
        )
        findings.append(
            self._create_finding(
                "dependencies",
                status="pass" if has_deps else "fail",
                details=None if has_deps else "No dependency relationships found",
                remediation="Add relationships with DEPENDS_ON or CONTAINS relationship types.",
            )
        )

        # Unique identifiers
        identifier_warnings = []
        for i, pkg in enumerate(packages):
            has_id = pkg.get("purl") or any(
                ref.get("referenceType") in ("purl", "cpe22Type", "cpe23Type") for ref in pkg.get("externalRefs", [])
            )
            if not has_id:
                identifier_warnings.append(pkg.get("name", f"Package {i}"))

        findings.append(
            self._create_finding(
                "unique_identifiers",
                status="pass" if not identifier_warnings else "warning",
                details=self._format_failure_details(identifier_warnings) if identifier_warnings else None,
                remediation="Add externalRefs with purl or CPE identifiers.",
            )
        )

        # Check for embedded vulnerabilities (MUST NOT have any per BSI §3.1)
        findings.append(self._check_spdx_vulnerabilities(data))

        # Note: Attestation check is added in assess() method after validation

        return findings

    # === Helper methods ===

    def _get_cyclonedx_sbom_creator(self, metadata: dict[str, Any]) -> str | None:
        """Extract SBOM creator email or URL from CycloneDX metadata."""
        manufacturer = metadata.get("manufacturer", {})

        # Check for URL
        if _is_valid_url(manufacturer.get("url", "")):
            return manufacturer["url"]

        # Check for email in contacts
        for contact in manufacturer.get("contact", []):
            if _is_valid_email(contact.get("email", "")):
                return contact["email"]

        return None

    def _get_cyclonedx_component_creator(self, component: dict[str, Any]) -> str | None:
        """Extract component creator email or URL from CycloneDX component."""
        manufacturer = component.get("manufacturer", {})

        # Check for URL
        if _is_valid_url(manufacturer.get("url", "")):
            return manufacturer["url"]

        # Check for email in contacts
        for contact in manufacturer.get("contact", []):
            if _is_valid_email(contact.get("email", "")):
                return contact["email"]

        return None

    def _get_bsi_property(self, component: dict[str, Any], prop_name: str) -> str | None:
        """Get a BSI property value from CycloneDX component properties."""
        full_name = f"{BSI_PROPERTY_PREFIX}{prop_name}"
        for prop in component.get("properties", []):
            if prop.get("name") == full_name:
                return prop.get("value")
        return None

    def _has_valid_cyclonedx_licence(self, component: dict[str, Any]) -> bool:
        """Check if CycloneDX component has valid distribution licence using SPDX identifier."""
        for licence in component.get("licenses", []):
            # Check for expression (preferred per BSI)
            if licence.get("expression"):
                return True
            # Check for license.id (SPDX identifier)
            if licence.get("license", {}).get("id"):
                return True
        return False

    def _check_component_hash(self, component: dict[str, Any]) -> str:
        """Check CycloneDX component hash status.

        BSI TR-03183-2 requires SHA-512, but we accept other hashes with a warning.

        Returns:
            "sha512" if SHA-512 hash found, "other" if other hash found, "none" if no hash.
        """
        has_other_hash = False

        for ext_ref in component.get("externalReferences", []):
            if ext_ref.get("type") == "distribution":
                for hash_obj in ext_ref.get("hashes", []):
                    alg = hash_obj.get("alg", "").upper()
                    if alg == "SHA-512":
                        return "sha512"
                    if alg:
                        has_other_hash = True

        # Also check component-level hashes
        for hash_obj in component.get("hashes", []):
            alg = hash_obj.get("alg", "").upper()
            if alg == "SHA-512":
                return "sha512"
            if alg:
                has_other_hash = True

        return "other" if has_other_hash else "none"

    def _check_cyclonedx_dependencies(
        self,
        dependencies: list[dict[str, Any]],
        compositions: list[dict[str, Any]],
        components: list[dict[str, Any]],
    ) -> tuple[bool, bool]:
        """Check CycloneDX dependencies and completeness indicator.

        Returns:
            Tuple of (has_dependencies, has_completeness_indicator).
        """
        has_deps = any(dep.get("ref") for dep in dependencies)

        # Check for completeness in compositions
        has_completeness = any(
            comp.get("aggregate") in ("complete", "incomplete", "unknown", "not_specified") for comp in compositions
        )

        return has_deps, has_completeness

    def _get_spdx3_sbom_creator(
        self, creation_info: dict[str, Any] | None, persons_orgs: dict[str, dict]
    ) -> str | None:
        """Extract SBOM creator email or URL from SPDX 3.x CreationInfo."""
        if not creation_info:
            return None

        created_by = creation_info.get("createdBy", [])
        for ref in created_by:
            entity = persons_orgs.get(ref, {})
            for ext_id in entity.get("externalIdentifiers", []):
                id_type = ext_id.get("externalIdentifierType", "")
                identifier = ext_id.get("identifier", "")
                if id_type == "email" and _is_valid_email(identifier):
                    return identifier
                if id_type in ("urlScheme", "other") and _is_valid_url(identifier):
                    return identifier
        return None

    def _get_spdx3_component_creator(self, package: dict[str, Any], persons_orgs: dict[str, dict]) -> str | None:
        """Extract component creator email or URL from SPDX 3.x package."""
        originated_by = package.get("originatedBy", [])
        for ref in originated_by:
            entity = persons_orgs.get(ref, {})
            for ext_id in entity.get("externalIdentifiers", []):
                id_type = ext_id.get("externalIdentifierType", "")
                identifier = ext_id.get("identifier", "")
                if id_type == "email" and _is_valid_email(identifier):
                    return identifier
                if id_type in ("urlScheme", "other") and _is_valid_url(identifier):
                    return identifier
        return None

    def _get_spdx3_related_files(
        self,
        pkg_id: str,
        relationships: list[dict[str, Any]],
        files: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get files related to a package via hasDistributionArtifact relationship."""
        related_file_ids: set[str] = set()
        for rel in relationships:
            if rel.get("from") == pkg_id and rel.get("relationshipType") == "hasDistributionArtifact":
                for to_ref in rel.get("to", []):
                    related_file_ids.add(to_ref)

        return [f for f in files if f.get("spdxId", f.get("@id")) in related_file_ids]

    def _check_spdx3_file_hash(self, file_elem: dict[str, Any]) -> str:
        """Check SPDX 3.x file element hash status.

        BSI TR-03183-2 requires SHA-512, but we accept other hashes with a warning.

        Returns:
            "sha512" if SHA-512 hash found, "other" if other hash found, "none" if no hash.
        """
        has_other_hash = False

        for verified in file_elem.get("verifiedUsing", []):
            alg = verified.get("algorithm", "")
            if alg == "sha512":
                return "sha512"
            if alg:
                has_other_hash = True

        return "other" if has_other_hash else "none"

    def _has_spdx3_licence(self, package: dict[str, Any], relationships: list[dict[str, Any]]) -> bool:
        """Check if SPDX 3.x package has concluded licence via relationship."""
        pkg_id = package.get("spdxId", package.get("@id"))
        for rel in relationships:
            if rel.get("from") == pkg_id and rel.get("relationshipType") == "hasConcludedLicense":
                return True
        return False

    def _has_spdx3_identifier(self, package: dict[str, Any]) -> bool:
        """Check if SPDX 3.x package has unique identifier."""
        for ext_id in package.get("externalIdentifiers", []):
            id_type = ext_id.get("externalIdentifierType", "")
            if id_type in ("cpe22", "cpe23", "swid", "packageURL"):
                return True
        return False

    def _check_spdx3_dependencies(self, relationships: list[dict[str, Any]]) -> tuple[bool, bool]:
        """Check SPDX 3.x dependencies and completeness indicator.

        Returns:
            Tuple of (has_dependencies, has_completeness_indicator).
        """
        has_deps = False
        has_completeness = False

        for rel in relationships:
            rel_type = rel.get("relationshipType", "")
            if rel_type in ("dependsOn", "contains"):
                has_deps = True
                if rel.get("completeness") in ("complete", "incomplete", "noAssertion"):
                    has_completeness = True

        return has_deps, has_completeness

    def _validate_timestamp(self, timestamp: str | None) -> bool:
        """Validate that a timestamp is in valid ISO-8601 format."""
        if not timestamp:
            return False
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return True
        except (ValueError, TypeError):
            return False

    def _format_failure_details(self, failures: list[str]) -> str:
        """Format a list of failures into a details string."""
        return f"Missing for: {', '.join(failures)}"

    def _check_cyclonedx_vulnerabilities(self, data: dict[str, Any]) -> Finding:
        """Check that CycloneDX SBOM does not contain embedded vulnerabilities.

        BSI TR-03183-2 §3.1 explicitly states that SBOMs MUST NOT contain
        vulnerability information. Vulnerabilities should be communicated
        via separate CSAF or VEX documents.

        Args:
            data: Parsed CycloneDX SBOM dictionary.

        Returns:
            Finding for vulnerability check.
        """
        # Check for vulnerabilities array (CycloneDX 1.4+)
        vulnerabilities = data.get("vulnerabilities", [])
        has_vulnerabilities = len(vulnerabilities) > 0

        # Also check for vulnerability-related extensions
        extensions = data.get("extensions", [])
        vuln_extensions = [e for e in extensions if "vuln" in str(e).lower()]

        if has_vulnerabilities:
            return self._create_finding(
                "no_vulnerabilities",
                status="fail",
                details=f"Found {len(vulnerabilities)} embedded vulnerabilities",
                remediation=(
                    "Remove the 'vulnerabilities' array from the SBOM. "
                    "Use CSAF or VEX documents to communicate vulnerability information separately."
                ),
            )
        elif vuln_extensions:
            return self._create_finding(
                "no_vulnerabilities",
                status="warning",
                details="Found vulnerability-related extensions",
                remediation=(
                    "Consider removing vulnerability extensions. "
                    "Use CSAF or VEX documents for vulnerability information."
                ),
            )
        else:
            return self._create_finding(
                "no_vulnerabilities",
                status="pass",
                details="No embedded vulnerability information found",
            )

    def _check_spdx_vulnerabilities(self, data: dict[str, Any]) -> Finding:
        """Check that SPDX SBOM does not contain embedded vulnerabilities.

        BSI TR-03183-2 §3.1 explicitly states that SBOMs MUST NOT contain
        vulnerability information.

        Args:
            data: Parsed SPDX SBOM dictionary.

        Returns:
            Finding for vulnerability check.
        """
        # Check for SPDX 3.x vulnerability elements
        elements = data.get("elements", data.get("@graph", []))
        vuln_elements = [
            e
            for e in elements
            if "Vulnerability" in str(e.get("type", e.get("@type", "")))
            or "VulnAssessment" in str(e.get("type", e.get("@type", "")))
        ]

        # Check for SPDX 2.x vulnerability annotations/comments
        packages = data.get("packages", [])
        vuln_annotations = []
        for pkg in packages:
            annotations = pkg.get("annotations", [])
            for ann in annotations:
                if "vuln" in str(ann).lower() or "cve" in str(ann).lower():
                    vuln_annotations.append(ann)

        if vuln_elements:
            return self._create_finding(
                "no_vulnerabilities",
                status="fail",
                details=f"Found {len(vuln_elements)} vulnerability elements",
                remediation=(
                    "Remove vulnerability elements from the SBOM. "
                    "Use CSAF or VEX documents to communicate vulnerability information separately."
                ),
            )
        elif vuln_annotations:
            return self._create_finding(
                "no_vulnerabilities",
                status="warning",
                details="Found potential vulnerability annotations",
                remediation=(
                    "Consider removing vulnerability-related annotations. "
                    "Use CSAF or VEX documents for vulnerability information."
                ),
            )
        else:
            return self._create_finding(
                "no_vulnerabilities",
                status="pass",
                details="No embedded vulnerability information found",
            )

    def _check_attestation_requirement(self, dependency_status: dict | None) -> Finding:
        """Check that at least one attestation plugin has passed for this SBOM.

        BSI TR-03183-2 §3.2 and CRA Article 10 require digital signatures for
        SBOM integrity verification. This check uses the orchestrator-provided
        dependency status to verify attestation requirements (per ADR-003).

        Args:
            dependency_status: Dependency status provided by the orchestrator.
                Expected to contain requires_one_of with attestation category.

        Returns:
            Finding indicating attestation status.
        """
        plugins_list = ", ".join(self.REQUIRED_ATTESTATION_PLUGINS)

        # If no dependency status provided, attestation cannot be verified
        if not dependency_status:
            return self._create_finding(
                "attestation_check",
                status="warning",
                details="Dependency status not available from orchestrator",
                remediation=(
                    f"Run one of the following attestation plugins to verify SBOM integrity: "
                    f"{plugins_list}. BSI TR-03183-2 requires digital signature verification."
                ),
            )

        # Check requires_one_of (attestation category dependency)
        one_of = dependency_status.get("requires_one_of", {})

        if one_of.get("satisfied"):
            # At least one attestation plugin passed
            passing = one_of.get("passing_plugins", [])
            return self._create_finding(
                "attestation_check",
                status="pass",
                details=f"Passing attestation(s): {', '.join(passing)}",
            )
        elif one_of.get("failed_plugins"):
            # Attestation plugins ran but none passed
            failed = one_of.get("failed_plugins", [])
            return self._create_finding(
                "attestation_check",
                status="fail",
                details=f"Attestation plugin(s) ran but did not pass: {', '.join(failed)}",
                remediation=(
                    "Review the attestation plugin results and resolve any issues. "
                    "The SBOM must have a valid digital signature for BSI compliance."
                ),
            )
        else:
            # No attestation plugins have been run
            return self._create_finding(
                "attestation_check",
                status="fail",
                details="No attestation plugin has been run for this SBOM",
                remediation=(
                    f"Run one of the following attestation plugins to verify SBOM integrity: "
                    f"{plugins_list}. BSI TR-03183-2 requires digital signature verification."
                ),
            )

    def _create_finding(
        self,
        element: str,
        status: str,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """Create a finding for a BSI element.

        Args:
            element: Element key (e.g., "component_name").
            status: Status string ("pass", "fail", or "warning").
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
            severity="info" if status == "pass" else ("low" if status == "warning" else "medium"),
            remediation=remediation if status in ("fail", "warning") else None,
            metadata={
                "standard": "BSI TR-03183-2",
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
            id="bsi-tr03183:error",
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
            plugin_name="bsi-tr03183-v2.1-compliance",
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
