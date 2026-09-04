"""CISA 2026 Minimum Elements compliance plugin.

Scores an SBOM against the 2026 Minimum Elements for a Software Bill of
Materials, published 29 July 2026 by CISA with the NSA, the FBI and fifteen
international partners. That document updates and replaces the 2021 NTIA
minimum elements and supersedes the August 2025 public comment draft this
plugin used to implement.

Standard reference:
    - Name: 2026 Minimum Elements for a Software Bill of Materials (SBOM)
    - Version: 2.1, published 2026-07-29
    - URL: https://www.cisa.gov/resources-tools/resources/2026-minimum-elements-software-bill-materials-sbom

The standard defines 23 elements in two groups. The seventeen **data fields**
are what a document can be scored against and are what this plugin reports.
The six **practices and processes** (Accommodation of Updates to SBOM Data,
Coverage, Distribution and Delivery, Explicitly Identifying Unknown
Information, Frequency, Machine-Processable Data) describe how an
organisation operates rather than what one document says, so they are not
scored here.

Three outcomes, not two
-----------------------
The standard repeatedly says that an author who does not have a value should
say so rather than omit it: a version, a hash, a licence and a tool version
each carry that instruction, and Component Producer asks for an explicit
statement of unknown provenance. An author who does that has complied, so a
declared unknown is not scored as a miss. It is not the same as real data
either, and a reader has to be able to tell, so it reports as a warning while
an omission reports as a failure.

SPDX spells the two apart and the distinction is load-bearing: ``NOASSERTION``
is "the creator made no assertion", which is the declared unknown, while
``NONE`` is "the creator determined there is none", which is an answer.

What each format is read for
----------------------------
Where a format offers a field that means *created* and another that means
*supplied*, both are accepted, because CISA's Component Producer is the
creator and a document naming only the creator must not fail. That is the
direction the 2021 "Supplier Name" element was renamed for.

The SBOM Author Signature element has no in-document home in SPDX, and
CycloneDX carries one only in its own JSF ``signature`` block. The standard
says implementations should use existing signing infrastructure, so a
signature stored alongside the artifact satisfies the element for any format.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.builtins._spdx3_helpers import (
    extract_spdx3_elements,
    is_spdx3,
    iter_spdx3_external_identifiers,
)
from sbomify.apps.plugins.builtins._spdx_shared import (
    spdx2_annotation_targets_document,
    spdx2_root_spdxid,
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


#: Lifecycle phases that satisfy SBOM Generation Context. CISA names "before
#: build", "build" and "after build" and allows "more specific identifiers",
#: which is what the CycloneDX phase vocabulary and the SPDX 3 SbomType
#: vocabulary are. Both spacing and underscore spellings of CISA's own words
#: are accepted, because the standard writes them with spaces and tooling
#: writes them with underscores.
GENERATION_CONTEXT_VALUES = frozenset(
    {
        # CISA's own wording, in both spellings tools use.
        "before build",
        "before_build",
        "during build",
        "during_build",
        "build",
        "after build",
        "after_build",
        "post build",
        "post_build",
        # CycloneDX lifecycle phases.
        "design",
        "pre-build",
        "post-build",
        "operations",
        "discovery",
        "decommission",
        # SPDX 3 SbomType values.
        "source",
        "deployed",
        "runtime",
        "analyzed",
    }
)

#: SPDX 3 ``software_sbomType`` vocabulary. Checked by name rather than for
#: non-emptiness, so a document claiming a lifecycle phase the spec does not
#: define does not score as if it had stated one.
SPDX3_SBOM_TYPES = frozenset({"design", "source", "build", "deployed", "runtime", "analyzed"})

#: Hash algorithms a document may name, lowercased and stripped of the
#: punctuation the formats disagree about ("SHA-256", "SHA256", "sha256").
#: Drawn from the IANA Hash Function Textual Names registry the standard
#: points at, plus the CycloneDX and SPDX enumerations.
HASH_ALGORITHMS = frozenset(
    {
        "md2",
        "md4",
        "md5",
        "md6",
        "adler32",
        "sha1",
        "sha224",
        "sha256",
        "sha384",
        "sha512",
        "sha3224",
        "sha3256",
        "sha3384",
        "sha3512",
        "blake2b256",
        "blake2b384",
        "blake2b512",
        "blake2s256",
        "blake3",
    }
)

#: Identifier types that serve as a look-up key. CISA names CPE and PURL as
#: the common ones and adds UUIDs, organisation-specific identifiers, commit
#: hashes and the intrinsic identifiers OmniBOR and SWHID.
SPDX2_IDENTIFIER_TYPES = frozenset({"purl", "cpe22Type", "cpe23Type", "swid", "gitoid", "swhid"})
SPDX3_IDENTIFIER_TYPES = frozenset({"packageUrl", "packageURL", "purl", "cpe22", "cpe23", "swid", "gitoid", "swhid"})

#: What a document says when it is asserting that it does not know. SPDX
#: defines ``NOASSERTION`` for exactly this. ``NONE`` is deliberately absent:
#: it asserts that there is none, which is an answer rather than an unknown.
UNKNOWN_MARKERS = frozenset({"noassertion", "unknown", "notprovided"})

#: RFC 9557, which the standard names for SBOM Timestamp. An RFC 3339
#: date-time, then the optional bracketed time zone and tags RFC 9557 adds.
#: Written out rather than delegated to ``datetime.fromisoformat``, which
#: accepts a bare date and a space separator that RFC 9557 does not, and
#: rejects the bracketed suffix that it does.
_RFC_9557_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r"(?P<offset>[Zz]|[+-]\d{2}:\d{2})"
    r"(?:\[!?[A-Za-z0-9._+/-]+\])?"
    r"(?:\[!?[A-Za-z0-9-]+=[A-Za-z0-9._+/-]+\])*$"
)

#: The sanctioned property name for a CycloneDX generation context that is
#: not expressed as a lifecycle, under the taxonomy's "internal" namespace.
_GENERATION_CONTEXT_PROP = "internal:sbom:generationContext"
#: The earlier name, kept readable because documents in the wild carry it.
#: The taxonomy reserves the "cdx" namespace for registered names, so this
#: one was never valid there and new documents should not use it.
_LEGACY_GENERATION_CONTEXT_PROP = "cdx:sbom:generationContext"


def _text(value: Any) -> str:
    """A field's value as trimmed text, or empty for anything that is not a string."""
    return value.strip() if isinstance(value, str) else ""


def _is_unknown(value: Any) -> bool:
    """Whether a value is the document saying it does not know."""
    return _text(value).lower().replace(" ", "").replace("_", "") in UNKNOWN_MARKERS


def _stated(value: Any) -> bool:
    """Whether a value carries data, as opposed to being absent or a declared unknown."""
    return bool(_text(value)) and not _is_unknown(value)


def _looks_versioned(value: str) -> bool:
    """Whether a tool's name carries its version.

    Neither SPDX 2.x nor SPDX 3 gives a tool a version field, so the version
    rides the name. The spec's convention is "name-version", and real
    documents also write "name (1.0.0)" and "name v1.2", so this looks for a
    version-shaped token rather than for one punctuation mark.
    """
    return bool(re.search(r"\d+\.\d+|[-\s(]v?\d+\b", value))


def _normalise_algorithm(value: Any) -> str:
    """A hash algorithm name with the punctuation the formats disagree about removed."""
    return re.sub(r"[^a-z0-9]", "", _text(value).lower())


@dataclass
class _Tally:
    """What one element looked like across every component in a document.

    Two lists rather than a count, so a finding can name the components that
    need attention instead of only how many there were.
    """

    missing: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def record(self, name: str, value: Any) -> None:
        """Sort one component's value into stated, declared unknown, or absent."""
        if _is_unknown(value):
            self.unknown.append(name)
        elif not _text(value):
            self.missing.append(name)

    def note(self, name: str, *, stated: bool, unknown: bool = False) -> None:
        """Record an outcome a caller worked out for itself."""
        if stated:
            return
        (self.unknown if unknown else self.missing).append(name)


class CISAMinimumElementsPlugin(AssessmentPlugin):
    """Scores an SBOM against the seventeen CISA 2026 minimum data fields."""

    VERSION = "2.0.0"
    STANDARD_NAME = "2026 Minimum Elements for a Software Bill of Materials (SBOM)"
    STANDARD_VERSION = "2026-07"
    STANDARD_URL = "https://www.cisa.gov/resources-tools/resources/2026-minimum-elements-software-bill-materials-sbom"
    PLUGIN_NAME = "cisa-minimum-elements-2026"

    #: The nine SBOM Metadata data fields, in the order the standard lists them.
    METADATA_ELEMENTS = (
        "sbom_author",
        "sbom_author_signature",
        "sbom_data_format_name",
        "sbom_data_format_version",
        "sbom_generation_context",
        "sbom_timestamp",
        "sbom_tool_name",
        "sbom_tool_version",
        "sbom_version",
    )

    #: The eight Component Data fields.
    COMPONENT_ELEMENTS = (
        "component_producer",
        "component_name",
        "component_version",
        "component_identifiers",
        "component_hash_value",
        "component_hash_algorithm",
        "component_license",
        "component_dependency_relationship",
    )

    #: Title and definition per element, the definitions quoted from Appendix A.
    ELEMENTS: dict[str, tuple[str, str]] = {
        "sbom_author": (
            "SBOM Author",
            "The name of the entity that creates the SBOM data for the target component",
        ),
        "sbom_author_signature": (
            "SBOM Author Signature",
            "A digital signature attributable to the SBOM author",
        ),
        "sbom_data_format_name": (
            "SBOM Data Format Name",
            "The name of the data format used to represent the SBOM data",
        ),
        "sbom_data_format_version": (
            "SBOM Data Format Version",
            "Identifier designated by the SBOM data format to specify the version of the data format",
        ),
        "sbom_generation_context": (
            "SBOM Generation Context",
            "The software lifecycle phase and data available when the SBOM author generated the SBOM",
        ),
        "sbom_timestamp": (
            "SBOM Timestamp",
            "Record of the date and time of the most recent update to the SBOM data",
        ),
        "sbom_tool_name": (
            "SBOM Tool Name",
            "The name of the tool used by the SBOM author to generate or amend the SBOM",
        ),
        "sbom_tool_version": (
            "SBOM Tool Version",
            "Identifier for the version of the tool named in SBOM Tool Name",
        ),
        "sbom_version": (
            "SBOM Version",
            "Identifier specifying a change in the SBOM document from a previous version, or that it is the first",
        ),
        "component_producer": (
            "Component Producer",
            "The name of an entity that creates, defines, and identifies components",
        ),
        "component_name": (
            "Component Name",
            "The name assigned by the component producer to a software component",
        ),
        "component_version": (
            "Component Version",
            "Identifier specifying a change in a component from a previous version, or that it is the first",
        ),
        "component_identifiers": (
            "Component Identifiers",
            "Identifiers used to identify a component or serve as a look-up key for relevant databases",
        ),
        "component_hash_value": (
            "Component Hash Value",
            "The output of applying a cryptographic hash algorithm to an executable component artifact",
        ),
        "component_hash_algorithm": (
            "Component Hash Algorithm",
            "The cryptographic algorithm used to compute the Component Hash Value",
        ),
        "component_license": (
            "Component License",
            "The identifiers for the licenses under which the software component is available",
        ),
        "component_dependency_relationship": (
            "Component Dependency Relationship",
            "The relationship between two components, where one is necessary for the operation of the other",
        ),
    }

    def get_metadata(self) -> PluginMetadata:
        """Identity and category, as the registry and the orchestrator read it."""
        return PluginMetadata(
            name=self.PLUGIN_NAME,
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
        """Score one stored document against the seventeen data fields.

        ``context`` carries the artifact's stored signature, which is the only
        way any SPDX document can satisfy SBOM Author Signature.
        """
        logger.info("[CISA-2026] Starting compliance check for SBOM %s", sbom_id)

        try:
            data = json.loads(sbom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            logger.error("[CISA-2026] Failed to parse SBOM JSON: %s", error)
            return self._error_result(f"Invalid JSON format: {error}")
        except Exception as error:
            logger.error("[CISA-2026] Failed to read SBOM file: %s", error)
            return self._error_result(f"Failed to read SBOM: {error}")

        if not isinstance(data, dict):
            return self._error_result("The document is valid JSON but not an object")

        sbom_format = self._detect_format(data)
        if sbom_format == "spdx3":
            findings = self._validate_spdx3(data, context)
        elif sbom_format == "spdx":
            findings = self._validate_spdx2(data, context)
        elif sbom_format == "cyclonedx":
            findings = self._validate_cyclonedx(data, context)
        else:
            logger.warning("[CISA-2026] Unknown SBOM format for %s", sbom_id)
            return self._error_result("Unable to detect SBOM format (expected SPDX or CycloneDX)")

        counts = {status: sum(1 for f in findings if f.status == status) for status in ("pass", "fail", "warning")}
        summary = AssessmentSummary(
            total_findings=len(findings),
            pass_count=counts["pass"],
            fail_count=counts["fail"],
            warning_count=counts["warning"],
            error_count=0,
        )
        logger.info(
            "[CISA-2026] Completed compliance check for SBOM %s: %s pass, %s fail, %s warning",
            sbom_id,
            counts["pass"],
            counts["fail"],
            counts["warning"],
        )

        return AssessmentResult(
            plugin_name=self.PLUGIN_NAME,
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

    def _detect_format(self, data: dict[str, Any]) -> str:
        """Which of the two sanctioned formats this document is written in."""
        if is_spdx3(data):
            return "spdx3"
        if "spdxVersion" in data:
            return "spdx"
        if isinstance(data.get("bomFormat"), str) and data["bomFormat"].lower() == "cyclonedx":
            return "cyclonedx"
        if "specVersion" in data and "components" in data:
            return "cyclonedx"
        return "unknown"

    # ------------------------------------------------------------------
    # Shared outcome shaping
    # ------------------------------------------------------------------

    def _finding(
        self,
        element: str,
        status: str,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """One element's result, with the standard's own definition as the description."""
        title, definition = self.ELEMENTS[element]
        description = f"{definition}. {details}" if details else definition
        return Finding(
            id=f"cisa-2026:{element.replace('_', '-')}",
            title=title,
            description=description,
            status=status,
            severity="info" if status == "pass" else ("low" if status == "warning" else "medium"),
            remediation=remediation if status != "pass" else None,
            metadata={
                "standard": "CISA",
                "standard_version": self.STANDARD_VERSION,
                "element": element,
            },
        )

    def _document_finding(
        self,
        element: str,
        *,
        stated: bool,
        unknown: bool = False,
        details: str | None = None,
        remediation: str | None = None,
    ) -> Finding:
        """A document-level element, which is stated, declared unknown, or absent.

        ``details`` describes the absence, so it is not reused for the
        declared unknown: telling a reader the tool "is named without a
        version" when the document said the version is unknown describes the
        wrong document.
        """
        if stated:
            return self._finding(element, "pass")
        if unknown:
            return self._finding(element, "warning", "The document states this is unknown.", remediation)
        return self._finding(element, "fail", details, remediation)

    def _component_finding(
        self,
        element: str,
        tally: _Tally,
        total: int,
        remediation: str,
    ) -> Finding:
        """A per-component element, summarised over every component assessed.

        A miss anywhere fails the element, because the standard asks for the
        field on every component rather than on most of them. Declared
        unknowns warn only when nothing is outright missing, so the more
        serious outcome is the one a reader sees first.
        """
        if not total:
            return self._finding(
                element,
                "warning",
                "The document lists no components, so there was nothing to assess.",
                remediation,
            )
        if tally.missing:
            return self._finding(element, "fail", f"Missing for: {self._names(tally.missing)}", remediation)
        if tally.unknown:
            return self._finding(
                element,
                "warning",
                f"Stated as unknown for: {self._names(tally.unknown)}",
                remediation,
            )
        return self._finding(element, "pass")

    @staticmethod
    def _names(names: list[str], limit: int = 12) -> str:
        """A readable list of component names, truncated so one finding stays legible."""
        shown = ", ".join(names[:limit])
        remaining = len(names) - limit
        return f"{shown} and {remaining} more" if remaining > 0 else shown

    def _signature_finding(self, *, in_document: bool, context: SBOMContext | None, note: str) -> Finding:
        """SBOM Author Signature, which a stored detached signature can satisfy for any format."""
        stored = bool(context and context.signature_blob_key)
        if in_document or stored:
            return self._finding("sbom_author_signature", "pass")
        return self._finding(
            "sbom_author_signature",
            "fail",
            note,
            "Sign the SBOM and attach the signature to the artifact, or carry one in the document.",
        )

    @staticmethod
    def _valid_timestamp(value: Any) -> bool:
        """Whether a timestamp is an RFC 9557 date-time, which is what the standard asks for."""
        match = _RFC_9557_RE.match(_text(value))
        if not match:
            return False
        # The shape is right; this rejects the impossible dates it allows.
        stamp = match.group("stamp")
        offset = match.group("offset")
        normalised = f"{stamp}+00:00" if offset in {"Z", "z"} else f"{stamp}{offset}"
        try:
            datetime.fromisoformat(normalised)
        except ValueError:
            return False
        return True

    # ------------------------------------------------------------------
    # CycloneDX
    # ------------------------------------------------------------------

    def _validate_cyclonedx(self, data: dict[str, Any], context: SBOMContext | None = None) -> list[Finding]:
        """Score a CycloneDX document."""
        metadata = data.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        components = self._cyclonedx_components(data, metadata)

        findings = [
            self._document_finding(
                "sbom_author",
                stated=self._cyclonedx_has_author(metadata),
                details="No metadata.authors or metadata.manufacturer names an entity.",
                remediation="Add metadata.authors[].name, or metadata.manufacturer.name for an organisation. "
                "A tool in metadata.tools is not the author.",
            ),
            self._signature_finding(
                in_document=self._cyclonedx_has_signature(data),
                context=context,
                note="The document carries no signature block.",
            ),
            self._document_finding(
                "sbom_data_format_name",
                stated=_text(data.get("bomFormat")).lower() == "cyclonedx",
                details="bomFormat does not name the format.",
                remediation='Set bomFormat to "CycloneDX".',
            ),
            self._document_finding(
                "sbom_data_format_version",
                stated=bool(_text(data.get("specVersion"))),
                details="specVersion is absent.",
                remediation="Set specVersion to the CycloneDX version the document is written in.",
            ),
            self._document_finding(
                "sbom_generation_context",
                stated=self._cyclonedx_has_generation_context(metadata),
                details="No lifecycle phase is stated.",
                remediation="Add metadata.lifecycles[].phase, which is the CycloneDX-sanctioned path, "
                f'or a metadata property named "{_GENERATION_CONTEXT_PROP}".',
            ),
            self._document_finding(
                "sbom_timestamp",
                stated=self._valid_timestamp(metadata.get("timestamp")),
                details="metadata.timestamp is absent or is not an RFC 9557 date-time.",
                remediation="Set metadata.timestamp to an RFC 9557 date-time, such as 2026-07-29T10:00:00Z.",
            ),
        ]

        tool_name, tool_version = self._cyclonedx_tool(metadata)
        findings.append(
            self._document_finding(
                "sbom_tool_name",
                stated=bool(tool_name),
                details="No tool is named in metadata.tools.",
                remediation="Add the generating tool to metadata.tools.components[] with its name.",
            )
        )
        findings.append(
            self._document_finding(
                "sbom_tool_version",
                stated=_stated(tool_version),
                unknown=_is_unknown(tool_version),
                details="The tool is named without a version.",
                remediation="Add the tool's version alongside its name, or state that it is unknown.",
            )
        )
        findings.append(
            self._document_finding(
                "sbom_version",
                stated=isinstance(data.get("version"), int) and data["version"] >= 1,
                details="The document states no version number.",
                remediation="Set version to 1 for a first document and raise it on every revision.",
            )
        )

        tallies = {element: _Tally() for element in self.COMPONENT_ELEMENTS}
        for index, component in enumerate(components):
            name = _text(component.get("name")) or f"component at index {index}"
            tallies["component_name"].note(name, stated=bool(_text(component.get("name"))))
            if _text(component.get("type")).lower() == "file":
                # A file entry is input metadata rather than a shipped
                # component, and the per-component fields do not describe it.
                # Its name is still checked above, where a missing one is a
                # data-quality problem whatever the entry is.
                continue

            tallies["component_producer"].note(
                name,
                stated=self._cyclonedx_has_producer(component),
                unknown=self._cyclonedx_producer_unknown(component),
            )
            tallies["component_version"].record(name, component.get("version"))
            tallies["component_identifiers"].note(name, stated=self._cyclonedx_has_identifier(component))

            hashes = component.get("hashes")
            hashes = [h for h in hashes if isinstance(h, dict)] if isinstance(hashes, list) else []
            tallies["component_hash_value"].note(name, stated=any(_stated(h.get("content")) for h in hashes))
            tallies["component_hash_algorithm"].note(
                name,
                stated=any(_normalise_algorithm(h.get("alg")) in HASH_ALGORITHMS for h in hashes),
            )
            tallies["component_license"].note(
                name,
                stated=self._cyclonedx_has_license(component),
                unknown=self._cyclonedx_license_unknown(component),
            )

        assessed = sum(1 for c in components if _text(c.get("type")).lower() != "file")
        remediations = {
            "component_producer": "Add manufacturer.name for the organisation that created the component, "
            "or authors[].name. supplier.name is accepted where the supplier is the producer.",
            "component_name": "Add name to every component.",
            "component_version": "Add version to every component, or state that it is unknown.",
            "component_identifiers": "Add at least one of purl, cpe, swid, omniborId or swhid.",
            "component_hash_value": "Add hashes[].content for every component.",
            "component_hash_algorithm": "Name the algorithm in hashes[].alg, such as SHA-256.",
            "component_license": "Add licenses[] with an SPDX identifier or expression, "
            "or state that the licence is unknown.",
            "component_dependency_relationship": "Add a dependencies[] entry with dependsOn for each component.",
        }
        for element in self.COMPONENT_ELEMENTS:
            if element == "component_dependency_relationship":
                continue
            if element == "component_name":
                findings.append(
                    self._component_finding(element, tallies[element], len(components), remediations[element])
                )
                continue
            findings.append(self._component_finding(element, tallies[element], assessed, remediations[element]))

        findings.append(
            self._document_finding(
                "component_dependency_relationship",
                stated=self._cyclonedx_has_dependencies(data, assessed),
                details="No dependencies[] entry states what a component depends on.",
                remediation=remediations["component_dependency_relationship"],
            )
        )
        return self._ordered(findings)

    @staticmethod
    def _cyclonedx_components(data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """Every component the document describes, target and subcomponents alike.

        The standard's Component Data elements cover "the target component
        ... and all subcomponents", so the metadata component counts, and
        CycloneDX's nested components are walked rather than only the top
        level.
        """
        found: list[dict[str, Any]] = []
        seen: set[int] = set()

        def walk(entries: Any) -> None:
            if not isinstance(entries, list):
                return
            for entry in entries:
                if not isinstance(entry, dict) or id(entry) in seen:
                    continue
                seen.add(id(entry))
                found.append(entry)
                walk(entry.get("components"))

        target = metadata.get("component")
        if isinstance(target, dict):
            seen.add(id(target))
            found.append(target)
            walk(target.get("components"))
        walk(data.get("components"))
        return found

    @staticmethod
    def _cyclonedx_has_author(metadata: dict[str, Any]) -> bool:
        """Whether the document names the entity that created it, rather than the tool.

        The standard is explicit that the author "captures the entity
        operating the tool to generate the SBOM, not the tool itself", so
        metadata.tools never satisfies this.
        """
        authors = metadata.get("authors")
        if isinstance(authors, list):
            for author in authors:
                if isinstance(author, dict) and (_stated(author.get("name")) or _stated(author.get("email"))):
                    return True
        # 1.6 renamed "manufacture" to "manufacturer"; documents carry both.
        for key in ("manufacturer", "manufacture"):
            entity = metadata.get(key)
            if isinstance(entity, dict) and _stated(entity.get("name")):
                return True
        return False

    @staticmethod
    def _cyclonedx_has_signature(data: dict[str, Any]) -> bool:
        """Whether the document carries its own JSF signature block."""
        signature = data.get("signature")
        if isinstance(signature, dict):
            return bool(_text(signature.get("value")) or signature.get("signers") or signature.get("chain"))
        return isinstance(signature, list) and bool(signature)

    @staticmethod
    def _cyclonedx_tool(metadata: dict[str, Any]) -> tuple[str, str]:
        """The generating tool's name and version, across the 1.4 and 1.5 shapes."""
        tools = metadata.get("tools")
        candidates: list[dict[str, Any]] = []
        if isinstance(tools, list):
            # 1.4 and earlier: a bare array of tool objects.
            candidates = [t for t in tools if isinstance(t, dict)]
        elif isinstance(tools, dict):
            # 1.5 and later: components and services under metadata.tools.
            for key in ("components", "services"):
                entries = tools.get(key)
                if isinstance(entries, list):
                    candidates.extend(t for t in entries if isinstance(t, dict))
        for tool in candidates:
            name = _text(tool.get("name")) or _text(tool.get("vendor"))
            if name:
                return name, _text(tool.get("version"))
        return "", ""

    def _cyclonedx_has_generation_context(self, metadata: dict[str, Any]) -> bool:
        """Whether the document states the lifecycle phase it was generated in.

        ``metadata.lifecycles[].phase`` is the sanctioned path. The spec also
        allows a custom lifecycle carrying a name instead of a phase, and
        CISA accepts "more specific identifiers", so a named custom lifecycle
        counts. A property remains as the fallback for documents that carry
        neither.
        """
        lifecycles = metadata.get("lifecycles")
        if isinstance(lifecycles, list):
            for lifecycle in lifecycles:
                if not isinstance(lifecycle, dict):
                    continue
                if _text(lifecycle.get("phase")).lower() in GENERATION_CONTEXT_VALUES:
                    return True
                if _stated(lifecycle.get("name")):
                    return True

        properties = metadata.get("properties")
        if not isinstance(properties, list):
            return False
        accepted = (_GENERATION_CONTEXT_PROP, _LEGACY_GENERATION_CONTEXT_PROP)
        for prop in properties:
            if not isinstance(prop, dict) or prop.get("name") not in accepted:
                continue
            if _text(prop.get("value")).lower() in GENERATION_CONTEXT_VALUES:
                return True
        return False

    @staticmethod
    def _cyclonedx_producer_fields(component: dict[str, Any]) -> list[Any]:
        """The values that can name who created or supplied a component.

        Creator-side fields come first: ``manufacturer`` is "the organization
        that created the component" and ``authors`` "the person(s) who
        created" it, which is what Component Producer asks for. ``publisher``
        and ``supplier`` follow because the supplier is often the
        manufacturer and a document naming only those must not fail.
        """
        values: list[Any] = []
        for key in ("manufacturer", "manufacture", "supplier"):
            entity = component.get(key)
            if isinstance(entity, dict):
                values.append(entity.get("name"))
        authors = component.get("authors")
        if isinstance(authors, list):
            values.extend(a.get("name") for a in authors if isinstance(a, dict))
        values.append(component.get("author"))
        values.append(component.get("publisher"))
        return values

    def _cyclonedx_has_producer(self, component: dict[str, Any]) -> bool:
        return any(_stated(value) for value in self._cyclonedx_producer_fields(component))

    def _cyclonedx_producer_unknown(self, component: dict[str, Any]) -> bool:
        return any(_is_unknown(value) for value in self._cyclonedx_producer_fields(component))

    @staticmethod
    def _cyclonedx_has_identifier(component: dict[str, Any]) -> bool:
        """Whether the component carries a look-up key.

        CISA names CPE and PURL as the common identifiers and adds the
        intrinsic ones. CycloneDX 1.6 carries the five in three shapes: purl
        and cpe are strings, swid is an object keyed by tagId, and omniborId
        and swhid are arrays. A producer that writes one of the last three as
        a bare string is read too, because that was accepted before and the
        element is about whether a key is there.
        """
        if any(_stated(component.get(key)) for key in ("purl", "cpe")):
            return True
        swid = component.get("swid")
        if isinstance(swid, dict):
            if _stated(swid.get("tagId")) or _stated(swid.get("name")):
                return True
        elif _stated(swid):
            return True
        for key in ("omniborId", "swhid"):
            value = component.get(key)
            entries = value if isinstance(value, list) else [value]
            if any(_stated(entry) for entry in entries):
                return True
        return False

    @staticmethod
    def _cyclonedx_licenses(component: dict[str, Any]) -> list[dict[str, Any]]:
        licenses = component.get("licenses")
        return [entry for entry in licenses if isinstance(entry, dict)] if isinstance(licenses, list) else []

    def _cyclonedx_has_license(self, component: dict[str, Any]) -> bool:
        for entry in self._cyclonedx_licenses(component):
            if _stated(entry.get("expression")):
                return True
            licence = entry.get("license")
            if isinstance(licence, dict) and (_stated(licence.get("id")) or _stated(licence.get("name"))):
                return True
        return False

    def _cyclonedx_license_unknown(self, component: dict[str, Any]) -> bool:
        """Whether the licence block is present but says the licence is unknown."""
        for entry in self._cyclonedx_licenses(component):
            if _is_unknown(entry.get("expression")):
                return True
            licence = entry.get("license")
            if isinstance(licence, dict) and (_is_unknown(licence.get("id")) or _is_unknown(licence.get("name"))):
                return True
        return False

    @staticmethod
    def _cyclonedx_has_dependencies(data: dict[str, Any], component_count: int) -> bool:
        """Whether the document states a dependency edge.

        The count is of components the standard's Component Data elements
        apply to, so file entries are already out of it. A document
        describing fewer than two such components has no relationship to
        state, and the element is satisfied rather than failed on a document
        that could not carry one.
        """
        if component_count < 2:
            return True
        dependencies = data.get("dependencies")
        if not isinstance(dependencies, list):
            return False
        for entry in dependencies:
            if not isinstance(entry, dict):
                continue
            depends_on = entry.get("dependsOn")
            if isinstance(depends_on, list) and any(_text(ref) for ref in depends_on):
                return True
        return False

    # ------------------------------------------------------------------
    # SPDX 2.x
    # ------------------------------------------------------------------

    def _validate_spdx2(self, data: dict[str, Any], context: SBOMContext | None = None) -> list[Finding]:
        """Score an SPDX 2.x document."""
        creation_info = data.get("creationInfo")
        creation_info = creation_info if isinstance(creation_info, dict) else {}
        creators = [_text(c) for c in creation_info.get("creators", []) if isinstance(c, str)]
        packages = [p for p in data.get("packages", []) if isinstance(p, dict)]

        # The author is a Person or an Organization. A Tool: entry names the
        # tool, which the standard says is not the author.
        authors = [c for c in creators if c.startswith(("Person:", "Organization:")) and c.split(":", 1)[1].strip()]
        tools = [c for c in creators if c.startswith("Tool:") and c.split(":", 1)[1].strip()]

        findings = [
            self._document_finding(
                "sbom_author",
                stated=bool(authors),
                details="creationInfo.creators names no Person or Organization.",
                remediation='Add a creator of the form "Organization: Acme Inc" or "Person: Jane Doe". '
                "A Tool entry names the tool, not the author.",
            ),
            self._signature_finding(
                in_document=False,
                context=context,
                note="SPDX carries no in-document signature, and no signature is stored for this artifact.",
            ),
            self._document_finding(
                "sbom_data_format_name",
                stated=bool(_text(data.get("spdxVersion"))),
                details="spdxVersion is absent, so the document does not name its format.",
                remediation='Set spdxVersion, such as "SPDX-2.3".',
            ),
            self._document_finding(
                "sbom_data_format_version",
                stated=bool(re.search(r"\d", _text(data.get("spdxVersion")))),
                details="spdxVersion states no version.",
                remediation='Set spdxVersion to the version the document is written in, such as "SPDX-2.3".',
            ),
            self._document_finding(
                "sbom_generation_context",
                stated=self._spdx2_has_generation_context(data),
                details="No lifecycle phase is stated in the creator comment, the document comment, "
                "or a document-level annotation.",
                remediation='State the phase in creationInfo.comment, for example "after build".',
            ),
            self._document_finding(
                "sbom_timestamp",
                stated=self._valid_timestamp(creation_info.get("created")),
                details="creationInfo.created is absent or is not an RFC 9557 date-time.",
                remediation="Set creationInfo.created to an RFC 9557 date-time, such as 2026-07-29T10:00:00Z.",
            ),
            self._document_finding(
                "sbom_tool_name",
                stated=bool(tools),
                details="creationInfo.creators names no Tool.",
                remediation='Add a creator of the form "Tool: syft-1.51.1".',
            ),
        ]

        # SPDX 2.x has no tool version field: the version rides the tool's
        # name. The spec's own convention is "name-version", and documents in
        # the wild also write "name (version)" and "name v1.2", so the test is
        # for a version-shaped token rather than one punctuation mark.
        tool_versions = [t.split(":", 1)[1].strip() for t in tools]
        has_tool_version = any(_looks_versioned(value) for value in tool_versions)
        findings.append(
            self._document_finding(
                "sbom_tool_version",
                stated=has_tool_version,
                unknown=any(_is_unknown(value) for value in tool_versions),
                details="The tool entry carries no version.",
                remediation='Append the version to the tool name, as in "Tool: syft-1.51.1".',
            )
        )
        findings.append(
            self._document_finding(
                "sbom_version",
                stated=bool(_text(data.get("documentNamespace"))),
                details="documentNamespace is absent, so revisions of this document cannot be told apart.",
                remediation="Set a documentNamespace that is unique to this revision of the document.",
            )
        )

        tallies = {element: _Tally() for element in self.COMPONENT_ELEMENTS}
        assessed = 0
        for index, package in enumerate(packages):
            name = _text(package.get("name")) or f"package at index {index}"
            tallies["component_name"].note(name, stated=bool(_text(package.get("name"))))
            if "-File-" in _text(package.get("SPDXID")):
                continue
            assessed += 1

            # PackageOriginator is who created it, PackageSupplier who
            # distributed it. The producer is the originator, and a document
            # naming only the supplier is still naming a party.
            producer_values = [package.get("originator"), package.get("supplier")]
            tallies["component_producer"].note(
                name,
                stated=any(_stated(v) for v in producer_values),
                unknown=any(_is_unknown(v) for v in producer_values),
            )
            tallies["component_version"].record(name, package.get("versionInfo"))
            tallies["component_identifiers"].note(name, stated=self._spdx2_has_identifier(package))

            checksums = package.get("checksums")
            checksums = [c for c in checksums if isinstance(c, dict)] if isinstance(checksums, list) else []
            tallies["component_hash_value"].note(name, stated=any(_stated(c.get("checksumValue")) for c in checksums))
            tallies["component_hash_algorithm"].note(
                name,
                stated=any(_normalise_algorithm(c.get("algorithm")) in HASH_ALGORITHMS for c in checksums),
            )

            licences = [package.get("licenseConcluded"), package.get("licenseDeclared")]
            tallies["component_license"].note(
                name,
                stated=any(_stated(v) for v in licences),
                unknown=any(_is_unknown(v) for v in licences),
            )

        remediations = {
            "component_producer": "Add originator to every package, in the form "
            '"Organization: Acme Inc", or state NOASSERTION for unknown provenance.',
            "component_name": "Add name to every package.",
            "component_version": "Add versionInfo to every package, or state NOASSERTION.",
            "component_identifiers": "Add externalRefs with a purl or a CPE.",
            "component_hash_value": "Add checksums[].checksumValue to every package.",
            "component_hash_algorithm": "Name the algorithm in checksums[].algorithm, such as SHA256.",
            "component_license": "Add licenseConcluded or licenseDeclared, or state NOASSERTION.",
            "component_dependency_relationship": "Add relationships with DEPENDS_ON or CONTAINS.",
        }
        for element in self.COMPONENT_ELEMENTS:
            if element == "component_dependency_relationship":
                continue
            total = len(packages) if element == "component_name" else assessed
            findings.append(self._component_finding(element, tallies[element], total, remediations[element]))

        findings.append(
            self._document_finding(
                "component_dependency_relationship",
                stated=self._spdx2_has_dependencies(data, assessed),
                details="No relationship states that one component is necessary to another.",
                remediation=remediations["component_dependency_relationship"],
            )
        )
        return self._ordered(findings)

    @staticmethod
    def _spdx2_has_identifier(package: dict[str, Any]) -> bool:
        """Whether the package carries a look-up key in its external references."""
        refs = package.get("externalRefs")
        if not isinstance(refs, list):
            return False
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if _text(ref.get("referenceType")) in SPDX2_IDENTIFIER_TYPES and _stated(ref.get("referenceLocator")):
                return True
        return False

    @staticmethod
    def _spdx2_has_dependencies(data: dict[str, Any], package_count: int) -> bool:
        """Whether the document states a dependency relationship.

        ``package_count`` excludes file packages, for the reason given on the
        CycloneDX counterpart.
        """
        if package_count < 2:
            return True
        relationships = data.get("relationships")
        if not isinstance(relationships, list):
            return False
        wanted = {"DEPENDS_ON", "DEPENDENCY_OF", "CONTAINS", "CONTAINED_BY", "DESCENDANT_OF", "STATIC_LINK"}
        return any(
            isinstance(rel, dict) and _text(rel.get("relationshipType")).upper() in wanted for rel in relationships
        )

    def _spdx2_has_generation_context(self, data: dict[str, Any]) -> bool:
        """Whether the document states the lifecycle phase it was generated in.

        SPDX 2.x has no field for it, so the creator comment, the document
        comment and a document-scoped annotation are the three places it can
        be written. An annotation whose ``spdxElementId`` points at a package
        describes that package rather than the document, so it does not count.
        """
        creation_info = data.get("creationInfo")
        if isinstance(creation_info, dict):
            comment = _text(creation_info.get("comment")).lower()
            if any(value in comment for value in GENERATION_CONTEXT_VALUES):
                return True

        document_comment = _text(data.get("comment")).lower()
        if any(value in document_comment for value in GENERATION_CONTEXT_VALUES):
            return True

        root_spdxid = spdx2_root_spdxid(data)
        annotations = data.get("annotations")
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict) or annotation.get("annotationType") != "OTHER":
                continue
            if not spdx2_annotation_targets_document(annotation, root_spdxid):
                continue
            comment = _text(annotation.get("comment"))
            for part in comment.split():
                if part.startswith("cisa:generationContext="):
                    if part.split("=", 1)[1].lower().strip() in GENERATION_CONTEXT_VALUES:
                        return True
        return False

    # ------------------------------------------------------------------
    # SPDX 3.x
    # ------------------------------------------------------------------

    def _validate_spdx3(self, data: dict[str, Any], context: SBOMContext | None = None) -> list[Finding]:
        """Score an SPDX 3.x document."""
        creation_info, packages, relationships, agents, tools = extract_spdx3_elements(data)
        creation_info = creation_info if isinstance(creation_info, dict) else {}

        findings = [
            self._document_finding(
                "sbom_author",
                stated=self._spdx3_has_author(creation_info, agents),
                details="CreationInfo.createdBy names no Person or Organization.",
                remediation="Point createdBy at a Person or Organization element. A SoftwareAgent is the tool, "
                "which the standard says is not the author.",
            ),
            self._signature_finding(
                in_document=False,
                context=context,
                note="SPDX carries no in-document signature, and no signature is stored for this artifact.",
            ),
            self._document_finding(
                "sbom_data_format_name",
                stated=True,
                remediation=None,
            ),
            self._document_finding(
                "sbom_data_format_version",
                stated=bool(_text(creation_info.get("specVersion"))),
                details="CreationInfo.specVersion is absent.",
                remediation='Set CreationInfo.specVersion, such as "3.0.1".',
            ),
            self._document_finding(
                "sbom_generation_context",
                stated=self._spdx3_has_generation_context(data),
                details="No software_Sbom element states a software_sbomType the specification defines.",
                remediation="Set software_sbomType on the software_Sbom element to one of "
                f"{', '.join(sorted(SPDX3_SBOM_TYPES))}.",
            ),
            self._document_finding(
                "sbom_timestamp",
                stated=self._valid_timestamp(creation_info.get("created")),
                details="CreationInfo.created is absent or is not an RFC 9557 date-time.",
                remediation="Set CreationInfo.created to an RFC 9557 date-time, such as 2026-07-29T10:00:00Z.",
            ),
        ]

        tool_elements = self._spdx3_tools(creation_info, tools, agents)
        findings.append(
            self._document_finding(
                "sbom_tool_name",
                stated=any(_stated(tool.get("name")) for tool in tool_elements),
                details="CreationInfo.createdUsing names no tool.",
                remediation="Point createdUsing at a Tool element carrying a name.",
            )
        )
        findings.append(
            self._document_finding(
                "sbom_tool_version",
                stated=any(self._spdx3_tool_version(tool) for tool in tool_elements),
                unknown=any(self._spdx3_tool_version_unknown(tool) for tool in tool_elements),
                details="The tool element states no version.",
                remediation="Carry the tool version in software_packageVersion, in the tool's name, "
                "or as an external identifier.",
            )
        )
        findings.append(
            self._document_finding(
                "sbom_version",
                stated=self._spdx3_has_document_identity(data),
                details="No SpdxDocument element carries an identifier, so revisions cannot be told apart.",
                remediation="Give the SpdxDocument element a spdxId that is unique to this revision.",
            )
        )

        licence_subjects = self._spdx3_license_subjects(relationships)
        tallies = {element: _Tally() for element in self.COMPONENT_ELEMENTS}
        for index, package in enumerate(packages):
            name = _text(package.get("name")) or f"package at index {index}"
            package_id = _text(package.get("spdxId")) or _text(package.get("@id"))
            tallies["component_name"].note(name, stated=bool(_text(package.get("name"))))

            producers = self._spdx3_producer_names(package, agents)
            tallies["component_producer"].note(
                name,
                stated=any(_stated(value) for value in producers),
                unknown=any(_is_unknown(value) for value in producers),
            )
            tallies["component_version"].record(name, package.get("software_packageVersion"))
            tallies["component_identifiers"].note(name, stated=self._spdx3_has_identifier(package))

            hashes = self._spdx3_hashes(package)
            tallies["component_hash_value"].note(name, stated=any(_stated(h.get("hashValue")) for h in hashes))
            tallies["component_hash_algorithm"].note(
                name,
                stated=any(_normalise_algorithm(h.get("algorithm")) in HASH_ALGORITHMS for h in hashes),
            )
            tallies["component_license"].note(name, stated=package_id in licence_subjects)

        remediations = {
            "component_producer": "Point originatedBy at a Person or Organization element for every package.",
            "component_name": "Add name to every software_Package element.",
            "component_version": "Add software_packageVersion to every package, or state NOASSERTION.",
            "component_identifiers": "Add software_packageUrl, or an externalIdentifier of type "
            "packageUrl, cpe23, gitoid or swhid.",
            "component_hash_value": "Add verifiedUsing with a Hash carrying hashValue.",
            "component_hash_algorithm": "Name the algorithm in the Hash element, such as sha256.",
            "component_license": "Add a hasDeclaredLicense relationship, which is what the producer declares, "
            "or hasConcludedLicense.",
            "component_dependency_relationship": "Add a Relationship of type dependsOn or contains.",
        }
        for element in self.COMPONENT_ELEMENTS:
            if element == "component_dependency_relationship":
                continue
            findings.append(self._component_finding(element, tallies[element], len(packages), remediations[element]))

        findings.append(
            self._document_finding(
                "component_dependency_relationship",
                stated=self._spdx3_has_dependencies(relationships, len(packages)),
                details="No Relationship states that one component is necessary to another.",
                remediation=remediations["component_dependency_relationship"],
            )
        )
        return self._ordered(findings)

    @staticmethod
    def _spdx3_has_author(creation_info: dict[str, Any], agents: dict[str, dict[str, Any]]) -> bool:
        """Whether createdBy resolves to a Person or an Organization.

        The agent map holds every Agent subtype the specification allows,
        SoftwareAgent included. A SoftwareAgent is the tool, and the standard
        separates the tool from the author, so only the two human-or-company
        types satisfy this element.
        """
        created_by = creation_info.get("createdBy")
        if isinstance(created_by, str):
            created_by = [created_by]
        if not isinstance(created_by, list):
            return False
        for ref in created_by:
            entity = agents.get(ref) if isinstance(ref, str) else (ref if isinstance(ref, dict) else None)
            if not isinstance(entity, dict):
                continue
            entity_type = _text(entity.get("type") or entity.get("@type")).rsplit("/", 1)[-1]
            if entity_type in {"Person", "Organization"} and _stated(entity.get("name")):
                return True
        return False

    @staticmethod
    def _spdx3_tools(
        creation_info: dict[str, Any],
        tools: dict[str, dict[str, Any]],
        agents: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """The tool elements createdUsing points at."""
        refs = creation_info.get("createdUsing")
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            return []
        found: list[dict[str, Any]] = []
        for ref in refs:
            if isinstance(ref, dict):
                found.append(ref)
            elif isinstance(ref, str):
                element = tools.get(ref) or agents.get(ref)
                if element:
                    found.append(element)
        return found

    @staticmethod
    def _spdx3_tool_version(tool: dict[str, Any]) -> bool:
        """Whether a tool element states its version.

        SPDX 3 gives Tool no version property, so the specification's own
        advice is to carry it in the name, an external identifier, or a
        package version where the tool is modelled as one.
        """
        if _stated(tool.get("software_packageVersion")) or _stated(tool.get("version")):
            return True
        if _looks_versioned(_text(tool.get("name"))):
            return True
        return any(_stated(ext.get("identifier")) for ext in iter_spdx3_external_identifiers(tool))

    @staticmethod
    def _spdx3_tool_version_unknown(tool: dict[str, Any]) -> bool:
        """Whether the tool element states its version is unknown rather than omitting it.

        The other two formats already report this, and an element that
        warns on one format and fails on another for the same document is
        the inconsistency the three-outcome design exists to avoid.
        """
        return any(_is_unknown(tool.get(key)) for key in ("software_packageVersion", "version"))

    @staticmethod
    def _spdx3_has_document_identity(data: dict[str, Any]) -> bool:
        """Whether an SpdxDocument element carries an identifier this revision can be known by."""
        elements = data.get("@graph", data.get("elements", []))
        if not isinstance(elements, list):
            return False
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_type = _text(element.get("type") or element.get("@type")).rsplit("/", 1)[-1]
            if element_type in {"SpdxDocument", "software_Sbom", "Sbom"}:
                if _stated(element.get("spdxId")) or _stated(element.get("@id")):
                    return True
        return False

    def _spdx3_has_generation_context(self, data: dict[str, Any]) -> bool:
        """Whether a software_Sbom element states a lifecycle phase the specification defines."""
        elements = data.get("@graph", data.get("elements", []))
        if not isinstance(elements, list):
            return False
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_type = _text(element.get("type") or element.get("@type")).rsplit("/", 1)[-1]
            if element_type not in {"software_Sbom", "Sbom"}:
                continue
            raw = element.get("software_sbomType") or element.get("sbomType")
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                if _text(value).rsplit("/", 1)[-1].lower() in SPDX3_SBOM_TYPES:
                    return True
        return False

    @staticmethod
    def _spdx3_producer_names(package: dict[str, Any], agents: dict[str, dict[str, Any]]) -> list[Any]:
        """Names for whoever originated or supplied a package.

        ``originatedBy`` is the producer and comes first. ``suppliedBy`` is
        the distributor, kept because a document naming only the party it has
        is still naming one.
        """
        values: list[Any] = []
        for key in ("originatedBy", "suppliedBy"):
            refs = package.get(key)
            if isinstance(refs, str):
                refs = [refs]
            if not isinstance(refs, list):
                continue
            for ref in refs:
                entity = agents.get(ref) if isinstance(ref, str) else (ref if isinstance(ref, dict) else None)
                if isinstance(entity, dict):
                    values.append(entity.get("name"))
                elif isinstance(ref, str) and _is_unknown(ref):
                    # NOASSERTION arrives as a bare string rather than a
                    # reference to an element. A reference that resolves to
                    # nothing names nobody, so it is not counted as one.
                    values.append(ref)
        return values

    @staticmethod
    def _spdx3_has_identifier(package: dict[str, Any]) -> bool:
        """Whether the package carries a look-up key."""
        if _stated(package.get("software_packageUrl")):
            return True
        for ext in iter_spdx3_external_identifiers(package):
            kind = _text(ext.get("externalIdentifierType")).rsplit("/", 1)[-1]
            if kind in SPDX3_IDENTIFIER_TYPES and _stated(ext.get("identifier")):
                return True
        return False

    @staticmethod
    def _spdx3_hashes(package: dict[str, Any]) -> list[dict[str, Any]]:
        """The Hash elements a package is verified by."""
        verified = package.get("verifiedUsing")
        if isinstance(verified, dict):
            verified = [verified]
        if not isinstance(verified, list):
            return []
        return [entry for entry in verified if isinstance(entry, dict)]

    @staticmethod
    def _spdx3_license_subjects(relationships: list[dict[str, Any]]) -> set[str]:
        """Packages that a licence relationship speaks about.

        Both relationship types count. ``hasDeclaredLicense`` is what the
        producer declares, which is what the standard asks for, and
        ``hasConcludedLicense`` is the SBOM author's own determination.
        """
        subjects: set[str] = set()
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            kind = _text(relationship.get("relationshipType")).rsplit("/", 1)[-1]
            if kind not in {"hasDeclaredLicense", "hasConcludedLicense"}:
                continue
            source = relationship.get("from")
            if _text(source):
                subjects.add(_text(source))
        return subjects

    @staticmethod
    def _spdx3_has_dependencies(relationships: list[dict[str, Any]], package_count: int) -> bool:
        """Whether the document states a dependency relationship."""
        if package_count < 2:
            return True
        wanted = {"dependsOn", "contains", "hasPrerequisite", "hasStaticLink", "hasDynamicLink"}
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            if _text(relationship.get("relationshipType")).rsplit("/", 1)[-1] in wanted:
                return True
        return False

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------

    def _ordered(self, findings: list[Finding]) -> list[Finding]:
        """Findings in the order the standard lists the elements."""
        order = {
            f"cisa-2026:{element.replace('_', '-')}": index
            for index, element in enumerate(self.METADATA_ELEMENTS + self.COMPONENT_ELEMENTS)
        }
        return sorted(findings, key=lambda finding: order.get(finding.id, len(order)))

    def _error_result(self, message: str) -> AssessmentResult:
        """A run that could not read the document, reported as an error rather than a score."""
        finding = Finding(
            id="cisa-2026:error",
            title="Assessment Error",
            description=message,
            status="error",
            severity="high",
        )
        return AssessmentResult(
            plugin_name=self.PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(
                total_findings=1,
                pass_count=0,
                fail_count=0,
                warning_count=0,
                error_count=1,
            ),
            findings=[finding],
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
                # Same keys as a scored run, so a consumer reading the
                # metadata does not have to branch on which path produced it.
                "sbom_format": "unknown",
                # A flag, as the other plugins set it. The message the view
                # shows comes from the finding.
                "error": True,
            },
        )
