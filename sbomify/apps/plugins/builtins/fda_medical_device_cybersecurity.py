"""FDA Medical Device Cybersecurity SBOM compliance plugin.

This plugin validates SBOMs against the FDA guidance "Cybersecurity in Medical
Devices: Quality System Considerations and Content of Premarket Submissions"
(June 2025).

Standard Reference:
    - Name: FDA Cybersecurity in Medical Devices
    - Version: 2025-06 (June 2025)
    - Official URL: https://www.fda.gov/media/119933/download

sbomify Compliance Guide:
    - Overview: https://sbomify.com/compliance/fda-medical-device/
    - Schema Crosswalk: https://sbomify.com/compliance/schema-crosswalk/
    - CLE Standard: https://sbomify.com/compliance/cle/

The FDA guidance requires SBOMs to include:
    1. NTIA Minimum Elements (7 elements from NTIA 2021 report)
    2. FDA-specific Additional Elements (Section V.A.4.b):
        - Software Support Level: Whether software is actively maintained,
          no longer maintained, or abandoned
        - End-of-Support Date: The component's end-of-support date

CLE (Common Lifecycle Enumeration) data is expected to be injected by the
sbomify GitHub Action and validated by this plugin.

CLE Format Support:
    - CycloneDX: Component-level properties. Primary recognition uses the
      sanctioned cdx:lifecycle:milestone:* taxonomy (see
      https://cyclonedx.github.io/cyclonedx-property-taxonomy/cdx/lifecycle.html):
        - cdx:lifecycle:milestone:endOfSupport (ISO-8601 date) — satisfies the
          FDA "End-of-Support Date" element.
        - Any status-bearing milestone on the component
          (endOfSupport, endOfLife, endOfDevelopment, endOfGuaranteedSupport,
          endOfBusinessOperations) — satisfies the FDA "Software Support Status"
          element, since the component's lifecycle position is derivable from
          these dates.
      For backward compatibility the deprecated cdx:cle:supportStatus /
      cdx:cle:endOfSupport property names are still accepted. New data
      should use the sanctioned names; the cdx:cle:* names are not part
      of the CycloneDX property taxonomy.
    - SPDX 2.3: Native validUntilDate field + annotations
        - Per-package validUntilDate for end-of-support.
        - Package-scoped OTHER annotation carrying cle:supportStatus=<status>
          or cle:endOfSupport=<ISO-8601 date> (annotation.spdxElementId
          points at the package).
        - Document-scoped OTHER annotation carrying the same tokens
          (spdxElementId empty, SPDXRef-DOCUMENT, or the documentDescribes
          target, per SPDX 2.3 §12). Document-level annotations are only
          applied to the BOM root subject — dependencies must carry their
          own annotations.
    - SPDX 3.0.1: Native software_validUntilDate field + Annotation elements
        - Per-package software_validUntilDate for end-of-support.
        - Annotation elements whose statement contains
          cle:supportStatus=<status> / cle:endOfSupport=<date>, scoped
          by the annotation's subject: a non-empty subject matches the
          package with that spdxId; an empty subject or subject matching
          an SpdxDocument/rootElement is treated as document-level per
          SPDX 3.0.1 Core.SpdxDocument.

Scope of the per-component CLE checks:
    FDA V.A.4.b requires per-component support data (or a per-component
    justification when unknown). Dependencies in components[] / packages[]
    are judged on their own CLE data and cannot inherit coverage from
    document-level fields. The only document-level fallback recognised is
    a narrow one that applies solely to the BOM subject (the root
    component referenced by metadata.component.bom-ref in CycloneDX, or
    the documentDescribes / DESCRIBES target in SPDX).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.builtins._spdx3_helpers import (
    extract_spdx3_elements,
    get_spdx3_creation_info_fields,
    get_spdx3_package_fields,
    is_spdx3,
)
from sbomify.apps.plugins.builtins._spdx_shared import (
    iter_spdx3_elements,
    spdx2_annotation_targets_document,
    spdx2_root_spdxid,
    spdx3_annotation_subject_matches,
    spdx3_document_subjects,
)
from sbomify.apps.plugins.sdk.base import AssessmentPlugin, SBOMContext
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
    be injected by the sbomify GitHub Action. Per-component data is
    load-bearing: the BOM subject (root component) can inherit support
    information from document-level fields via a narrow fallback, but every
    dependency must carry its own data or fail — a single document-level
    support date does not cover every component in the BOM.

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
            supported_bom_types=["sbom"],
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        """Run FDA Medical Device Cybersecurity compliance check against the SBOM.

        Args:
            sbom_id: The SBOM's primary key (for logging/reference).
            sbom_path: Path to the SBOM file on disk.
            dependency_status: Not used by this plugin.
            context: Optional SBOMContext with pre-computed metadata (unused).

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
        if sbom_format == "spdx3":
            findings = self._validate_spdx3(sbom_data)
        elif sbom_format == "spdx":
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
            Format string: "spdx", "spdx3", "cyclonedx", or "unknown".
        """
        if is_spdx3(sbom_data):
            return "spdx3"
        elif "spdxVersion" in sbom_data:
            return "spdx"
        elif isinstance(sbom_data.get("bomFormat"), str) and sbom_data["bomFormat"].lower() == "cyclonedx":
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
        packages = data.get("packages") or []
        if not isinstance(packages, list):
            packages = []
        packages = [p for p in packages if isinstance(p, dict)]
        relationships = data.get("relationships") or []
        if not isinstance(relationships, list):
            relationships = []
        creation_info = data.get("creationInfo") or {}
        if not isinstance(creation_info, dict):
            creation_info = {}

        # Track element-level failures across all packages
        supplier_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        unique_id_failures: list[str] = []
        support_status_failures: list[str] = []
        end_of_support_failures: list[str] = []

        # Narrow doc-level CLE fallback, mirroring the CycloneDX path.
        # Only the SPDX root subject (DESCRIBES target) inherits document-level
        # CLE annotations — dependencies must carry their own data. Per SPDX 2.3
        # §12, a top-level annotation with spdxElementId pointing at a specific
        # package describes that package, not the document, so such annotations
        # are not counted as "document-level" for the root fallback.
        root_spdxid = spdx2_root_spdxid(data)
        doc_has_support_status = self._spdx_doc_has_valid_support_status(data, root_spdxid)
        doc_has_end_of_support = self._spdx_doc_has_cle_token(data, "cle:endOfSupport=", root_spdxid)

        # Check each package for required elements
        for i, package in enumerate(packages):
            package_name = package.get("name", f"Package {i + 1}")

            # Skip file-type packages (e.g., lockfiles) — they're input metadata,
            # not software packages. Detected by SPDXID containing "-File-".
            spdx_id = str(package.get("SPDXID") or "")
            is_file_entry = "-File-" in spdx_id

            # === NTIA Elements ===

            # 1. Supplier name
            if not is_file_entry and not package.get("supplier"):
                supplier_failures.append(package_name)

            # 2. Component name (applies to all entries)
            if not package.get("name"):
                component_name_failures.append(f"Package at index {i}")

            if is_file_entry:
                continue

            # 3. Version
            if not package.get("versionInfo"):
                version_failures.append(package_name)

            # 4. Unique identifiers (PURL, CPE, SWID via externalRefs)
            valid_identifier_types = {"purl", "cpe22Type", "cpe23Type", "swid"}
            purl = package.get("purl")
            external_refs = package.get("externalRefs")
            if not isinstance(external_refs, list):
                external_refs = []
            has_unique_id = (isinstance(purl, str) and bool(purl)) or any(
                isinstance(ref, dict)
                and isinstance(ref.get("referenceType"), str)
                and ref["referenceType"] in valid_identifier_types
                for ref in external_refs
            )
            if not has_unique_id:
                unique_id_failures.append(package_name)

            # === FDA CLE Elements ===

            is_root = bool(root_spdxid) and spdx_id == root_spdxid

            # 8. Support status (from annotations, with root-only doc fallback)
            has_support_status = self._spdx_has_support_status(package, data) or (is_root and doc_has_support_status)
            if not has_support_status:
                support_status_failures.append(package_name)

            # 9. End of support date (validUntilDate, with root-only doc fallback)
            has_end_of_support = bool(package.get("validUntilDate")) or (is_root and doc_has_end_of_support)
            if not has_end_of_support:
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
            isinstance(rel, dict)
            and isinstance(rel.get("relationshipType"), str)
            and rel["relationshipType"].upper() in ("DEPENDS_ON", "CONTAINS")
            for rel in relationships
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

    def _spdx_doc_has_cle_token(self, data: dict[str, Any], token: str, root_spdxid: str | None) -> bool:
        """Check if any top-level OTHER annotation describing the document
        (or its DESCRIBES target) contains the given CLE token.
        """
        annotations = data.get("annotations")
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            if annotation.get("annotationType") != "OTHER":
                continue
            if not spdx2_annotation_targets_document(annotation, root_spdxid):
                continue
            comment = annotation.get("comment", "")
            if isinstance(comment, str) and token in comment:
                return True
        return False

    def _spdx_doc_has_valid_support_status(self, data: dict[str, Any], root_spdxid: str | None) -> bool:
        """Check if any top-level OTHER annotation describing the document
        (or its DESCRIBES target) carries a valid CLE support status value
        (active/deprecated/eol/abandoned/unknown)."""
        annotations = data.get("annotations")
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            if not spdx2_annotation_targets_document(annotation, root_spdxid):
                continue
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

    def _validate_spdx3(self, data: dict[str, Any]) -> list[Finding]:
        """Validate SPDX 3.0 format SBOM against FDA requirements.

        Args:
            data: Parsed SPDX 3.0 SBOM dictionary.

        Returns:
            List of findings for each element (7 NTIA + 2 CLE).
        """
        findings: list[Finding] = []
        creation_info, packages, relationships, persons_orgs, tools = extract_spdx3_elements(data)
        ci_fields = get_spdx3_creation_info_fields(creation_info, persons_orgs, tools)

        # Track element-level failures across all packages
        supplier_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        unique_id_failures: list[str] = []
        support_status_failures: list[str] = []
        end_of_support_failures: list[str] = []

        # Narrow root-only doc-level CLE fallback (parity with SPDX 2.3 path).
        # Only the SpdxDocument subject and its declared rootElements inherit
        # document-level CLE annotations — dependencies must carry their own
        # data. See spdx3_document_subjects / spdx3_annotation_subject_matches
        # for the split-sets rationale.
        doc_ids, root_ids = spdx3_document_subjects(data)
        doc_has_support_status = self._spdx3_doc_has_valid_support_status(data, doc_ids, root_ids)
        doc_has_end_of_support = self._spdx3_doc_has_cle_token(data, "cle:endOfSupport=", doc_ids, root_ids)

        for i, package in enumerate(packages):
            pkg_fields = get_spdx3_package_fields(package)
            pkg_name = pkg_fields["name"] or f"Package {i + 1}"

            # === NTIA Elements ===

            # 1. Supplier name (originatedBy → Person/Org)
            has_supplier = False
            for ref in pkg_fields["supplier_refs"]:
                if isinstance(ref, str) and ref in persons_orgs:
                    has_supplier = True
                    break
            if not has_supplier:
                supplier_failures.append(pkg_name)

            # 2. Component name
            if not pkg_fields["name"]:
                component_name_failures.append(f"Package at index {i}")

            # 3. Version
            if not pkg_fields["version"]:
                version_failures.append(pkg_name)

            # 4. Unique identifiers
            if not pkg_fields["has_unique_id"]:
                unique_id_failures.append(pkg_name)

            # === FDA CLE Elements ===

            pkg_id = package.get("spdxId", package.get("@id", ""))
            # Root subjects per SPDX 3.0.1 are the declared rootElement IDs,
            # not the SpdxDocument's own spdxId (which is not a rootElement
            # candidate). Matching pkg_id against root_ids only prevents the
            # SpdxDocument element itself from being treated as the root.
            is_root = isinstance(pkg_id, str) and pkg_id in root_ids

            # 8. Support status (from Annotation elements + root-only doc fallback)
            has_support_status = self._spdx3_has_support_status(pkg_id, data) or (is_root and doc_has_support_status)
            if not has_support_status:
                support_status_failures.append(pkg_name)

            # 9. End of support date (software_validUntilDate + root-only doc fallback)
            has_end_of_support = bool(package.get("software_validUntilDate")) or (is_root and doc_has_end_of_support)
            if not has_end_of_support:
                end_of_support_failures.append(pkg_name)

        # Create findings for per-package NTIA elements
        findings.append(
            self._create_finding(
                "supplier_name",
                is_ntia=True,
                status="fail" if supplier_failures else "pass",
                details=f"Missing for: {', '.join(supplier_failures)}" if supplier_failures else None,
                remediation="Add originatedBy reference to Person/Organization element.",
            )
        )

        findings.append(
            self._create_finding(
                "component_name",
                is_ntia=True,
                status="fail" if component_name_failures else "pass",
                details=f"Missing for: {', '.join(component_name_failures)}" if component_name_failures else None,
                remediation="Add name field to all software_Package elements.",
            )
        )

        findings.append(
            self._create_finding(
                "version",
                is_ntia=True,
                status="fail" if version_failures else "pass",
                details=f"Missing for: {', '.join(version_failures)}" if version_failures else None,
                remediation="Add software_packageVersion field to packages.",
            )
        )

        findings.append(
            self._create_finding(
                "unique_identifiers",
                is_ntia=True,
                status="fail" if unique_id_failures else "pass",
                details=f"Missing for: {', '.join(unique_id_failures)}" if unique_id_failures else None,
                remediation="Add externalIdentifiers with packageURL, cpe23, or swid type.",
            )
        )

        # 5. Dependency relationships
        has_dependencies = any(
            isinstance(rel, dict)
            and isinstance(rel.get("relationshipType"), str)
            and rel["relationshipType"] in ("dependsOn", "contains")
            for rel in relationships
        )
        findings.append(
            self._create_finding(
                "dependency_relationship",
                is_ntia=True,
                status="pass" if has_dependencies else "fail",
                details=None if has_dependencies else "No dependsOn or contains relationships found",
                remediation="Add Relationship elements with dependsOn or contains.",
            )
        )

        # 6. SBOM author (createdBy → Person/Org)
        findings.append(
            self._create_finding(
                "sbom_author",
                is_ntia=True,
                status="pass" if ci_fields["creators"] else "fail",
                details=None if ci_fields["creators"] else "No creators found in CreationInfo.createdBy",
                remediation="Add createdBy reference to Person/Organization element in CreationInfo.",
            )
        )

        # 7. Timestamp
        timestamp_valid = self._validate_timestamp(ci_fields["timestamp"])
        findings.append(
            self._create_finding(
                "timestamp",
                is_ntia=True,
                status="pass" if timestamp_valid else "fail",
                details=None
                if timestamp_valid
                else ("Missing timestamp" if not ci_fields["timestamp"] else "Invalid ISO-8601 format"),
                remediation="Add created field in CreationInfo with ISO-8601 timestamp.",
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
                    "Add CLE support status via Annotation element with statement "
                    "'cle:supportStatus=<status>' where status is one of: active, deprecated, "
                    "eol, abandoned, unknown. Use sbomify GitHub Action to inject CLE data."
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
                    "Add software_validUntilDate field to packages with ISO-8601 date. "
                    "Use sbomify GitHub Action to inject CLE data."
                ),
            )
        )

        return findings

    def _spdx3_has_support_status(self, pkg_id: str, data: dict[str, Any]) -> bool:
        """Check if an SPDX 3.0 package has CLE support status via Annotation.

        Searches Annotation elements in @graph that reference the package.

        Args:
            pkg_id: The spdxId of the package.
            data: Full SPDX 3.0 document dictionary.

        Returns:
            True if valid support status annotation found.
        """
        for element in iter_spdx3_elements(data):
            elem_type = element.get("type", element.get("@type", ""))
            if not isinstance(elem_type, str) or "Annotation" not in elem_type:
                continue

            # Check if annotation references this package
            subject = element.get("subject", element.get("annotationSubject", ""))
            if subject != pkg_id:
                continue

            # Check statement for cle:supportStatus
            statement = element.get("statement", element.get("comment", ""))
            if not isinstance(statement, str):
                continue
            if "cle:supportStatus=" in statement:
                for part in statement.split():
                    if part.startswith("cle:supportStatus="):
                        status = part.split("=", 1)[1].lower().strip()
                        if status in CLE_SUPPORT_STATUS_VALUES:
                            return True

        return False

    def _spdx3_doc_has_valid_support_status(self, data: dict[str, Any], doc_ids: set[str], root_ids: set[str]) -> bool:
        """Check for an SPDX 3.x Annotation describing the document (or its
        rootElement) that carries a valid cle:supportStatus token."""
        for element in iter_spdx3_elements(data):
            elem_type = element.get("type", element.get("@type", ""))
            if not isinstance(elem_type, str) or "Annotation" not in elem_type:
                continue
            if not spdx3_annotation_subject_matches(element, doc_ids, root_ids):
                continue
            statement = element.get("statement", element.get("comment", ""))
            if not isinstance(statement, str) or "cle:supportStatus=" not in statement:
                continue
            for part in statement.split():
                if part.startswith("cle:supportStatus="):
                    status = part.split("=", 1)[1].lower().strip()
                    if status in CLE_SUPPORT_STATUS_VALUES:
                        return True
        return False

    def _spdx3_doc_has_cle_token(self, data: dict[str, Any], token: str, doc_ids: set[str], root_ids: set[str]) -> bool:
        """Check for an SPDX 3.x Annotation describing the document (or its
        rootElement) whose statement contains the given CLE token."""
        for element in iter_spdx3_elements(data):
            elem_type = element.get("type", element.get("@type", ""))
            if not isinstance(elem_type, str) or "Annotation" not in elem_type:
                continue
            if not spdx3_annotation_subject_matches(element, doc_ids, root_ids):
                continue
            statement = element.get("statement", element.get("comment", ""))
            if isinstance(statement, str) and token in statement:
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
        components = data.get("components") or []
        if not isinstance(components, list):
            components = []
        components = [c for c in components if isinstance(c, dict)]
        dependencies = data.get("dependencies") or []
        if not isinstance(dependencies, list):
            dependencies = []
        dependencies = [d for d in dependencies if isinstance(d, dict)]
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        # Track element-level failures across all components
        supplier_failures: list[str] = []
        component_name_failures: list[str] = []
        version_failures: list[str] = []
        unique_id_failures: list[str] = []
        support_status_failures: list[str] = []
        end_of_support_failures: list[str] = []

        # Doc-level lifecycle milestone applies ONLY to the BOM subject (root
        # component referenced by metadata.component.bom-ref). Per the CycloneDX
        # property taxonomy, cdx:lifecycle:milestone:endOfSupport describes a
        # single manufacturer's support timeline for the object it's attached
        # to — it does NOT imply coverage for every component in components[].
        # FDA V.A.4.b likewise requires per-component support data (or a
        # per-component justification when unknown).
        doc_lifecycle_eos = self._cyclonedx_has_lifecycle_property(metadata, "cdx:lifecycle:milestone:endOfSupport")
        root_component = metadata.get("component") if isinstance(metadata.get("component"), dict) else {}
        root_bom_ref = root_component.get("bom-ref") if isinstance(root_component, dict) else None

        # Check each component for required elements
        for i, component in enumerate(components):
            component_name = component.get("name", f"Component {i + 1}")

            # Skip type=file components (e.g., lockfiles) — they're input metadata,
            # not software packages, so FDA/NTIA per-component fields don't apply.
            # Component Name is still checked so misnamed file entries surface.
            is_file_type = str(component.get("type", "")).lower() == "file"

            # === NTIA Elements ===

            # 1. Supplier name (publisher or supplier.name)
            if not is_file_type:
                supplier_field = component.get("supplier")
                supplier = component.get("publisher") or (
                    supplier_field.get("name") if isinstance(supplier_field, dict) else None
                )
                if not supplier:
                    supplier_failures.append(component_name)

            # 2. Component name (applies to all component types)
            if not component.get("name"):
                component_name_failures.append(f"Component at index {i}")

            if is_file_type:
                continue

            # 3. Version
            if not component.get("version"):
                version_failures.append(component_name)

            # 4. Unique identifiers (PURL, CPE, SWID)
            # Note: hashes are for "Component Hash" (RECOMMENDED), not "Unique Identifiers" (MINIMUM)
            has_unique_id = component.get("purl") or component.get("cpe") or component.get("swid")
            if not has_unique_id:
                unique_id_failures.append(component_name)

            # === FDA CLE Elements ===

            # Narrow doc-level fallback: the metadata lifecycle milestone
            # applies only when this component IS the BOM subject.
            is_root = bool(root_bom_ref) and component.get("bom-ref") == root_bom_ref
            doc_fallback = is_root and doc_lifecycle_eos

            # 8. Support status — derived from any status-bearing lifecycle
            # milestone on the component (endOfSupport, endOfLife, etc.). The
            # CycloneDX property taxonomy expresses lifecycle position via
            # dated milestones, not a status enum; presence of any such date
            # gives the FDA reviewer enough to determine support level. The
            # deprecated cdx:cle:supportStatus / cdx:cle:endOfSupport names
            # are also accepted for backward compatibility.
            has_support_status = (
                self._cyclonedx_has_status_milestone(component)
                or self._cyclonedx_has_legacy_status_property(component)
                or self._cyclonedx_has_legacy_eos_property(component)
                or doc_fallback
            )
            if not has_support_status:
                support_status_failures.append(component_name)

            # 9. End of support date
            has_end_of_support = (
                self._cyclonedx_component_has_milestone(component, "cdx:lifecycle:milestone:endOfSupport")
                or self._cyclonedx_has_legacy_eos_property(component)
                or doc_fallback
            )
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
                    "Add a lifecycle milestone to each component under the sanctioned "
                    "cdx:lifecycle:milestone:* taxonomy (e.g. "
                    "'cdx:lifecycle:milestone:endOfSupport', 'endOfLife', or "
                    "'endOfDevelopment'). The component's support status is derived "
                    "from the milestone date. Use sbomify GitHub Action to inject this data."
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
                    "Add the sanctioned component property 'cdx:lifecycle:milestone:endOfSupport' "
                    "with an ISO-8601 date value. Use sbomify GitHub Action to inject this data."
                ),
            )
        )

        return findings

    # Status-bearing milestones: presence of any of these on a component lets
    # an FDA reviewer determine its support level (active / deprecated / eol /
    # abandoned) from the dated lifecycle position.
    _STATUS_MILESTONES = (
        "cdx:lifecycle:milestone:endOfSupport",
        "cdx:lifecycle:milestone:endOfLife",
        "cdx:lifecycle:milestone:endOfDevelopment",
        "cdx:lifecycle:milestone:endOfGuaranteedSupport",
        "cdx:lifecycle:milestone:endOfBusinessOperations",
    )

    # Deprecated legacy property names (not in the CycloneDX taxonomy).
    # Accepted for backward compatibility with SBOMs that were generated
    # when the plugin used the unsanctioned cdx:cle:* convention. Prefer
    # the _STATUS_MILESTONES names for new data.
    #
    # Sunset plan: these aliases are retained for a two-release window
    # (roughly six months after the legacy-name introduction) to give
    # downstream producers time to migrate to the sanctioned
    # cdx:lifecycle:milestone:* taxonomy. After that window they may be
    # removed — track the removal commit via the git history of this
    # module rather than an absolute wall-clock date.
    _LEGACY_STATUS_PROP = "cdx:cle:supportStatus"
    _LEGACY_EOS_PROP = "cdx:cle:endOfSupport"

    def _cyclonedx_has_lifecycle_property(self, metadata: dict[str, Any], property_name: str) -> bool:
        """Check if a CycloneDX metadata object has a specific lifecycle property.

        Used for the narrow root-only doc-level fallback: the BOM subject can
        inherit support data from metadata.properties when the corresponding
        per-component property is absent.
        """
        properties = metadata.get("properties") or []
        for prop in properties if isinstance(properties, list) else []:
            if not isinstance(prop, dict):
                continue
            if prop.get("name") == property_name:
                value = prop.get("value", "")
                if isinstance(value, str) and value.strip():
                    return True
        return False

    def _cyclonedx_component_has_milestone(self, component: dict[str, Any], property_name: str) -> bool:
        """Check if a CycloneDX component has a specific lifecycle milestone
        property with a non-empty value. Uses the taxonomy-sanctioned
        cdx:lifecycle:milestone:* namespace.
        """
        properties = component.get("properties") or []
        for prop in properties if isinstance(properties, list) else []:
            if not isinstance(prop, dict):
                continue
            if prop.get("name") != property_name:
                continue
            value = prop.get("value", "")
            if isinstance(value, str) and value.strip():
                return True
        return False

    def _cyclonedx_has_status_milestone(self, component: dict[str, Any]) -> bool:
        """Check if a component carries any status-bearing lifecycle milestone.

        Any of the ``_STATUS_MILESTONES`` is enough: presence of a dated
        milestone lets the reviewer derive support level from the
        lifecycle position, which is how the CycloneDX taxonomy expresses
        status (rather than via a dedicated enum property).
        """
        return any(self._cyclonedx_component_has_milestone(component, name) for name in self._STATUS_MILESTONES)

    def _cyclonedx_has_legacy_status_property(self, component: dict[str, Any]) -> bool:
        """Recognise the deprecated cdx:cle:supportStatus property for
        backward compatibility. Value must be a valid CLE status enum."""
        for prop in component.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            if prop.get("name") != self._LEGACY_STATUS_PROP:
                continue
            value = prop.get("value", "")
            if isinstance(value, str) and value.strip().lower() in CLE_SUPPORT_STATUS_VALUES:
                return True
        return False

    def _cyclonedx_has_legacy_eos_property(self, component: dict[str, Any]) -> bool:
        """Recognise the deprecated cdx:cle:endOfSupport property for
        backward compatibility. Any non-empty value counts."""
        for prop in component.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            if prop.get("name") != self._LEGACY_EOS_PROP:
                continue
            value = prop.get("value", "")
            if isinstance(value, str) and value.strip():
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

        finding_id = self.NTIA_FINDING_IDS.get(element) or self.FDA_FINDING_IDS.get(element) or element

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
