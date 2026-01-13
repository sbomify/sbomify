"""CISA 2025 Minimum Elements compliance plugin.

This plugin validates SBOMs against the CISA Minimum Elements for a Software
Bill of Materials as defined in the August 2025 public comment draft.

IMPORTANT: This standard is based on the PUBLIC COMMENT DRAFT released in
August 2025. It is NOT a finalized standard. The requirements may change
when the final version is published by CISA. This plugin will be updated
accordingly when the final standard is released.

Standard Reference:
    - Name: CISA 2025 Minimum Elements for a Software Bill of Materials (SBOM)
    - Version: 2025-08 (August 2025 Public Comment Draft)
    - URL: https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf
    - Status: PUBLIC COMMENT DRAFT (Pre-decisional)

The eleven CISA 2025 minimum data fields are:
    1. SBOM Author - Name of entity that creates the SBOM data for this component
    2. Software Producer - Name of entity that creates, defines, and identifies components
       (replaces NTIA "Supplier Name")
    3. Component Name - Name assigned by the Software Producer to a software component
    4. Component Version - Identifier used to specify a change from previous version
    5. Software Identifiers - At least one identifier for component lookup (PURL, CPE preferred)
    6. Component Hash (NEW) - Cryptographic hash value of the software component
    7. License (NEW) - License(s) under which the software component is made available
    8. Dependency Relationship - Relationship between software components
    9. Tool Name (NEW) - Name of tool(s) used by SBOM Author to generate the SBOM
    10. Timestamp - Date and time of SBOM data assembly (ISO 8601)
    11. Generation Context (NEW) - Software lifecycle phase (before build, build, after build)

Key differences from NTIA 2021:
    - 4 new required elements: Component Hash, License, Tool Name, Generation Context
    - Software Producer replaces Supplier Name
    - Software Identifiers requires at least one (not optional)
    - Stricter timestamp validation (ISO 8601 enforced)
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


# Valid generation context values
# CISA defines: "before build, during build, after build"
# CycloneDX lifecycle phases: design, pre-build, build, post-build, operations,
#   discovery, decommission
# We also accept common synonyms used in tooling:
#   - "source" = before_build (source code analysis)
#   - "analyzed" = post_build (binary analysis)
GENERATION_CONTEXT_VALUES = {
    # CISA terminology (underscore format)
    "before_build",
    "build",
    "post_build",
    # CycloneDX lifecycle phases (hyphen format)
    "design",
    "pre-build",
    "post-build",
    "operations",
    "discovery",
    "decommission",
    # Common synonyms
    "source",  # equivalent to before_build/pre-build
    "analyzed",  # equivalent to post_build/post-build
}


class CISAMinimumElementsPlugin(AssessmentPlugin):
    """CISA 2025 Minimum Elements compliance plugin (PUBLIC COMMENT DRAFT).

    This plugin checks SBOMs for compliance with the eleven minimum data fields
    defined in the CISA August 2025 public comment draft. It supports both SPDX
    and CycloneDX formats.

    IMPORTANT: This is based on a PUBLIC COMMENT DRAFT, not a finalized standard.
    The requirements may change when the final version is published by CISA.

    Attributes:
        VERSION: Plugin version (semantic versioning).
        STANDARD_NAME: Official name of the standard being checked.
        STANDARD_VERSION: Version identifier of the standard (YYYY-MM format).
        STANDARD_URL: Official URL to the standard documentation.

    Example:
        >>> plugin = CISAMinimumElementsPlugin()
        >>> result = plugin.assess("sbom123", Path("/tmp/sbom.json"))
        >>> print(f"Compliant: {result.summary.fail_count == 0}")
    """

    VERSION = "1.0.0"
    STANDARD_NAME = "CISA 2025 Minimum Elements for a Software Bill of Materials (SBOM) - Public Comment Draft"
    STANDARD_VERSION = "2025-08-draft"  # August 2025 public comment draft
    STANDARD_URL = "https://www.cisa.gov/sites/default/files/2025-08/2025_CISA_SBOM_Minimum_Elements.pdf"

    # Finding IDs for each CISA element (prefixed with standard version)
    FINDING_IDS = {
        "sbom_author": "cisa-2025:sbom-author",
        "software_producer": "cisa-2025:software-producer",
        "component_name": "cisa-2025:component-name",
        "component_version": "cisa-2025:component-version",
        "software_identifiers": "cisa-2025:software-identifiers",
        "component_hash": "cisa-2025:component-hash",
        "license": "cisa-2025:license",
        "dependency_relationship": "cisa-2025:dependency-relationship",
        "tool_name": "cisa-2025:tool-name",
        "timestamp": "cisa-2025:timestamp",
        "generation_context": "cisa-2025:generation-context",
    }

    # Human-readable titles for findings
    FINDING_TITLES = {
        "sbom_author": "SBOM Author",
        "software_producer": "Software Producer",
        "component_name": "Component Name",
        "component_version": "Component Version",
        "software_identifiers": "Software Identifiers",
        "component_hash": "Component Hash",
        "license": "License",
        "dependency_relationship": "Dependency Relationship",
        "tool_name": "Tool Name",
        "timestamp": "Timestamp",
        "generation_context": "Generation Context",
    }

    # Descriptions for each element per CISA 2025 standard
    FINDING_DESCRIPTIONS = {
        "sbom_author": "Name of entity that creates the SBOM data for this component",
        "software_producer": "Name of entity that creates, defines, and identifies components",
        "component_name": "Name assigned by the Software Producer to a software component",
        "component_version": "Identifier used by Software Producer to specify a change from previous version",
        "software_identifiers": "At least one identifier for component lookup (PURL, CPE preferred)",
        "component_hash": "Cryptographic hash value generated from the software component",
        "license": "License(s) under which the software component is made available",
        "dependency_relationship": "Relationship between software components (includes/derived from)",
        "tool_name": "Name of tool(s) used by SBOM Author to generate the SBOM",
        "timestamp": "Record of date and time of SBOM data assembly (ISO 8601)",
        "generation_context": "Software lifecycle phase at SBOM generation (before build, build, after build)",
    }

    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Returns:
            PluginMetadata with name, version, and category.
        """
        return PluginMetadata(
            name="cisa-minimum-elements-2025",
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
        )

    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        """Run CISA 2025 Minimum Elements compliance check against the SBOM.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.

        Returns:
            AssessmentResult with findings for each of the 11 CISA elements.
        """
        logger.info(f"[CISA-2025] Starting compliance check for SBOM {sbom_id}")

        # Read and parse the SBOM
        try:
            sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"[CISA-2025] Failed to parse SBOM JSON: {e}")
            return self._create_error_result(f"Invalid JSON format: {e}")
        except Exception as e:
            logger.error(f"[CISA-2025] Failed to read SBOM file: {e}")
            return self._create_error_result(f"Failed to read SBOM: {e}")

        # Detect format and validate
        sbom_format = self._detect_format(sbom_data)
        if sbom_format == "spdx":
            findings = self._validate_spdx(sbom_data)
        elif sbom_format == "cyclonedx":
            findings = self._validate_cyclonedx(sbom_data)
        else:
            logger.warning(f"[CISA-2025] Unknown SBOM format for {sbom_id}")
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

        logger.info(f"[CISA-2025] Completed compliance check for SBOM {sbom_id}: {pass_count} pass, {fail_count} fail")

        return AssessmentResult(
            plugin_name="cisa-minimum-elements-2025",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=findings,
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
                "standard_status": "public_comment_draft",
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
        """Validate SPDX format SBOM against CISA 2025 minimum elements.

        Args:
            data: Parsed SPDX SBOM dictionary.

        Returns:
            List of findings for each CISA element.
        """
        findings: list[Finding] = []
        packages = data.get("packages", [])
        relationships = data.get("relationships", [])
        creation_info = data.get("creationInfo", {})

        # Track element-level failures across all packages
        producer_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        identifier_failures: list[str] = []
        hash_failures: list[str] = []
        license_failures: list[str] = []

        # Check each package for required elements
        for i, package in enumerate(packages):
            package_name = package.get("name", f"Package {i + 1}")

            # 2. Software Producer (was Supplier Name)
            if not package.get("supplier"):
                producer_failures.append(package_name)

            # 3. Component name
            if not package.get("name"):
                component_name_failures.append(f"Package at index {i}")

            # 4. Component Version
            if not package.get("versionInfo"):
                version_failures.append(package_name)

            # 5. Software Identifiers (at least one required)
            # Only accept externalRefs with valid identifier types (purl, cpe22Type, cpe23Type, swid)
            valid_identifier_types = {"purl", "cpe22Type", "cpe23Type", "swid"}
            has_identifier = package.get("purl") or any(
                ref.get("referenceType") in valid_identifier_types for ref in package.get("externalRefs", [])
            )
            if not has_identifier:
                identifier_failures.append(package_name)

            # 6. Component Hash (NEW - check checksums)
            has_hash = bool(package.get("checksums"))
            if not has_hash:
                hash_failures.append(package_name)

            # 7. License (NEW - check licenseConcluded or licenseDeclared)
            # CISA: "If the SBOM author is not aware of the license information,
            # then the SBOM author should indicate that license information is unknown."
            # NOASSERTION is acceptable as it explicitly indicates unknown license.
            license_concluded = package.get("licenseConcluded", "")
            license_declared = package.get("licenseDeclared", "")
            has_license = bool(license_concluded or license_declared)
            if not has_license:
                license_failures.append(package_name)

        # Create findings for per-package elements

        # 2. Software Producer
        findings.append(
            self._create_finding(
                "software_producer",
                status="fail" if producer_failures else "pass",
                details=f"Missing for: {', '.join(producer_failures)}" if producer_failures else None,
                remediation="Add supplier field to packages. Use 'Organization: <name>' format.",
            )
        )

        # 3. Component Name
        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all packages.",
            )
        )

        # 4. Component Version
        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add versionInfo field. Use file creation date if version is unknown.",
            )
        )

        # 5. Software Identifiers
        findings.append(
            self._create_finding(
                "software_identifiers",
                status="fail" if identifier_failures else "pass",
                details=f"Missing for: {', '.join(identifier_failures)}" if identifier_failures else None,
                remediation="Add externalRefs with at least one identifier (PURL or CPE preferred).",
            )
        )

        # 6. Component Hash (NEW)
        findings.append(
            self._create_finding(
                "component_hash",
                status="fail" if hash_failures else "pass",
                details=f"Missing for: {', '.join(hash_failures)}" if hash_failures else None,
                remediation="Add checksums field with cryptographic hash (SHA-256 recommended).",
            )
        )

        # 7. License (NEW)
        findings.append(
            self._create_finding(
                "license",
                status="fail" if license_failures else "pass",
                details=f"Missing for: {', '.join(license_failures)}" if license_failures else None,
                remediation="Add licenseConcluded or licenseDeclared field with SPDX license expression.",
            )
        )

        # 8. Dependency relationships (document-level)
        has_dependencies = any(
            rel.get("relationshipType", "").upper() in ["DEPENDS_ON", "CONTAINS", "DESCENDANT_OF"]
            for rel in relationships
        )
        findings.append(
            self._create_finding(
                "dependency_relationship",
                status="pass" if has_dependencies else "fail",
                details=None if has_dependencies else "No DEPENDS_ON, CONTAINS, or DESCENDANT_OF relationships found",
                remediation="Add relationships section with DEPENDS_ON, CONTAINS, or DESCENDANT_OF relationships.",
            )
        )

        # 1. SBOM Author (document-level)
        creators = creation_info.get("creators", [])
        findings.append(
            self._create_finding(
                "sbom_author",
                status="pass" if creators else "fail",
                details=None if creators else "No creators found in creationInfo",
                remediation="Add creators field in creationInfo with tool or person information.",
            )
        )

        # 9. Tool Name (NEW - document-level, check for Tool: entries)
        tool_entries = [c for c in creators if c.startswith("Tool:")]
        findings.append(
            self._create_finding(
                "tool_name",
                status="pass" if tool_entries else "fail",
                details=None if tool_entries else "No Tool entries found in creators",
                remediation="Add 'Tool: <tool-name>' entry in creationInfo.creators.",
            )
        )

        # 10. Timestamp (document-level)
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

        # 11. Generation Context (NEW - check comments and annotations)
        has_generation_context = self._spdx_has_generation_context(data)
        findings.append(
            self._create_finding(
                "generation_context",
                status="pass" if has_generation_context else "fail",
                details=None if has_generation_context else "No generation context found",
                remediation=(
                    "Add generation context in creationInfo.comment (CreatorComment) or "
                    "document-level comment (DocumentComment) with lifecycle phase "
                    "(e.g., 'build', 'pre-build', 'post-build'). Alternatively, add "
                    "annotation with 'cisa:generationContext=<context>'."
                ),
            )
        )

        return findings

    def _spdx_has_generation_context(self, data: dict[str, Any]) -> bool:
        """Check if SPDX document has generation context information.

        Checks (per https://sbomify.com/compliance/schema-crosswalk/):
        - creationInfo.comment (CreatorComment)
        - document-level comment (DocumentComment)
        - document-level annotations with cisa:generationContext

        Args:
            data: Full SPDX document dictionary.

        Returns:
            True if valid generation context found.
        """
        # Check CreatorComment (creationInfo.comment)
        # See: https://sbomify.com/compliance/schema-crosswalk/
        creator_comment = data.get("creationInfo", {}).get("comment", "").lower()
        if any(ctx in creator_comment for ctx in GENERATION_CONTEXT_VALUES):
            return True

        # Check DocumentComment (document-level comment)
        # See: https://sbomify.com/compliance/schema-crosswalk/
        document_comment = data.get("comment", "").lower()
        if any(ctx in document_comment for ctx in GENERATION_CONTEXT_VALUES):
            return True

        # Check document-level annotations for explicit cisa:generationContext
        for annotation in data.get("annotations", []):
            if annotation.get("annotationType") == "OTHER":
                comment = annotation.get("comment", "")
                if "cisa:generationContext=" in comment:
                    for part in comment.split():
                        if part.startswith("cisa:generationContext="):
                            context = part.split("=", 1)[1].lower().strip()
                            if context in GENERATION_CONTEXT_VALUES:
                                return True

        return False

    def _validate_cyclonedx(self, data: dict[str, Any]) -> list[Finding]:
        """Validate CycloneDX format SBOM against CISA 2025 minimum elements.

        Args:
            data: Parsed CycloneDX SBOM dictionary.

        Returns:
            List of findings for each CISA element.
        """
        findings: list[Finding] = []
        components = data.get("components", [])
        dependencies = data.get("dependencies", [])
        metadata = data.get("metadata", {})

        # Track element-level failures across all components
        producer_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        identifier_failures: list[str] = []
        hash_failures: list[str] = []
        license_failures: list[str] = []

        # Check each component for required elements
        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i + 1}")

            # 2. Software Producer (publisher or supplier.name)
            supplier = component.get("publisher") or component.get("supplier", {}).get("name")
            if not supplier:
                producer_failures.append(component_name)

            # 3. Component name
            if not component.get("name"):
                component_name_failures.append(f"Component at index {i}")

            # 4. Component Version
            if not component.get("version"):
                version_failures.append(component_name)

            # 5. Software Identifiers (at least one required - purl, cpe, swid)
            has_identifier = bool(component.get("purl") or component.get("cpe") or component.get("swid"))
            if not has_identifier:
                identifier_failures.append(component_name)

            # 6. Component Hash (NEW)
            has_hash = bool(component.get("hashes"))
            if not has_hash:
                hash_failures.append(component_name)

            # 7. License (NEW)
            licenses = component.get("licenses", [])
            has_license = bool(licenses)
            if not has_license:
                license_failures.append(component_name)

        # Create findings for per-component elements

        # 2. Software Producer
        findings.append(
            self._create_finding(
                "software_producer",
                status="fail" if producer_failures else "pass",
                details=f"Missing for: {', '.join(producer_failures)}" if producer_failures else None,
                remediation="Add publisher field or supplier.name to components.",
            )
        )

        # 3. Component Name
        findings.append(
            self._create_finding(
                "component_name",
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all components.",
            )
        )

        # 4. Component Version
        findings.append(
            self._create_finding(
                "component_version",
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add version field. Use file creation date if version is unknown.",
            )
        )

        # 5. Software Identifiers
        findings.append(
            self._create_finding(
                "software_identifiers",
                status="fail" if identifier_failures else "pass",
                details=f"Missing for: {', '.join(identifier_failures)}" if identifier_failures else None,
                remediation="Add at least one identifier: purl (preferred), cpe, or swid.",
            )
        )

        # 6. Component Hash (NEW)
        findings.append(
            self._create_finding(
                "component_hash",
                status="fail" if hash_failures else "pass",
                details=f"Missing for: {', '.join(hash_failures)}" if hash_failures else None,
                remediation="Add hashes field with cryptographic hash (SHA-256 recommended).",
            )
        )

        # 7. License (NEW)
        findings.append(
            self._create_finding(
                "license",
                status="fail" if license_failures else "pass",
                details=f"Missing for: {', '.join(license_failures)}" if license_failures else None,
                remediation="Add licenses field with license information.",
            )
        )

        # 8. Dependency relationships (document-level)
        has_valid_dependencies = any(dep.get("ref") for dep in dependencies)
        findings.append(
            self._create_finding(
                "dependency_relationship",
                status="pass" if has_valid_dependencies else "fail",
                details=None if has_valid_dependencies else "No valid dependency relationships found",
                remediation="Add dependencies section with dependency relationships.",
            )
        )

        # 1. SBOM author (document-level)
        # NTIA/CISA "Author of SBOM Data" = "the entity that creates the SBOM"
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

        # 9. Tool Name (NEW - document-level)
        # CycloneDX 1.5+ uses tools as array of objects or tools.components
        has_tool = self._cyclonedx_has_tool(metadata)
        findings.append(
            self._create_finding(
                "tool_name",
                status="pass" if has_tool else "fail",
                details=None if has_tool else "No tool information found in metadata",
                remediation="Add tools field in metadata with tool name and version.",
            )
        )

        # 10. Timestamp (document-level)
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

        # 11. Generation Context (NEW)
        has_generation_context = self._cyclonedx_has_generation_context(metadata)
        findings.append(
            self._create_finding(
                "generation_context",
                status="pass" if has_generation_context else "fail",
                details=None if has_generation_context else "No generation context found in metadata",
                remediation=(
                    "Add metadata.lifecycles[].phase (preferred) with value: design, pre-build, "
                    "build, post-build, operations, discovery, or decommission. Alternatively, "
                    "add property 'cdx:sbom:generationContext' in metadata.properties."
                ),
            )
        )

        return findings

    def _cyclonedx_has_tool(self, metadata: dict[str, Any]) -> bool:
        """Check if CycloneDX metadata has tool information.

        Supports both CycloneDX 1.4 (tools as array of objects) and
        CycloneDX 1.5+ (tools.components array).

        Args:
            metadata: CycloneDX metadata dictionary.

        Returns:
            True if tool information found.
        """
        tools = metadata.get("tools", [])
        if isinstance(tools, list) and tools:
            # CycloneDX 1.4 format: array of tool objects
            return any(tool.get("name") or tool.get("vendor") for tool in tools)
        elif isinstance(tools, dict):
            # CycloneDX 1.5+ format: tools.components array
            components = tools.get("components", [])
            return any(comp.get("name") for comp in components)
        return False

    def _cyclonedx_has_generation_context(self, metadata: dict[str, Any]) -> bool:
        """Check if CycloneDX metadata has generation context property.

        Checks both (per https://sbomify.com/compliance/schema-crosswalk/):
        - metadata.lifecycles[].phase (preferred)
        - metadata.properties[] with name "cdx:sbom:generationContext"

        Args:
            metadata: CycloneDX metadata dictionary.

        Returns:
            True if valid generation context property found.
        """
        # Check metadata.lifecycles[].phase (preferred per schema crosswalk)
        # CycloneDX 1.5+ supports lifecycle phases: design, pre-build, build,
        # post-build, operations, discovery, decommission
        # See: https://sbomify.com/compliance/schema-crosswalk/
        lifecycles = metadata.get("lifecycles", [])
        for lifecycle in lifecycles:
            phase = lifecycle.get("phase", "").lower().strip()
            if phase in GENERATION_CONTEXT_VALUES:
                return True

        # Check metadata.properties[] for custom generation context property
        properties = metadata.get("properties", [])
        for prop in properties:
            if prop.get("name") == "cdx:sbom:generationContext":
                value = prop.get("value", "").lower().strip()
                if value in GENERATION_CONTEXT_VALUES:
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
        status: str,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """Create a finding for a CISA element.

        Args:
            element: Element key (e.g., "software_producer").
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
                "standard": "CISA",
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
            id="cisa-2025:error",
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
            plugin_name="cisa-minimum-elements-2025",
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
                "standard_status": "public_comment_draft",
                "error": True,
            },
        )
