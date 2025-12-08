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

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Set, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NTIAComplianceStatus(str, Enum):
    """NTIA compliance status enumeration."""

    COMPLIANT = "compliant"
    PARTIAL = "partial"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"


class NTIACheckStatus(str, Enum):
    """Status for an individual NTIA check."""

    PASS = "pass"  # nosec
    WARNING = "warning"
    FAIL = "fail"
    UNKNOWN = "unknown"


class NTIASection(str, Enum):
    """High-level NTIA minimum element pillars."""

    DATA_FIELDS = "data_fields"
    AUTOMATION_SUPPORT = "automation_support"
    PRACTICES_PROCESSES = "practices_and_processes"


class NTIAValidationError(BaseModel):
    """Model for NTIA validation errors."""

    field: str = Field(..., description="The NTIA field that failed validation")
    message: str = Field(..., description="Human-readable error message")
    suggestion: str = Field(..., description="Suggestion for fixing the issue")


class NTIACheckResult(BaseModel):
    """Result for a single NTIA element check."""

    element: str = Field(..., description="Identifier for the NTIA element (e.g., supplier_name)")
    title: str = Field(..., description="Human-friendly check title")
    status: NTIACheckStatus = Field(..., description="Outcome of the check")
    message: str = Field(..., description="Details about the check result")
    suggestion: Optional[str] = Field(default=None, description="Recommended remediation when status is warning/fail")
    affected: List[str] = Field(default_factory=list, description="Affected components/items")


class NTIASectionResult(BaseModel):
    """Group of checks for one NTIA pillar."""

    name: NTIASection
    title: str
    summary: str
    checks: List[NTIACheckResult] = Field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(check.status == NTIACheckStatus.FAIL for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status == NTIACheckStatus.WARNING for check in self.checks)


class NTIAValidationResult(BaseModel):
    """Model for NTIA validation results."""

    is_compliant: bool = Field(..., description="Whether the SBOM is NTIA compliant")
    status: NTIAComplianceStatus = Field(..., description="Overall compliance status")
    errors: List[NTIAValidationError] = Field(default_factory=list, description="List of validation errors")
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sections: List[NTIASectionResult] = Field(default_factory=list, description="Detailed section results")

    @property
    def error_count(self) -> int:
        """Return the number of validation errors."""
        return len(self.errors)

    @property
    def warnings(self) -> List[NTIACheckResult]:
        warnings: List[NTIACheckResult] = []
        for section in self.sections:
            warnings.extend(check for check in section.checks if check.status == NTIACheckStatus.WARNING)
        return warnings


def _normalise_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _is_placeholder(value: Optional[str]) -> bool:
    if value is None:
        return True
    upper = value.strip().upper()
    return upper in {"", "UNKNOWN", "NOASSERTION", "NONE", "TBD", "N/A"}


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Ensure timezone aware, default to UTC when absent
        normalised = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalised)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extract_emails(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [match.group(0) for match in _EMAIL_PATTERN.finditer(str(value))]


def _normalize_spdx_actor(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    actor = str(value).strip()
    if ":" in actor:
        _, actor = actor.split(":", 1)
        actor = actor.strip()
    if _is_placeholder(actor):
        return None
    return _normalise_label(actor)


def _flatten(items: Iterable[Iterable[str]]) -> List[str]:
    flattened: List[str] = []
    for group in items:
        for entry in group:
            flattened.append(entry)
    return flattened


def _format_hash_entry(hash_entry: Dict[str, Any]) -> Optional[str]:
    value = hash_entry.get("content") or hash_entry.get("value")
    if not value:
        return None

    algorithm = str(hash_entry.get("alg") or hash_entry.get("algorithm") or "").upper()
    return f"{algorithm}:{value}"


@dataclass
class NormalizedComponent:
    """Unified representation of an SBOM component/package."""

    ref: Optional[str]
    name: str
    supplier: Optional[str]
    version: Optional[str]
    identifiers: Set[str] = field(default_factory=set)
    global_identifiers: Set[str] = field(default_factory=set)
    hashes: Set[str] = field(default_factory=set)
    name_placeholder: bool = False

    def label(self) -> str:
        if self.name and not self.name.startswith("Component "):
            return self.name
        if self.ref:
            return self.ref
        return self.name or "<unknown>"

    def has_supplier(self) -> bool:
        return not _is_placeholder(self.supplier)

    def has_version(self) -> bool:
        return not _is_placeholder(self.version)

    def has_global_identifier(self) -> bool:
        return bool(self.global_identifiers)

    def has_any_identifier(self) -> bool:
        return bool(self.identifiers or self.global_identifiers or self.hashes)


@dataclass
class NormalizedSBOM:
    """Shared SBOM representation used for NTIA evaluation."""

    format: str
    spec_version: Optional[str]
    components: List[NormalizedComponent] = field(default_factory=list)
    dependencies: Dict[str, Set[str]] = field(default_factory=dict)
    authors: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    creation_timestamp: Optional[datetime] = None
    document_name: Optional[str] = None
    document_describes: List[str] = field(default_factory=list)
    metadata_component_ref: Optional[str] = None
    external_references: List[str] = field(default_factory=list)
    properties: Dict[str, str] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def component_labels(self, components: Iterable[NormalizedComponent]) -> List[str]:
        return [component.label() for component in components]

    @property
    def component_count(self) -> int:
        return len(self.components)

    def components_missing_supplier(self) -> List[NormalizedComponent]:
        return [component for component in self.components if not component.has_supplier()]

    def components_with_placeholder_supplier(self) -> List[NormalizedComponent]:
        return [
            component
            for component in self.components
            if component.supplier is not None and _is_placeholder(component.supplier)
        ]

    def components_missing_version(self) -> List[NormalizedComponent]:
        return [component for component in self.components if not component.has_version()]

    def components_with_placeholder_version(self) -> List[NormalizedComponent]:
        return [
            component
            for component in self.components
            if component.version is not None and _is_placeholder(component.version)
        ]

    def components_missing_identifiers(self) -> List[NormalizedComponent]:
        return [component for component in self.components if not component.has_any_identifier()]

    def components_missing_global_identifiers(self) -> List[NormalizedComponent]:
        return [component for component in self.components if not component.has_global_identifier()]

    def dependency_edges(self) -> int:
        return sum(len(targets) for targets in self.dependencies.values())

    def has_dependency_graph(self) -> bool:
        return bool(self.dependencies)

    def components_without_dependencies(self) -> List[str]:
        refs_with_deps = {ref for ref, targets in self.dependencies.items() if targets}
        components_without = []
        for component in self.components:
            ref = component.ref or component.name
            if not ref:
                continue
            if ref not in refs_with_deps and not any(ref in targets for targets in self.dependencies.values()):
                components_without.append(component.label())
        return components_without


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
        sbom_format_normalized = (sbom_format or "").lower()
        if sbom_format_normalized not in {"spdx", "cyclonedx"}:
            error = NTIAValidationError(
                field="format",
                message=f"Unsupported SBOM format: {sbom_format}",
                suggestion="Use SPDX or CycloneDX SBOM formats for NTIA validation.",
            )
            return NTIAValidationResult(is_compliant=False, status=NTIAComplianceStatus.NON_COMPLIANT, errors=[error])

        self.logger.info("Starting NTIA validation for %s SBOM", sbom_format_normalized.upper())

        try:
            normalized = self._normalize_sbom(sbom_data, sbom_format_normalized)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.exception("Failed to normalise SBOM for NTIA validation: %s", exc)
            error = NTIAValidationError(
                field="validation",
                message=f"Validation failed due to error: {exc}",
                suggestion="Ensure the SBOM conforms to the SPDX or CycloneDX specification.",
            )
            return NTIAValidationResult(is_compliant=False, status=NTIAComplianceStatus.UNKNOWN, errors=[error])

        sections: List[NTIASectionResult] = [
            self._evaluate_data_fields(normalized),
            self._evaluate_automation_support(normalized),
            self._evaluate_practices_and_processes(normalized),
        ]

        field_aliases = {
            "supplier_name": "supplier",
            "component_name": "component_name",
            "component_version": "version",
            "unique_identifiers": "unique_id",
            "dependency_relationships": "dependencies",
            "sbom_author": "sbom_author",
            "timestamp": "timestamp",
        }

        errors: List[NTIAValidationError] = []
        for section in sections:
            for check in section.checks:
                if check.status == NTIACheckStatus.FAIL:
                    alias_field = field_aliases.get(check.element, check.element or "unknown")
                    errors.append(
                        NTIAValidationError(
                            field=alias_field,
                            message=check.message,
                            suggestion=check.suggestion or "Refer to NTIA guidance for remediation.",
                        )
                    )

        has_failures = any(section.has_failures for section in sections)
        has_warnings = any(section.has_warnings for section in sections)

        if has_failures:
            status = NTIAComplianceStatus.NON_COMPLIANT
            is_compliant = False
        elif has_warnings:
            status = NTIAComplianceStatus.PARTIAL
            is_compliant = False
        else:
            status = NTIAComplianceStatus.COMPLIANT
            is_compliant = True

        self.logger.info(
            "NTIA validation completed. Status: %s. Components: %d. Errors: %d",
            status.value,
            normalized.component_count,
            len(errors),
        )

        return NTIAValidationResult(
            is_compliant=is_compliant,
            status=status,
            errors=errors,
            sections=sections,
        )

    # Normalisation
    def _normalize_sbom(self, sbom_data: Dict[str, Any], sbom_format: str) -> NormalizedSBOM:
        sbom_format = (sbom_format or "").lower()
        if sbom_format not in {"spdx", "cyclonedx"}:
            raise ValueError(f"Unsupported SBOM format: {sbom_format}")

        if sbom_format == "cyclonedx":
            return self._normalize_cyclonedx(sbom_data)
        return self._normalize_spdx(sbom_data)

    def _normalize_cyclonedx(self, data: Dict[str, Any]) -> NormalizedSBOM:
        components: List[NormalizedComponent] = []
        for index, component in enumerate(data.get("components", []) or []):
            supplier = None
            if isinstance(component.get("supplier"), dict):
                supplier = component["supplier"].get("name") or component["supplier"].get("contact")
            elif component.get("supplier"):
                supplier = component.get("supplier")
            supplier = supplier or component.get("publisher") or component.get("manufacturer", {}).get("name")

            identifiers: Set[str] = set()
            global_ids: Set[str] = set()

            bom_ref = component.get("bom-ref") or component.get("bomRef")
            if bom_ref:
                identifiers.add(bom_ref)
            if component.get("serialNumber"):
                identifiers.add(component["serialNumber"])

            raw_name = component.get("name")
            normalized_name = _normalise_label(raw_name)
            name_placeholder = False
            if not normalized_name:
                normalized_name = f"Component {index + 1}"
                name_placeholder = True
            elif _is_placeholder(normalized_name):
                name_placeholder = True

            purl = component.get("purl")
            if purl:
                identifiers.add(purl)
                global_ids.add(purl)

            cpe = component.get("cpe")
            if cpe:
                identifiers.add(cpe)
                global_ids.add(cpe)

            swid = component.get("swid")
            if isinstance(swid, dict):
                for key in ("tagId", "uniqueId"):
                    if swid.get(key):
                        identifiers.add(swid[key])
                        global_ids.add(swid[key])

            for ext in component.get("externalReferences", []) or []:
                ref_type = str(ext.get("type", "")).lower()
                url = ext.get("url") or ext.get("referenceLocator")
                if url:
                    identifiers.add(url)
                    if ref_type in {"purl", "cpe22uri", "cpe23uri", "swid", "vcs", "distribution", "other"}:
                        global_ids.add(url)

            hashes: Set[str] = set()
            for hash_entry in component.get("hashes", []) or []:
                formatted_hash = _format_hash_entry(hash_entry)
                if formatted_hash:
                    hashes.add(formatted_hash)
            if hashes:
                global_ids.update(hashes)

            components.append(
                NormalizedComponent(
                    ref=bom_ref,
                    name=normalized_name,
                    supplier=_normalise_label(supplier),
                    version=_normalise_label(component.get("version")),
                    identifiers=identifiers,
                    global_identifiers=global_ids,
                    hashes=hashes,
                    name_placeholder=name_placeholder,
                )
            )

        dependencies: Dict[str, Set[str]] = {}
        for dependency in data.get("dependencies", []) or []:
            raw_ref = dependency.get("ref") or dependency.get("reference")
            if isinstance(raw_ref, dict):
                ref = (
                    raw_ref.get("ref")
                    or raw_ref.get("bom-ref")
                    or raw_ref.get("bomRef")
                    or raw_ref.get("value")
                    or raw_ref.get("spdxElementId")
                )
            else:
                ref = raw_ref
            depends_on = dependency.get("dependsOn") or dependency.get("depends_on") or []
            if ref:
                ref = str(ref)
                normalised_targets: Set[str] = set()
                for target in depends_on:
                    if isinstance(target, dict):
                        target_ref = (
                            target.get("ref")
                            or target.get("bom-ref")
                            or target.get("bomRef")
                            or target.get("value")
                            or target.get("spdxElementId")
                        )
                        if target_ref:
                            normalised_targets.add(str(target_ref))
                    else:
                        normalised_targets.add(str(target))
                dependencies.setdefault(ref, set()).update(normalised_targets)

        metadata = data.get("metadata", {}) or {}
        authors = []
        contacts = []
        for author in metadata.get("authors", []) or []:
            if isinstance(author, dict):
                composed = " ".join(filter(None, [author.get("name"), author.get("email")]))
                if author.get("email"):
                    contacts.append(author.get("email"))
                if composed:
                    authors.append(composed)
            elif isinstance(author, str):
                authors.append(author)

        tools = []
        for tool in metadata.get("tools", []) or []:
            if isinstance(tool, dict):
                components_bits = [tool.get("vendor"), tool.get("name"), tool.get("version")]
                tool_label = " ".join(bit for bit in components_bits if bit)
                if tool_label:
                    tools.append(tool_label)
            elif isinstance(tool, str):
                tools.append(tool)

        timestamp = _parse_iso_timestamp(metadata.get("timestamp"))

        metadata_component = metadata.get("component") or {}
        metadata_component_ref = metadata_component.get("bom-ref") or metadata_component.get("bomRef")

        properties = {}
        for prop in metadata.get("properties", []) or []:
            name = prop.get("name")
            value = prop.get("value")
            if name and value:
                properties[str(name)] = str(value)

        external_refs = []
        for ref in metadata.get("externalReferences", []) or []:
            reference = ref.get("url") or ref.get("referenceLocator")
            if reference:
                external_refs.append(reference)

        return NormalizedSBOM(
            format="cyclonedx",
            spec_version=_normalise_label(data.get("specVersion")),
            components=components,
            dependencies=dependencies,
            authors=authors,
            contacts=contacts,
            tools=tools,
            creation_timestamp=timestamp,
            document_name=_normalise_label(metadata_component.get("name") or data.get("metadata", {}).get("name")),
            document_describes=[metadata_component_ref] if metadata_component_ref else [],
            metadata_component_ref=metadata_component_ref,
            external_references=external_refs,
            properties=properties,
            raw=data,
        )

    def _normalize_spdx(self, data: Dict[str, Any]) -> NormalizedSBOM:
        packages: List[NormalizedComponent] = []
        document_ref = str(data.get("SPDXID") or data.get("spdxId") or "SPDXRef-DOCUMENT")
        supplier_contacts: Set[str] = set()

        for index, package in enumerate(data.get("packages", []) or []):
            supplier_raw = package.get("supplier") or package.get("originator")
            supplier = _normalize_spdx_actor(supplier_raw)
            supplier_contacts.update(_extract_emails(supplier_raw))

            version = package.get("versionInfo") or package.get("version")
            spdx_id = package.get("SPDXID") or package.get("spdxid")

            raw_name = package.get("name")
            normalized_name = _normalise_label(raw_name)
            name_placeholder = False
            if not normalized_name:
                normalized_name = f"Package {index + 1}"
                name_placeholder = True
            elif _is_placeholder(normalized_name):
                name_placeholder = True

            identifiers: Set[str] = set()
            global_ids: Set[str] = set()

            if spdx_id:
                identifiers.add(spdx_id)

            name_aliases = package.get("externalRefs", []) or []
            download_location = package.get("downloadLocation")
            homepage = package.get("homepage")
            for candidate in [download_location, homepage]:
                if candidate and not _is_placeholder(candidate):
                    identifiers.add(candidate)
                    if str(candidate).startswith(("http://", "https://", "pkg:", "cpe:", "git", "ssh://")):
                        global_ids.add(candidate)

            purl = package.get("purl")
            if purl:
                identifiers.add(purl)
                global_ids.add(purl)

            # SPDX external references
            for ext in name_aliases:
                reference_locator = ext.get("referenceLocator") or ext.get("referenceType")
                if reference_locator:
                    identifiers.add(reference_locator)
                reference_type = (ext.get("referenceType") or "").lower()
                if reference_type in {"purl", "cpe22type", "cpe23type", "swid"} and reference_locator:
                    global_ids.add(reference_locator)
                if reference_type in {"website", "distribution", "vcs"} and reference_locator:
                    global_ids.add(reference_locator)

            verification = package.get("packageVerificationCode", {})
            if isinstance(verification, dict):
                value = verification.get("packageVerificationCodeValue")
                if value:
                    identifiers.add(value)

            hashes = {
                f"{checksum.get('algorithm', '').upper()}:{checksum.get('checksumValue')}"
                for checksum in package.get("checksums", []) or []
                if checksum.get("checksumValue")
            }
            if hashes:
                global_ids.update(hashes)

            packages.append(
                NormalizedComponent(
                    ref=spdx_id,
                    name=normalized_name,
                    supplier=supplier,
                    version=_normalise_label(version),
                    identifiers=identifiers,
                    global_identifiers=global_ids,
                    hashes=hashes,
                    name_placeholder=name_placeholder,
                )
            )

        file_hashes: Set[str] = set()
        for file_entry in data.get("files", []) or []:
            for checksum in file_entry.get("checksums", []) or []:
                algorithm = (checksum.get("algorithm") or "").upper()
                value = checksum.get("checksumValue")
                if algorithm and value:
                    file_hashes.add(f"{algorithm}:{value}")

        if file_hashes:
            for pkg in packages:
                if not pkg.has_global_identifier():
                    pkg.global_identifiers.update(file_hashes)
                    pkg.hashes.update(file_hashes)

        relationships: Dict[str, Set[str]] = {}
        dependency_mappings = {
            "depends_on": "forward",
            "dependency_of": "reverse",
            "prerequisite_for": "forward",
            "prerequisite_of": "reverse",
            "contains": "forward",
            "contained_by": "reverse",
            "describes": "forward",
            "described_by": "reverse",
            "generated_from": "forward",
            "generates": "reverse",
            "data_file_of": "reverse",
            "test_of": "reverse",
            "testcase_of": "reverse",
            "optional_component_of": "reverse",
            "optional_dependency_of": "reverse",
            "build_dependency_of": "reverse",
            "dev_dependency_of": "reverse",
            "provided_dependency_of": "reverse",
            "runtime_dependency_of": "reverse",
            "example_of": "reverse",
            "variant_of": "reverse",
            "ancestor_of": "forward",
            "descendant_of": "reverse",
            "static_link": "forward",
            "dynamic_link": "forward",
            "dependency_manifest_of": "reverse",
            "patch_for": "forward",
            "patch_applied_to": "reverse",
            "expanded_from_archive": "forward",
        }

        for relation in data.get("relationships", []) or []:
            rel_type = str(relation.get("relationshipType", "")).lower()
            source = relation.get("spdxElementId") or relation.get("source")
            target = relation.get("relatedSpdxElement") or relation.get("target")
            if not source or not target:
                continue

            src = str(source)
            tgt = str(target)

            direction = dependency_mappings.get(rel_type)

            if isinstance(target, list):
                targets = {str(t) for t in target if t}
            else:
                targets = {tgt}

            if direction == "forward":
                relationships.setdefault(src, set()).update(targets)
            elif direction == "reverse":
                for single_target in targets:
                    relationships.setdefault(single_target, set()).add(src)
            elif rel_type in {"uses", "requires"}:
                relationships.setdefault(src, set()).update(targets)
            elif rel_type in {"used_by", "required_by"}:
                for single_target in targets:
                    relationships.setdefault(single_target, set()).add(src)

        creation_info = data.get("creationInfo", {}) or {}
        creators = creation_info.get("creators", []) or []
        authors: List[str] = []
        tools: List[str] = []
        contacts: List[str] = []
        for creator in creators:
            if not isinstance(creator, str):
                continue
            if ":" in creator:
                prefix, value = creator.split(":", 1)
                prefix = prefix.strip().lower()
                value = value.strip()
                if prefix == "tool":
                    tools.append(value)
                else:
                    authors.append(value)
            else:
                authors.append(creator)
            if "<" in creator and ">" in creator:
                email = creator.split("<", 1)[1].split(">", 1)[0]
                contacts.append(email)

        contacts.extend(sorted(supplier_contacts))
        contacts = list(dict.fromkeys(email for email in contacts if email))
        timestamp = _parse_iso_timestamp(creation_info.get("created"))

        properties = {}
        for annotation in data.get("annotations", []) or []:
            comment = annotation.get("comment")
            if comment and ":" in comment:
                key, value = comment.split(":", 1)
                properties[key.strip()] = value.strip()

        document_describes = data.get("documentDescribes", []) or []
        describe_targets = [str(entry) for entry in document_describes if entry]
        if describe_targets:
            relationships.setdefault(document_ref, set()).update(describe_targets)

        external_refs: List[str] = []
        for doc_ref in data.get("externalDocumentRefs", []) or []:
            if doc_ref.get("uri"):
                external_refs.append(doc_ref["uri"])

        document_name = _normalise_label(data.get("name") or creation_info.get("comment"))

        spec_version_raw = data.get("specVersion") or data.get("spdxVersion")
        spec_version = None
        if spec_version_raw:
            spec_version_str = str(spec_version_raw).strip()
            if spec_version_str.upper().startswith("SPDX-"):
                spec_version_str = spec_version_str.split("-", 1)[1]
            spec_version = _normalise_label(spec_version_str)

        if data.get("documentNamespace"):
            properties["document_namespace"] = str(data.get("documentNamespace"))
        if data.get("dataLicense") and not _is_placeholder(data.get("dataLicense")):
            properties["data_license"] = str(data.get("dataLicense"))
        if creation_info.get("comment"):
            properties["creation_comment"] = creation_info.get("comment")

        return NormalizedSBOM(
            format="spdx",
            spec_version=spec_version,
            components=packages,
            dependencies=relationships,
            authors=authors,
            contacts=contacts,
            tools=tools,
            creation_timestamp=timestamp,
            document_name=document_name,
            document_describes=[str(entry) for entry in document_describes],
            metadata_component_ref=document_describes[0] if document_describes else None,
            external_references=external_refs,
            properties=properties,
            raw=data,
        )

    # Evaluation helpers
    def _evaluate_data_fields(self, sbom: NormalizedSBOM) -> NTIASectionResult:
        checks: List[NTIACheckResult] = []

        missing_supplier = sbom.components_missing_supplier()
        placeholder_supplier = sbom.components_with_placeholder_supplier()

        if missing_supplier:
            checks.append(
                NTIACheckResult(
                    element="supplier_name",
                    title="Supplier name recorded",
                    status=NTIACheckStatus.FAIL,
                    message="Some components are missing supplier information.",
                    suggestion="Provide supplier or publisher information for each component.",
                    affected=sbom.component_labels(missing_supplier),
                )
            )
        elif placeholder_supplier:
            checks.append(
                NTIACheckResult(
                    element="supplier_name",
                    title="Supplier name recorded",
                    status=NTIACheckStatus.WARNING,
                    message="Some components list supplier as NOASSERTION/UNKNOWN.",
                    suggestion="Where possible, replace placeholder supplier values with the actual organization.",
                    affected=sbom.component_labels(placeholder_supplier),
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="supplier_name",
                    title="Supplier name recorded",
                    status=NTIACheckStatus.PASS,
                    message="Supplier information is present for all components.",
                )
            )

        missing_name = [component for component in sbom.components if component.name_placeholder]
        if sbom.document_name and not _is_placeholder(sbom.document_name):
            missing_name = [component for component in missing_name if component.name != sbom.document_name]
        if missing_name:
            checks.append(
                NTIACheckResult(
                    element="component_name",
                    title="Component name recorded",
                    status=NTIACheckStatus.FAIL,
                    message="Some components are missing a human-readable name.",
                    suggestion="Provide a descriptive component name for each entry.",
                    affected=sbom.component_labels(missing_name),
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="component_name",
                    title="Component name recorded",
                    status=NTIACheckStatus.PASS,
                    message="Component names are present.",
                )
            )

        missing_version = sbom.components_missing_version()
        placeholder_version = sbom.components_with_placeholder_version()

        if missing_version:
            checks.append(
                NTIACheckResult(
                    element="component_version",
                    title="Component version recorded",
                    status=NTIACheckStatus.FAIL,
                    message="Some components are missing version information.",
                    suggestion="Provide explicit version information for each component."
                    + "Use NOASSERTION only when necessary.",
                    affected=sbom.component_labels(missing_version),
                )
            )
        elif placeholder_version:
            checks.append(
                NTIACheckResult(
                    element="component_version",
                    title="Component version recorded",
                    status=NTIACheckStatus.WARNING,
                    message="Some components list version as NOASSERTION/UNKNOWN.",
                    suggestion="Where possible, replace placeholder version values with"
                    + "the resolved component version.",
                    affected=sbom.component_labels(placeholder_version),
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="component_version",
                    title="Component version recorded",
                    status=NTIACheckStatus.PASS,
                    message="Version metadata is present for all components.",
                )
            )

        missing_identifiers = sbom.components_missing_identifiers()
        missing_global_identifiers = sbom.components_missing_global_identifiers()

        if missing_identifiers:
            checks.append(
                NTIACheckResult(
                    element="unique_identifiers",
                    title="Unique identifiers present",
                    status=NTIACheckStatus.FAIL,
                    message="Some components do not include any unique identifier or checksum.",
                    suggestion="Include package URLs (PURL), CPEs, SWID tags, or file hashes for each component.",
                    affected=sbom.component_labels(missing_identifiers),
                )
            )
        elif missing_global_identifiers:
            status = (
                NTIACheckStatus.FAIL
                if len(missing_global_identifiers) == sbom.component_count
                else NTIACheckStatus.WARNING
            )
            checks.append(
                NTIACheckResult(
                    element="unique_identifiers",
                    title="Unique identifiers present",
                    status=status,
                    message="Some components do not include globally resolvable identifiers (PURL, CPE, SWID, hashes).",
                    suggestion="Add global identifiers such as PURL, CPE, SWID tags, or \
                                    file hashes to improve traceability.",
                    affected=sbom.component_labels(missing_global_identifiers),
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="unique_identifiers",
                    title="Unique identifiers present",
                    status=NTIACheckStatus.PASS,
                    message="All components include globally useful identifiers.",
                )
            )

        total_edges = sbom.dependency_edges()
        if sbom.component_count <= 1:
            if sbom.has_dependency_graph():
                dependency_status = NTIACheckStatus.PASS
                dependency_message = "Dependency relationships are captured."
                dependency_suggestion = None
                affected = []
            else:
                dependency_status = NTIACheckStatus.FAIL
                dependency_message = "No dependency relationships are recorded between components."
                dependency_suggestion = "Populate the dependency graph (dependsOn/relationships) so that \
                                            consumers understand component linkages."
                affected = sbom.component_labels(sbom.components)
        elif not sbom.has_dependency_graph() or total_edges == 0:
            dependency_status = NTIACheckStatus.FAIL
            dependency_message = "No dependency relationships are recorded between components."
            dependency_suggestion = "Populate the dependency graph (dependsOn/relationships) so that \
                                        consumers understand component linkages."
            affected = sbom.component_labels(sbom.components)
        else:
            orphan_components = sbom.components_without_dependencies()
            if orphan_components and len(orphan_components) == sbom.component_count:
                dependency_status = NTIACheckStatus.FAIL
                dependency_message = "Dependency mapping exists but no components are linked together."
                dependency_suggestion = (
                    "Review dependency relationships to ensure components reference their direct dependencies."
                )
            elif orphan_components:
                dependency_status = NTIACheckStatus.WARNING
                dependency_message = "Some components are not part of the dependency graph."
                dependency_suggestion = (
                    "Ensure each component either depends on or is depended upon by another component when applicable."
                )
            else:
                dependency_status = NTIACheckStatus.PASS
                dependency_message = "Dependency relationships are captured."
                dependency_suggestion = None
            affected = orphan_components if dependency_status != NTIACheckStatus.PASS else []

        checks.append(
            NTIACheckResult(
                element="dependency_relationships",
                title="Dependency relationships captured",
                status=dependency_status,
                message=dependency_message,
                suggestion=dependency_suggestion,
                affected=affected,
            )
        )

        if sbom.authors or sbom.tools:
            checks.append(
                NTIACheckResult(
                    element="sbom_author",
                    title="Author of SBOM data recorded",
                    status=NTIACheckStatus.PASS,
                    message="Creator information is present.",
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="sbom_author",
                    title="Author of SBOM data recorded",
                    status=NTIACheckStatus.FAIL,
                    message="SBOM author/creator information is missing.",
                    suggestion="Include creator details or tool metadata (creationInfo.creators / metadata.authors).",
                )
            )

        if sbom.creation_timestamp:
            checks.append(
                NTIACheckResult(
                    element="timestamp",
                    title="Timestamp recorded",
                    status=NTIACheckStatus.PASS,
                    message=f"SBOM creation timestamp: {sbom.creation_timestamp.isoformat()}",
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="timestamp",
                    title="Timestamp recorded",
                    status=NTIACheckStatus.FAIL,
                    message="SBOM creation timestamp is missing or not in valid ISO-8601 format.",
                    suggestion="Provide an ISO-8601 timestamp in metadata.timestamp or creationInfo.created.",
                )
            )

        summary = f"Validated {sbom.component_count} components."

        return NTIASectionResult(
            name=NTIASection.DATA_FIELDS,
            title="Data Fields",
            summary=summary,
            checks=checks,
        )

    def _evaluate_automation_support(self, sbom: NormalizedSBOM) -> NTIASectionResult:
        checks: List[NTIACheckResult] = []

        checks.append(
            NTIACheckResult(
                element="machine_readable",
                title="SBOM is machine-readable",
                status=NTIACheckStatus.PASS,
                message="SBOM was parsed successfully, confirming machine-readable format.",
            )
        )

        checks.append(
            NTIACheckResult(
                element="standard_format",
                title="Uses a standard SBOM format",
                status=NTIACheckStatus.PASS,
                message=f"Format detected: {sbom.format.upper()} {sbom.spec_version or ''}".strip(),
            )
        )

        if sbom.tools or sbom.authors:
            checks.append(
                NTIACheckResult(
                    element="tooling_metadata",
                    title="Tooling metadata recorded",
                    status=NTIACheckStatus.PASS,
                    message="SBOM lists tooling/authoring metadata.",
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="tooling_metadata",
                    title="Tooling metadata recorded",
                    status=NTIACheckStatus.WARNING,
                    message="No tooling or creator metadata detected.",
                    suggestion="Include tool details or creator metadata used to generate the SBOM.",
                )
            )

        if sbom.component_count > 0:
            components_with_refs = sum(1 for component in sbom.components if component.ref)
            if components_with_refs == 0:
                checks.append(
                    NTIACheckResult(
                        element="component_references",
                        title="Component references support automation",
                        status=NTIACheckStatus.PASS,
                        message="Component references (bom-ref/SPDXID) not supplied; add them to improve traceability.",
                        suggestion="Define bom-ref or SPDXID values for components to "
                        + "enable automated dependency resolution.",
                    )
                )
            else:
                checks.append(
                    NTIACheckResult(
                        element="component_references",
                        title="Component references support automation",
                        status=NTIACheckStatus.PASS,
                        message=f"{components_with_refs} of {sbom.component_count} components"
                        + "include bom-ref/SPDXID references.",
                    )
                )

        if sbom.has_dependency_graph():
            checks.append(
                NTIACheckResult(
                    element="automation_dependency_graph",
                    title="Dependency graph available",
                    status=NTIACheckStatus.PASS,
                    message="Dependency graph entries were detected.",
                )
            )
        else:
            checks.append(
                NTIACheckResult(
                    element="automation_dependency_graph",
                    title="Dependency graph available",
                    status=NTIACheckStatus.WARNING,
                    message="Dependency graph is empty.",
                    suggestion="Populate dependency relationships to improve automated impact analysis workflows.",
                )
            )

        summary = "Automation support metrics evaluated."
        return NTIASectionResult(
            name=NTIASection.AUTOMATION_SUPPORT,
            title="Automation Support",
            summary=summary,
            checks=checks,
        )

    def _evaluate_practices_and_processes(self, sbom: NormalizedSBOM) -> NTIASectionResult:
        checks: List[NTIACheckResult] = []
        if sbom.creation_timestamp:
            status = NTIACheckStatus.PASS
            message = "SBOM includes creation timestamp metadata."
            suggestion = None
        else:
            status = NTIACheckStatus.UNKNOWN
            message = "Unable to determine SBOM age without timestamp."
            suggestion = "Include an ISO-8601 timestamp to support freshness checks."

        checks.append(
            NTIACheckResult(
                element="update_frequency",
                title="SBOM update cadence",
                status=status,
                message=message,
                suggestion=suggestion,
            )
        )

        depth_status = NTIACheckStatus.PASS
        depth_message = "Component coverage evaluated via metadata checks."
        depth_suggestion = None

        checks.append(
            NTIACheckResult(
                element="sbom_depth",
                title="SBOM depth and completeness",
                status=depth_status,
                message=depth_message,
                suggestion=depth_suggestion,
            )
        )

        if sbom.contacts or sbom.properties.get("distribution") or sbom.external_references:
            distribution_status = NTIACheckStatus.PASS
            distribution_message = "Distribution/contact information detected for SBOM consumers."
            distribution_suggestion = None
        else:
            distribution_status = NTIACheckStatus.UNKNOWN
            distribution_message = "No distribution or contact metadata provided."
            distribution_suggestion = "Include distribution details to support SBOM delivery."

        checks.append(
            NTIACheckResult(
                element="distribution_practices",
                title="Distribution and communication practices",
                status=distribution_status,
                message=distribution_message,
                suggestion=distribution_suggestion,
            )
        )

        summary = "Evaluated organisational practices based on available metadata."
        return NTIASectionResult(
            name=NTIASection.PRACTICES_PROCESSES,
            title="Practices & Processes",
            summary=summary,
            checks=checks,
        )

    def _evaluate_sbomqs_ntia(self, sbom: NormalizedSBOM) -> NTIAValidationResult:
        """
        NTIA validation aligned with sbomqs: checks author, timestamp, dependencies, and per-component fields.
        """
        checks: List[NTIACheckResult] = []
        errors: List[NTIAValidationError] = []

        # Automation support: requires SPDX or CycloneDX
        if sbom.format.lower() in {"cyclonedx", "spdx"}:
            checks.append(
                NTIACheckResult(
                    element="automation_support",
                    title="Automation support",
                    status=NTIACheckStatus.PASS,
                    message=f"{sbom.format} {sbom.spec_version or ''}".strip(),
                )
            )
        else:
            msg = f"Unsupported SBOM format: {sbom.format}"
            checks.append(
                NTIACheckResult(
                    element="automation_support",
                    title="Automation support",
                    status=NTIACheckStatus.FAIL,
                    message=msg,
                    suggestion="Provide CycloneDX or SPDX in a machine-readable format.",
                )
            )
            errors.append(
                NTIAValidationError(field="automation_support", message=msg, suggestion="Use CycloneDX/SPDX.")
            )

        # Timestamp
        if sbom.creation_timestamp:
            checks.append(
                NTIACheckResult(
                    element="timestamp",
                    title="Creation timestamp",
                    status=NTIACheckStatus.PASS,
                    message=sbom.creation_timestamp.isoformat(),
                )
            )
        else:
            msg = "Missing creation timestamp"
            checks.append(
                NTIACheckResult(
                    element="timestamp",
                    title="Creation timestamp",
                    status=NTIACheckStatus.FAIL,
                    message=msg,
                    suggestion="Include creationInfo.created or metadata.timestamp.",
                )
            )
            errors.append(NTIAValidationError(field="timestamp", message=msg, suggestion="Add created timestamp."))

        # Author/creator/tool (doc-level)
        if sbom.authors or sbom.tools or sbom.contacts:
            checks.append(
                NTIACheckResult(
                    element="author",
                    title="Author/creator",
                    status=NTIACheckStatus.PASS,
                    message="Author, supplier, or tool details present.",
                )
            )
        else:
            msg = "Author/creator details not found"
            checks.append(
                NTIACheckResult(
                    element="author",
                    title="Author/creator",
                    status=NTIACheckStatus.FAIL,
                    message=msg,
                    suggestion="Include authors/tools or supplier/manufacturer details.",
                )
            )
            errors.append(NTIAValidationError(field="author", message=msg, suggestion="Add author/tool metadata."))

        # Dependency relationships
        has_dependencies = any(deps for deps in sbom.dependencies.values())
        if has_dependencies:
            checks.append(
                NTIACheckResult(
                    element="dependency_relationship",
                    title="Dependency relationships",
                    status=NTIACheckStatus.PASS,
                    message="Dependency graph present.",
                )
            )
        else:
            msg = "No dependency relationships recorded"
            checks.append(
                NTIACheckResult(
                    element="dependency_relationship",
                    title="Dependency relationships",
                    status=NTIACheckStatus.FAIL,
                    message=msg,
                    suggestion="Provide relationships/dependsOn for components.",
                )
            )
            errors.append(
                NTIAValidationError(
                    field="dependency_relationship", message=msg, suggestion="Add dependency relationships."
                )
            )

        # Component-level checks
        missing_names: List[str] = []
        missing_suppliers: List[str] = []
        missing_versions: List[str] = []
        missing_ids: List[str] = []

        for component in sbom.components:
            label = component.label()
            if _is_placeholder(component.name):
                missing_names.append(label)
            if not component.has_supplier():
                missing_suppliers.append(label)
            if not component.has_version():
                missing_versions.append(label)
            if not component.has_any_identifier():
                missing_ids.append(label)

        def add_component_issue(element: str, title: str, affected: List[str], suggestion: str):
            nonlocal errors, checks
            if not affected:
                checks.append(
                    NTIACheckResult(
                        element=element, title=title, status=NTIACheckStatus.PASS, message="All components populated."
                    )
                )
                return
            msg = f"{len(affected)} component(s) missing {title.lower()}"
            checks.append(
                NTIACheckResult(
                    element=element,
                    title=title,
                    status=NTIACheckStatus.FAIL,
                    message=msg,
                    suggestion=suggestion,
                    affected=affected,
                )
            )
            errors.append(NTIAValidationError(field=element, message=msg, suggestion=suggestion))

        add_component_issue(
            "component_name",
            "Component name",
            missing_names,
            "Ensure every component has a name.",
        )
        add_component_issue(
            "supplier_name",
            "Supplier/creator",
            missing_suppliers,
            "Provide supplier/manufacturer or author for each component.",
        )
        add_component_issue(
            "component_version",
            "Component version",
            missing_versions,
            "Add a version for every component (no placeholders).",
        )
        add_component_issue(
            "unique_identifiers",
            "Unique identifiers",
            missing_ids,
            "Include PURL/CPE/hash/external identifiers for components.",
        )

        automation_section = NTIASectionResult(
            name=NTIASection.AUTOMATION_SUPPORT,
            title="Automation Support",
            summary="Machine-readable format",
            checks=[check for check in checks if check.element == "automation_support"],
        )
        data_fields_section = NTIASectionResult(
            name=NTIASection.DATA_FIELDS,
            title="SBOM Data Fields",
            summary="Supplier, names, versions, IDs, dependencies, author, timestamp",
            checks=[check for check in checks if check.element != "automation_support"],
        )
        practices_section = NTIASectionResult(
            name=NTIASection.PRACTICES_PROCESSES,
            title="Practices & Processes",
            summary="Not evaluated in sbomqs alignment",
            checks=[],
        )

        is_compliant = len(errors) == 0
        status = NTIAComplianceStatus.COMPLIANT if is_compliant else NTIAComplianceStatus.NON_COMPLIANT

        return NTIAValidationResult(
            is_compliant=is_compliant,
            status=status,
            errors=errors,
            sections=[automation_section, data_fields_section, practices_section],
        )


def validate_sbom_ntia_compliance(sbom_data: Union[str, Dict[str, Any]], sbom_format: str) -> NTIAValidationResult:
    """
    Convenience function to validate SBOM NTIA compliance.

    Args:
        sbom_data: SBOM data as JSON string or dictionary
        sbom_format: SBOM format ('spdx' or 'cyclonedx')

    Returns:
        NTIAValidationResult with compliance status and errors
    """
    if isinstance(sbom_data, (bytes, bytearray)):
        sbom_data = sbom_data.decode("utf-8")

    if isinstance(sbom_data, str):
        try:
            sbom_data = json.loads(sbom_data)
        except json.JSONDecodeError as exc:
            error = NTIAValidationError(
                field="format",
                message=f"Invalid JSON format: {exc}",
                suggestion="Provide SBOM data as valid JSON.",
            )
        return NTIAValidationResult(is_compliant=False, status=NTIAComplianceStatus.UNKNOWN, errors=[error])

    validator = NTIAValidator()
    normalized = validator._normalize_sbom(sbom_data, sbom_format)
    return validator._evaluate_sbomqs_ntia(normalized)
