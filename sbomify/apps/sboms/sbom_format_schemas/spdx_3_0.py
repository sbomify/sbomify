"""
Hand-written Pydantic models for SPDX 3.0.

These models cannot be auto-generated because SPDX 3.0 uses JSON-LD, which is
incompatible with datamodel-codegen. They cover the key types needed for upload
validation, metadata extraction, and aggregated SBOM generation.

SPDX 3.0 uses a JSON-LD graph structure (spec §4.4 "Serialization"):
- Root object has `@context` (JSON-LD context URL) and `@graph` (array of elements)
- SpdxDocument is an element inside `@graph`, not the root object
- CreationInfo is shared via blank node references (`"_:creationInfo"`)
- Version info comes from CreationInfo.specVersion (e.g. "3.0.1")

For backward compatibility, we also accept legacy format with `spdxVersion`/`elements`
at the root level. A model_validator normalizes legacy → graph format.

Spec reference: https://spdx.github.io/spdx-spec/v3.0.1/
Model reference: https://spdx.github.io/spdx-spec/v3.0.1/model/
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

# =============================================================================
# Constants
# =============================================================================

SPDX_30_CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"

# =============================================================================
# Enums
# =============================================================================


class RelationshipType(str, Enum):
    """SPDX 3.0 relationship types (subset covering common cases).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Vocabularies/RelationshipType/
    """

    DESCRIBES = "describes"
    DESCRIBED_BY = "describedBy"
    CONTAINS = "contains"
    CONTAINED_BY = "containedBy"
    DEPENDS_ON = "dependsOn"
    DEPENDENCY_OF = "dependencyOf"
    GENERATES = "generates"
    GENERATED_FROM = "generatedFrom"
    HAS_DECLARED_LICENSE = "hasDeclaredLicense"
    HAS_CONCLUDED_LICENSE = "hasConcludedLicense"
    OTHER = "other"
    AFFECTS = "affects"
    FIXED_IN = "fixedIn"
    HAS_ASSOCIATED_VULNERABILITY = "hasAssociatedVulnerability"
    PUBLISHED_BY = "publishedBy"
    AVAILABLE_FROM = "availableFrom"
    COPIED_TO = "copiedTo"
    HAS_DISTRIBUTION_ARTIFACT = "hasDistributionArtifact"
    BUILD_TOOL = "buildTool"
    DEV_TOOL = "devTool"
    TEST_TOOL = "testTool"
    DOCUMENTATION = "documentation"
    OPTIONAL_DEPENDENCY = "optionalDependency"
    PROVIDED_DEPENDENCY = "providedDependency"
    RUNTIME_DEPENDENCY = "runtimeDependency"
    DEV_DEPENDENCY = "devDependency"
    EXAMPLE = "example"
    VARIANT = "variant"
    PACKAGED_BY = "packagedBy"
    TESTED_ON = "testedOn"


class ElementType(str, Enum):
    """SPDX 3.0 element types (subset covering common cases).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/ (see Core and Software profiles)
    """

    SOFTWARE_PACKAGE = "software_Package"
    SOFTWARE_FILE = "software_File"
    SOFTWARE_SNIPPET = "software_Snippet"
    SOFTWARE_SBOM = "software_Sbom"
    RELATIONSHIP = "Relationship"
    ANNOTATION = "Annotation"
    ORGANIZATION = "Organization"
    PERSON = "Person"
    SOFTWARE_AGENT = "SoftwareAgent"
    TOOL = "Tool"
    SPDX_DOCUMENT = "SpdxDocument"
    CREATION_INFO = "CreationInfo"
    HASH = "Hash"
    EXTERNAL_REF = "ExternalRef"
    EXTERNAL_IDENTIFIER = "ExternalIdentifier"


# =============================================================================
# Core Models
# =============================================================================


class CreationInfo(BaseModel):
    """SPDX 3.0 CreationInfo — metadata about who/what/when created elements.

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/CreationInfo/

    Note: dataLicense is NOT on CreationInfo in the spec — it belongs on SpdxDocument.
    The previous implementation incorrectly placed it here.
    """

    model_config = ConfigDict(extra="allow")

    type: str = "CreationInfo"
    specVersion: str = Field(
        default="3.0.1",
        description="Version of the SPDX specification used.",
    )
    created: str = Field(
        ...,
        description="Date and time the element was created (ISO 8601).",
    )
    createdBy: list[str] = Field(
        default_factory=list,
        description="spdxIds of Agents who created this element.",
    )
    createdUsing: list[str] = Field(
        default_factory=list,
        description="spdxIds of Tools used to create this element.",
    )
    comment: str | None = None


class ExternalIdentifier(BaseModel):
    """SPDX 3.0 ExternalIdentifier for PURLs, CPEs, etc.

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/ExternalIdentifier/
    """

    model_config = ConfigDict(extra="allow")

    type: str = "ExternalIdentifier"
    externalIdentifierType: str
    identifier: str
    identifierLocator: list[str] = Field(default_factory=list)
    issuingAuthority: str | None = None
    comment: str | None = None


class ExternalRef(BaseModel):
    """SPDX 3.0 ExternalRef.

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/ExternalRef/

    Note: The spec uses `externalRefType` (not `externalReferenceType` as in SPDX 2.x).
    """

    model_config = ConfigDict(extra="allow")

    type: str = "ExternalRef"
    externalRefType: str
    locator: list[str] = Field(default_factory=list)
    contentType: str | None = None
    comment: str | None = None


class Hash(BaseModel):
    """SPDX 3.0 Hash (integrity method).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Hash/

    Note: Named `Hash` in the spec (not `IntegrityMethod` — that's the abstract parent).
    """

    model_config = ConfigDict(extra="allow")

    type: str = "Hash"
    algorithm: str
    hashValue: str


# =============================================================================
# Element Models
# =============================================================================


class Element(BaseModel):
    """Base SPDX 3.0 Element — the fundamental unit of the SPDX graph.

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Element/

    Note: `creationInfo` accepts both inline CreationInfo objects and string references
    (e.g. `"_:creationInfo"` blank node ID) for shared CreationInfo.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    spdxId: str
    creationInfo: CreationInfo | str | None = None
    name: str | None = None
    summary: str | None = None
    description: str | None = None
    comment: str | None = None
    externalIdentifier: list[ExternalIdentifier] = Field(
        default_factory=list,
        validation_alias=AliasChoices("externalIdentifier", "externalIdentifiers"),
    )
    externalRef: list[ExternalRef] = Field(default_factory=list)
    verifiedUsing: list[Hash] = Field(default_factory=list)


class SoftwarePackage(Element):
    """SPDX 3.0 software_Package element.

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Software/Classes/Package/
    """

    software_packageVersion: str | None = Field(
        default=None,
        description="Version of the package.",
    )
    software_packageUrl: str | None = Field(
        default=None,
        description="Package URL (purl) for the package.",
    )
    software_downloadLocation: str | None = Field(
        default=None,
        description="Download location for the package.",
    )
    software_homePage: str | None = None
    software_sourceInfo: str | None = None
    suppliedBy: str | None = Field(
        default=None,
        description="spdxId of the Agent supplying this package.",
    )
    originatedBy: list[str] = Field(default_factory=list)


class Relationship(Element):
    """SPDX 3.0 Relationship element.

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Relationship/

    Note: `to` uses default_factory=list for lenient parsing, though the spec requires
    at least one entry. Some real-world SBOMs emit empty `to` arrays.
    """

    relationshipType: str
    from_: str = Field(..., alias="from")
    to: list[str] = Field(default_factory=list)
    completeness: str | None = None


class Organization(Element):
    """SPDX 3.0 Organization element (Agent subclass).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Organization/
    """

    pass


class Person(Element):
    """SPDX 3.0 Person element (Agent subclass).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Person/
    """

    pass


class SoftwareAgent(Element):
    """SPDX 3.0 SoftwareAgent element (Agent subclass).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/SoftwareAgent/
    """

    pass


class Tool(Element):
    """SPDX 3.0 Tool element (Agent subclass).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Tool/
    """

    pass


class Annotation(Element):
    """SPDX 3.0 Annotation element."""

    annotationType: str | None = None
    subject: str | None = None
    statement: str | None = None


# =============================================================================
# Document Model
# =============================================================================


def _is_spdx3_context(context: Any) -> bool:
    """Check if a @context value indicates SPDX 3.0."""
    if isinstance(context, str):
        return "spdx.org/rdf/3.0" in context
    if isinstance(context, list):
        return any("spdx.org/rdf/3.0" in str(c) for c in context)
    if isinstance(context, dict):
        return "spdx.org/rdf/3.0" in str(context)
    return False


def _normalize_legacy_to_graph(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy SPDX 3.0 format (spdxVersion/elements) to @context/@graph.

    In legacy format, the root object acts as the SpdxDocument with fields like
    spdxVersion, name, spdxId, dataLicense, creationInfo, elements, rootElement.

    This normalizer creates a proper @context/@graph structure where the SpdxDocument
    is an element inside the graph.
    """
    elements = data.get("elements", [])

    # Build the SpdxDocument element from root-level fields
    doc_element: dict[str, Any] = {
        "type": "SpdxDocument",
    }
    if "spdxId" in data:
        doc_element["spdxId"] = data["spdxId"]
    if "name" in data:
        doc_element["name"] = data["name"]
    if "dataLicense" in data:
        doc_element["dataLicense"] = data["dataLicense"]
    if "rootElement" in data:
        doc_element["rootElement"] = data["rootElement"]
    if "comment" in data:
        doc_element["comment"] = data["comment"]

    # Promote inline creationInfo dict to a proper CreationInfo graph element.
    # In spec-compliant format, creationInfo is a string reference to a
    # CreationInfo element in @graph. Legacy format has it as an inline dict.
    # Work on a local copy to avoid mutating data["elements"] in-place.
    elements = [dict(e) for e in elements]
    creation_info_id = "_:creationInfo"
    if "creationInfo" in data:
        ci = data["creationInfo"]
        if isinstance(ci, dict):
            ci_element = dict(ci)
            ci_element.setdefault("type", "CreationInfo")
            ci_element.setdefault("@id", creation_info_id)
            elements.insert(0, ci_element)
            doc_element["creationInfo"] = creation_info_id
            # Replace inline creationInfo dicts on elements with the blank node
            # reference so the normalized output uses the shared pattern consistently.
            for elem in elements:
                if isinstance(elem.get("creationInfo"), dict):
                    elem["creationInfo"] = creation_info_id
        else:
            # Already a string reference
            doc_element["creationInfo"] = ci

    # SpdxDocument.element contains the spdxIds of all elements
    doc_element["element"] = [e.get("spdxId", "") for e in elements if e.get("spdxId")]

    # Derive specVersion from the spdxVersion field
    spdx_version = data.get("spdxVersion", "SPDX-3.0.1")
    spec_version = spdx_version.removeprefix("SPDX-")

    graph = list(elements) + [doc_element]

    return {
        "@context": SPDX_30_CONTEXT,
        "@graph": graph,
        # Preserve for downstream access
        "_legacy_spdxVersion": spdx_version,
        "_legacy_specVersion": spec_version,
    }


class SPDX3Document(BaseModel):
    """Root SPDX 3.0 document model (JSON-LD serialization envelope).

    Spec: https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/SpdxDocument/
    Serialization: https://spdx.github.io/spdx-spec/v3.0.1/annexes/serialization/

    SPDX 3.0 uses a JSON-LD graph structure with `@context` and `@graph`.
    The SpdxDocument is an element inside `@graph`, not the root object.

    For backward compatibility, also accepts legacy format with `spdxVersion`/`elements`
    at the root level. A model_validator normalizes this to @context/@graph.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    context: str | list[Any] | dict[str, Any] = Field(alias="@context")
    graph: list[dict[str, Any]] = Field(alias="@graph")

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_format(cls, data: Any) -> Any:
        """Normalize legacy spdxVersion/elements format to @context/@graph."""
        if not isinstance(data, dict):
            return data

        # Already in spec-compliant format
        if "@context" in data and "@graph" in data:
            return data

        # Legacy format: has spdxVersion and elements
        if "spdxVersion" in data and "elements" in data:
            return _normalize_legacy_to_graph(data)

        return data

    @property
    def spdx_document(self) -> dict[str, Any] | None:
        """Find the SpdxDocument element in the graph."""
        for elem in self.graph:
            if elem.get("type") == ElementType.SPDX_DOCUMENT.value:
                return elem
        return None

    @property
    def spec_version(self) -> str:
        """Get the spec version from CreationInfo in the graph, or legacy field."""
        # Check for legacy version stored during normalization
        legacy = getattr(self, "_legacy_specVersion", None)
        if legacy:
            return legacy

        # Look for CreationInfo element in graph
        for elem in self.graph:
            if elem.get("type") == "CreationInfo":
                return elem.get("specVersion", "3.0.1")

        # Look for creationInfo on any element
        for elem in self.graph:
            ci = elem.get("creationInfo")
            if isinstance(ci, dict) and "specVersion" in ci:
                return ci["specVersion"]

        return "3.0.1"

    @property
    def doc_name(self) -> str:
        """Get the document name from the SpdxDocument element."""
        doc = self.spdx_document
        if doc:
            return doc.get("name", "")
        return ""

    @property
    def data_license(self) -> str | None:
        """Get data license from the SpdxDocument element."""
        doc = self.spdx_document
        if doc:
            return doc.get("dataLicense")
        return None

    @property
    def root_element(self) -> list[str]:
        """Get root element refs from the SpdxDocument element."""
        doc = self.spdx_document
        if doc:
            re = doc.get("rootElement", [])
            if isinstance(re, list):
                return re
            return [re] if re else []
        return []

    @property
    def packages(self) -> list[SoftwarePackage]:
        """Extract software_Package elements from the graph."""
        result = []
        for elem in self.graph:
            if elem.get("type") == ElementType.SOFTWARE_PACKAGE.value:
                result.append(SoftwarePackage.model_validate(elem))
        return result

    @property
    def relationships(self) -> list[Relationship]:
        """Extract Relationship elements from the graph."""
        result = []
        for elem in self.graph:
            if elem.get("type") == ElementType.RELATIONSHIP.value:
                result.append(Relationship.model_validate(elem))
        return result

    @property
    def organizations(self) -> list[Organization]:
        """Extract Organization elements from the graph."""
        result = []
        for elem in self.graph:
            if elem.get("type") == ElementType.ORGANIZATION.value:
                result.append(Organization.model_validate(elem))
        return result

    @property
    def tools(self) -> list[Tool]:
        """Extract Tool elements from the graph."""
        result = []
        for elem in self.graph:
            if elem.get("type") == ElementType.TOOL.value:
                result.append(Tool.model_validate(elem))
        return result
