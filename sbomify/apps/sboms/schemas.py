from __future__ import annotations

import logging
from datetime import date, datetime
from enum import Enum
from types import ModuleType
from typing import Any

from ninja import Schema
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from sbomify.apps.core.utils import set_values_if_not_empty
from sbomify.apps.teams.schemas import ContactProfileSchema

from .sbom_format_schemas import cyclonedx_1_3 as cdx13
from .sbom_format_schemas import cyclonedx_1_4 as cdx14
from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16
from .sbom_format_schemas import cyclonedx_1_7 as cdx17
from .sbom_format_schemas import spdx_2_3 as spdx23
from .sbom_format_schemas import spdx_3_0 as spdx30
from .sbom_format_schemas.spdx import Schema as LicenseSchema

logger = logging.getLogger(__name__)


class PublicStatusSchema(Schema):
    is_public: bool


class SBOMUploadRequest(Schema):
    id: str


class SBOMResponseSchema(BaseModel):
    """Schema for SBOM API responses.

    Note: NTIA compliance data is now available via the AssessmentRun model
    in the plugins app. Query assessment_runs with plugin_name="ntia-minimum-elements-2021".
    """

    id: str
    name: str
    version: str
    format: str
    format_version: str
    sbom_filename: str
    created_at: datetime
    source: str | None
    component_id: str
    component_name: str
    source_display: str


class DashboardSBOMUploadInfo(Schema):
    component_name: str
    sbom_name: str
    sbom_version: str | None = None
    created_at: datetime


class DashboardStatsResponse(Schema):
    total_products: int
    total_projects: int
    total_components: int
    latest_uploads: list[DashboardSBOMUploadInfo]


# Import core schemas to avoid duplication


class CycloneDXSupportedVersion(str, Enum):
    """
    Supported CycloneDX specification versions.

    To add support for a new CycloneDX version (e.g., 2.0):
    1. Add the version here: v2_0 = "2.0"
    2. Import the schema module at the top of this file: from sbomify.apps.sboms.sbom_format_schemas import cdx20
    3. Add it to the module_map in get_cyclonedx_module() below
    4. That's it! The API will automatically support the new version.
    """

    v1_3 = "1.3"
    v1_4 = "1.4"
    v1_5 = "1.5"
    v1_6 = "1.6"
    v1_7 = "1.7"


def get_cyclonedx_module(spec_version: CycloneDXSupportedVersion) -> ModuleType:
    """
    Get the appropriate CycloneDX schema module for a given version.

    When adding a new version, add it to this mapping.
    """
    module_map: dict[CycloneDXSupportedVersion, ModuleType] = {
        CycloneDXSupportedVersion.v1_3: cdx13,
        CycloneDXSupportedVersion.v1_4: cdx14,
        CycloneDXSupportedVersion.v1_5: cdx15,
        CycloneDXSupportedVersion.v1_6: cdx16,
        CycloneDXSupportedVersion.v1_7: cdx17,
        # Add new versions here:
        # CycloneDXSupportedVersion.v2_0: cdx20,
    }
    return module_map[spec_version]


def get_supported_cyclonedx_versions() -> list[str]:
    """Get list of supported CycloneDX version strings."""
    return [v.value for v in CycloneDXSupportedVersion]


def validate_cyclonedx_sbom(
    sbom_data: dict,
) -> tuple[
    cdx13.CyclonedxSoftwareBillOfMaterialsStandard
    | cdx14.CyclonedxSoftwareBillOfMaterialsStandard
    | cdx15.CyclonedxSoftwareBillOfMaterialsStandard
    | cdx16.CyclonedxSoftwareBillOfMaterialsStandard
    | cdx17.CyclonedxSoftwareBillOfMaterialsStandard,
    str,
]:
    """
    Validate a CycloneDX SBOM and return the validated payload and spec version.

    Args:
        sbom_data: Dictionary containing the SBOM data

    Returns:
        Tuple of (validated_payload, spec_version)

    Raises:
        ValueError: If the spec version is unsupported
        ValidationError: If the SBOM data is invalid for the detected version
    """
    spec_version = sbom_data.get("specVersion", "1.5")

    # Check if version is supported
    try:
        version_enum = CycloneDXSupportedVersion(spec_version)
    except ValueError:
        supported = ", ".join(get_supported_cyclonedx_versions())
        raise ValueError(f"Unsupported CycloneDX specVersion: {spec_version}. Supported versions: {supported}")

    # Get the appropriate module and validate
    module = get_cyclonedx_module(version_enum)
    payload = module.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data)

    return payload, spec_version


class BaseLicenseSchema(BaseModel):
    pass


class CustomLicenseSchema(BaseLicenseSchema):
    name: str
    url: str | None = None
    text: str | None = None

    def to_cyclonedx(
        self, spec_version: CycloneDXSupportedVersion
    ) -> cdx13.License2 | cdx14.License2 | cdx15.License2 | cdx16.License2 | cdx17.License2:
        CycloneDx = get_cyclonedx_module(spec_version)
        result = CycloneDx.License2(name=self.name)
        set_values_if_not_empty(result, url=self.url)

        # License acknowledgement added in 1.6
        if spec_version in [CycloneDXSupportedVersion.v1_6, CycloneDXSupportedVersion.v1_7]:
            if hasattr(CycloneDx, "LicenseAcknowledgementEnumeration"):
                result.acknowledgement = CycloneDx.LicenseAcknowledgementEnumeration.declared

        if self.text:
            result.text = CycloneDx.Attachment(content=self.text)
        return result


class ComponentSupplierContactSchema(BaseModel):
    """Schema for component supplier contact information."""

    model_config = ConfigDict(extra="ignore")
    name: str
    email: str | None = None
    phone: str | None = None
    bom_ref: str | None = None

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.email is not None:
            data["email"] = self.email
        if self.phone is not None:
            data["phone"] = self.phone
        if self.bom_ref is not None:
            data["bom_ref"] = self.bom_ref
        return data


class ComponentAuthorSchema(BaseModel):
    """Schema for component author information."""

    model_config = ConfigDict(extra="ignore")
    name: str
    email: str | None = None
    phone: str | None = None
    bom_ref: str | None = None

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.email is not None:
            data["email"] = self.email
        if self.phone is not None:
            data["phone"] = self.phone
        if self.bom_ref is not None:
            data["bom_ref"] = self.bom_ref
        return data


class SupplierSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = Field(default=None, serialization_exclude_when_none=True)
    url: list[str] | None = Field(default=None, serialization_exclude_when_none=True)
    address: str | None = Field(default=None, serialization_exclude_when_none=True)
    contacts: list[ComponentSupplierContactSchema] = Field(default_factory=list)

    @field_validator("url", mode="before")
    @classmethod
    def convert_url_to_list(cls, v):
        """
        Convert string URL to list format for compatibility with frontend.

        This validator automatically handles both input formats:
        - String input: "https://example.com" → ["https://example.com"]
        - List input: ["https://example.com"] → ["https://example.com"] (unchanged)

        This ensures backward compatibility while supporting multiple URLs.
        """
        if isinstance(v, str):
            return [v]
        return v

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.name is not None:
            data["name"] = self.name
        if self.url:
            data["url"] = self.url
        if self.address is not None:
            data["address"] = self.address
        if self.contacts:
            data["contacts"] = [contact.model_dump() for contact in self.contacts]
        else:
            data["contacts"] = []
        return data

    @field_validator("contacts", mode="before")
    @classmethod
    def clean_supplier_contacts(cls, v):
        """Clean supplier contact information by converting empty strings to None."""
        if isinstance(v, list):
            cleaned_contacts = []
            for contact in v:
                if isinstance(contact, dict):
                    # Convert empty strings to None for email validation
                    cleaned_contact = contact.copy()
                    if cleaned_contact.get("email") == "":
                        cleaned_contact["email"] = None
                    cleaned_contacts.append(cleaned_contact)
                else:
                    cleaned_contacts.append(contact)
            return cleaned_contacts
        return v


class ComponentMetaData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    supplier: SupplierSchema = Field(default_factory=SupplierSchema)
    manufacturer: SupplierSchema = Field(default_factory=SupplierSchema)
    authors: list[ComponentAuthorSchema] = Field(default_factory=list)
    licenses: list[LicenseSchema | CustomLicenseSchema | str] = Field(default_factory=list)
    lifecycle_phase: str | None = Field(default=None, serialization_exclude_when_none=False)
    contact_profile_id: str | None = Field(default=None, serialization_exclude_when_none=False)
    contact_profile: ContactProfileSchema | None = Field(default=None, serialization_exclude_when_none=False)
    uses_custom_contact: bool = True

    # Lifecycle event fields (aligned with Common Lifecycle Enumeration)
    release_date: date | None = Field(default=None, description="Release date of the component")
    end_of_support: date | None = Field(default=None, description="Date when bugfixes stop (security-only after this)")
    end_of_life: date | None = Field(default=None, description="Date when all support ends")

    @field_validator("authors", mode="before")
    @classmethod
    def clean_authors_contacts(cls, v):
        """Clean author contact information by converting empty strings to None."""
        if isinstance(v, list):
            cleaned_authors = []
            for author in v:
                if isinstance(author, dict):
                    # Convert empty strings to None for email validation
                    cleaned_author = author.copy()
                    if cleaned_author.get("email") == "":
                        cleaned_author["email"] = None
                    cleaned_authors.append(cleaned_author)
                else:
                    cleaned_authors.append(author)
            return cleaned_authors
        return v

    def to_cyclonedx(
        self, spec_version: CycloneDXSupportedVersion
    ) -> cdx13.Metadata | cdx14.Metadata | cdx15.Metadata | cdx16.Metadata | cdx17.Metadata:
        CycloneDx = get_cyclonedx_module(spec_version)
        result = CycloneDx.Metadata()

        if self.supplier and (
            self.supplier.name or self.supplier.url or self.supplier.address or self.supplier.contacts
        ):
            result.supplier = CycloneDx.OrganizationalEntity()
            set_values_if_not_empty(result.supplier, name=self.supplier.name)

            # PostalAddress added in 1.6
            if (
                spec_version in [CycloneDXSupportedVersion.v1_6, CycloneDXSupportedVersion.v1_7]
                and self.supplier.address
            ):
                result.supplier.address = CycloneDx.PostalAddress(streetAddress=self.supplier.address)

            if self.supplier.url:
                result.supplier.url = self.supplier.url

            if self.supplier.contacts:
                result.supplier.contact = []
                for contact_data in self.supplier.contacts:
                    c = CycloneDx.OrganizationalContact()
                    set_values_if_not_empty(
                        c, name=contact_data.name, email=contact_data.email, phone=contact_data.phone
                    )
                    result.supplier.contact.append(c)

        # Component Manufacturer handling:
        # - 1.3-1.5: use metadata.manufacture (canonical field for component manufacturer)
        # - 1.6-1.7: use metadata.manufacturer (forward-looking, with PostalAddress support)
        if self.manufacturer and (
            self.manufacturer.name or self.manufacturer.url or self.manufacturer.address or self.manufacturer.contacts
        ):
            mfg_entity = CycloneDx.OrganizationalEntity()
            set_values_if_not_empty(mfg_entity, name=self.manufacturer.name)

            if self.manufacturer.url:
                mfg_entity.url = self.manufacturer.url

            if self.manufacturer.contacts:
                mfg_entity.contact = []
                for contact_data in self.manufacturer.contacts:
                    c = CycloneDx.OrganizationalContact()
                    set_values_if_not_empty(
                        c, name=contact_data.name, email=contact_data.email, phone=contact_data.phone
                    )
                    mfg_entity.contact.append(c)

            # Version-specific field assignment
            if spec_version in [
                CycloneDXSupportedVersion.v1_3,
                CycloneDXSupportedVersion.v1_4,
                CycloneDXSupportedVersion.v1_5,
            ]:
                # Use metadata.manufacture for 1.3-1.5
                result.manufacture = mfg_entity
            else:
                # Use metadata.manufacturer for 1.6+ (with PostalAddress support)
                if self.manufacturer.address:
                    mfg_entity.address = CycloneDx.PostalAddress(streetAddress=self.manufacturer.address)
                result.manufacturer = mfg_entity

        if self.authors:
            result.authors = []
            for author_data in self.authors:
                c = CycloneDx.OrganizationalContact()
                set_values_if_not_empty(c, name=author_data.name, email=author_data.email, phone=author_data.phone)
                result.authors.append(c)

        if self.licenses:
            licenses_list = []
            for component_license in self.licenses:
                cdx_lic: CycloneDx.License | None = None

                if isinstance(component_license, CustomLicenseSchema):
                    cdx_lic = component_license.to_cyclonedx(spec_version)
                elif isinstance(component_license, (str, LicenseSchema)):
                    if isinstance(component_license, Enum):
                        license_identifier = component_license.value
                    else:
                        license_identifier = str(component_license)

                    # Check if this is a license expression (contains operators)
                    from sbomify.apps.core.licensing_utils import is_license_expression

                    if is_license_expression(license_identifier):
                        # License expressions should be stored as name, not id
                        cdx_lic = CycloneDx.License(name=license_identifier)
                    else:
                        try:
                            # Individual SPDX IDs should be stored as id
                            cdx_lic = CycloneDx.License(id=license_identifier)
                        except Exception:  # Broad catch, consider pydantic.ValidationError if possible
                            # Fallback for non-SPDX IDs or other cases
                            cdx_lic = CycloneDx.License(name=license_identifier)
                else:
                    # Log warning for unexpected license types that are being skipped
                    logger.warning(
                        "Skipping unknown license type %s during CycloneDX conversion",
                        type(component_license).__name__,
                    )

                # Skip if no license was created (unknown type)
                if cdx_lic is None:
                    continue

                # CycloneDX 1.7+ requires licenses to be wrapped in LicenseChoice1/2
                if spec_version == CycloneDXSupportedVersion.v1_7:
                    # Wrap License in LicenseChoice1
                    licenses_list.append(CycloneDx.LicenseChoice1(license=cdx_lic))
                else:
                    licenses_list.append(cdx_lic)

            if licenses_list:
                result.licenses = CycloneDx.LicenseChoice(licenses_list)

        # Lifecycles added in 1.5
        if self.lifecycle_phase and spec_version not in [
            CycloneDXSupportedVersion.v1_3,
            CycloneDXSupportedVersion.v1_4,
        ]:
            result.lifecycles = [CycloneDx.Lifecycles(phase=self.lifecycle_phase)]
        return result


class ComponentMetaDataUpdate(BaseModel):
    """Schema for updating component metadata (excludes read-only fields like id and name)."""

    model_config = ConfigDict(extra="ignore")

    contact_profile_id: str | None = None
    supplier: SupplierSchema = Field(default_factory=SupplierSchema)
    authors: list[ComponentAuthorSchema] = Field(default_factory=list)
    licenses: list[LicenseSchema | CustomLicenseSchema | str] = Field(default_factory=list)
    lifecycle_phase: str | None = None

    # Lifecycle event fields (aligned with Common Lifecycle Enumeration)
    release_date: date | None = None
    end_of_support: date | None = None
    end_of_life: date | None = None

    @field_validator("authors", mode="before")
    @classmethod
    def clean_authors_contacts(cls, v):
        """Clean author contact information by converting empty strings to None."""
        if isinstance(v, list):
            cleaned_authors = []
            for author in v:
                if isinstance(author, dict):
                    # Convert empty strings to None for email validation
                    cleaned_author = author.copy()
                    if cleaned_author.get("email") == "":
                        cleaned_author["email"] = None
                    cleaned_authors.append(cleaned_author)
                else:
                    cleaned_authors.append(author)
            return cleaned_authors
        return v


class ComponentMetaDataPatch(BaseModel):
    """Schema for partially updating component metadata using PATCH (all fields optional)."""

    model_config = ConfigDict(extra="ignore")

    contact_profile_id: str | None = None
    supplier: SupplierSchema | None = None
    authors: list[ComponentAuthorSchema] | None = None
    licenses: list[LicenseSchema | CustomLicenseSchema | str] | None = None
    lifecycle_phase: str | None = None

    # Lifecycle event fields (aligned with Common Lifecycle Enumeration)
    release_date: date | None = None
    end_of_support: date | None = None
    end_of_life: date | None = None

    @field_validator("authors", mode="before")
    @classmethod
    def clean_authors_contacts(cls, v):
        """Clean author contact information by converting empty strings to None."""
        if isinstance(v, list):
            cleaned_authors = []
            for author in v:
                if isinstance(author, dict):
                    # Convert empty strings to None for email validation
                    cleaned_author = author.copy()
                    if cleaned_author.get("email") == "":
                        cleaned_author["email"] = None
                    cleaned_authors.append(cleaned_author)
                else:
                    cleaned_authors.append(author)
            return cleaned_authors
        return v


class ComponentMetadataRequest(BaseModel):
    version: str


class SBOMFormat(str, Enum):
    spdx = "spdx"
    cyclonedx = "cyclonedx"


class SPDXSupportedVersion(str, Enum):
    """
    Supported SPDX specification versions.

    To add support for a new SPDX version (e.g., 3.0):
    1. Add the version here: v3_0 = "3.0"
    2. Import the schema module at the top of this file, for example:
       from sbomify.apps.sboms.sbom_format_schemas import spdx_3_0 as spdx30
    3. Add it to the module_map in get_spdx_module() below
    4. That's it! The API will automatically support the new version.

    Note: SPDX 2.x versions share compatible schemas, but SPDX 3.0 will require
    a different schema structure.
    """

    v2_2 = "2.2"
    v2_3 = "2.3"
    v3_0 = "3.0"


def get_spdx_module(spec_version: SPDXSupportedVersion) -> ModuleType:
    """
    Get the appropriate SPDX schema module for a given version.

    When adding a new version, add it to this mapping.

    Note: This function provides the strict generated Pydantic schema for SPDX.
    It is used by:
    - sbomify.apps.sboms.builders for generating aggregated SBOMs (strict output)

    For parsing uploaded SBOMs, use the lenient SPDXSchema class instead,
    which allows extra fields and provides aliased properties.
    """
    module_map: dict[SPDXSupportedVersion, ModuleType] = {
        # SPDX 2.2 and 2.3 are compatible, use 2.3 schema for both
        SPDXSupportedVersion.v2_2: spdx23,
        SPDXSupportedVersion.v2_3: spdx23,
        SPDXSupportedVersion.v3_0: spdx30,
    }
    return module_map[spec_version]


def get_supported_spdx_versions() -> list[str]:
    """Get list of supported SPDX version strings."""
    return [v.value for v in SPDXSupportedVersion]


def _detect_spdx3_context(sbom_data: dict) -> bool:
    """Check if SBOM data has an @context indicating SPDX 3.0."""
    context = sbom_data.get("@context", "")
    if isinstance(context, str):
        return "spdx.org/rdf/3.0" in context
    if isinstance(context, list):
        return any("spdx.org/rdf/3.0" in str(c) for c in context)
    return False


def validate_spdx_sbom(sbom_data: dict) -> tuple["SPDXSchema | SPDX3Schema", str]:
    """
    Validate an SPDX SBOM and return the validated payload and spec version.

    For SPDX 2.x, uses the lenient SPDXSchema (allows extra fields, provides
    aliased properties like .version for versionInfo).
    For SPDX 3.x, uses SPDX3Schema which parses the graph-based element structure.

    Detects SPDX 3.0 by either:
    - `@context` containing "spdx.org/rdf/3.0" (spec-compliant)
    - `spdxVersion` starting with "SPDX-3." (legacy format)

    Args:
        sbom_data: Dictionary containing the SBOM data

    Returns:
        Tuple of (validated_payload, spdx_version)

    Raises:
        ValueError: If the SPDX version is unsupported
        ValidationError: If the SBOM data is invalid for the detected version
    """
    # Detect SPDX 3.0 via @context (spec-compliant format has no spdxVersion at root)
    if _detect_spdx3_context(sbom_data):
        payload: SPDXSchema | SPDX3Schema = SPDX3Schema.model_validate(sbom_data)
        # Extract version from CreationInfo.specVersion in the graph
        full_version = payload.spec_version
        return payload, full_version

    # Fall back to spdxVersion-based detection
    spdx_version_str = sbom_data.get("spdxVersion", "")
    if not spdx_version_str.startswith("SPDX-"):
        raise ValueError(f"Invalid spdxVersion format: {spdx_version_str}. Expected format: SPDX-X.X")

    full_version = spdx_version_str.removeprefix("SPDX-")

    # Normalize SPDX 3.x.y patch versions to "3.0" for enum lookup
    if full_version.startswith("3."):
        normalized_version = "3.0"
    else:
        normalized_version = full_version

    # Check if version is supported
    try:
        SPDXSupportedVersion(normalized_version)
    except ValueError:
        supported = ", ".join(get_supported_spdx_versions())
        raise ValueError(f"Unsupported SPDX version: {full_version}. Supported versions: {supported}")

    # Branch on major version for parsing
    if normalized_version == "3.0":
        payload = SPDX3Schema.model_validate(sbom_data)
    else:
        payload = SPDXSchema(**sbom_data)

    # Return the full version string (e.g., "3.0.1") for DB storage fidelity
    return payload, full_version


class SPDXPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    version: str = Field("", alias="versionInfo")
    license_concluded: str = Field("", alias="licenseConcluded")
    license_declared: str = Field("", alias="licenseDeclared")

    @property
    def license(self) -> str:
        if self.license_declared and self.license_declared != "NOASSERTION":
            return self.license_declared
        return self.license_concluded

    @property
    def purl(self) -> str:
        """
        Create package url id from given package data.
        Works with SPDX format for now but will get support for CycloneDX in the future.
        """
        for external_ref in getattr(self, "externalRefs", []):
            if external_ref["referenceType"] == "purl":
                return external_ref["referenceLocator"]
        return f"pkg:/{self.name}@{self.version}"


class SPDXSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    spdx_id: str = Field(..., alias="SPDXID")
    creation_info: dict = Field(..., alias="creationInfo")
    data_license: str = Field(..., alias="dataLicense")
    name: str
    spdx_version: str = Field(..., alias="spdxVersion")
    packages: list[SPDXPackage] = Field(default_factory=list)


class SPDX3Package(BaseModel):
    """Lenient parser for SPDX 3.0 software_Package elements."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    version: str = Field("", alias="software_packageVersion")
    spdx_id: str = Field("", alias="spdxId")
    type: str = ""

    @property
    def purl(self) -> str:
        for ext_id in getattr(self, "externalIdentifiers", []):
            if isinstance(ext_id, dict) and ext_id.get("externalIdentifierType") in {"purl", "packageURL"}:
                return ext_id["identifier"]
        return f"pkg:/{self.name}@{self.version}"


class SPDX3Schema(BaseModel):
    """Lenient parser for SPDX 3.0 documents.

    Accepts both spec-compliant (@context/@graph) and legacy (spdxVersion/elements)
    formats. A model_validator normalizes legacy → graph format so all downstream
    code only deals with the graph format.

    This class provides properties to extract typed elements from the graph and
    find the SpdxDocument element for document-level metadata (name, version, etc.).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    context: str = Field(alias="@context")
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
            from .sbom_format_schemas.spdx_3_0 import _normalize_legacy_to_graph

            return _normalize_legacy_to_graph(data)

        raise ValueError(
            "Unsupported SPDX 3.0 document format: expected '@context'/'@graph' or "
            "legacy 'spdxVersion'/'elements' structure."
        )

    @property
    def _spdx_document(self) -> dict[str, Any] | None:
        """Find the SpdxDocument element in the graph."""
        for elem in self.graph:
            if elem.get("type") == "SpdxDocument":
                return elem
        return None

    @property
    def name(self) -> str:
        """Get document name from the SpdxDocument element."""
        doc = self._spdx_document
        if doc:
            return doc.get("name", "")
        return ""

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
    def spdx_version(self) -> str:
        """Compatibility property: return SPDX-prefixed version string."""
        return f"SPDX-{self.spec_version}"

    @property
    def packages(self) -> list[SPDX3Package]:
        """Extract software_Package elements from the graph."""
        result = []
        for elem in self.graph:
            if elem.get("type") == "software_Package":
                result.append(SPDX3Package.model_validate(elem))
        return result

    @property
    def relationships(self) -> list[dict[str, Any]]:
        """Extract Relationship elements from the graph."""
        return [elem for elem in self.graph if elem.get("type") == "Relationship"]


# Patch OrganizationalContact to ignore extra fields
cdx13.OrganizationalContact.model_config = ConfigDict(extra="ignore")
cdx14.OrganizationalContact.model_config = ConfigDict(extra="ignore")
cdx15.OrganizationalContact.model_config = ConfigDict(extra="ignore")
cdx16.OrganizationalContact.model_config = ConfigDict(extra="ignore")


# Product/Project/Component CRUD schemas moved to core/schemas.py
