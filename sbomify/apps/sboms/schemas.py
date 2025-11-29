from __future__ import annotations

from datetime import datetime
from enum import Enum
from types import ModuleType
from typing import Any

from ninja import Schema
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from sbomify.apps.core.utils import set_values_if_not_empty
from sbomify.apps.teams.schemas import ContactProfileSchema

from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16
from .sbom_format_schemas import cyclonedx_1_7 as cdx17
from .sbom_format_schemas.spdx import Schema as LicenseSchema


class PublicStatusSchema(Schema):
    is_public: bool


class SBOMUploadRequest(Schema):
    id: str


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

    v1_5 = "1.5"
    v1_6 = "1.6"
    v1_7 = "1.7"


def get_cyclonedx_module(spec_version: CycloneDXSupportedVersion) -> ModuleType:
    """
    Get the appropriate CycloneDX schema module for a given version.

    When adding a new version, add it to this mapping.
    """
    module_map: dict[CycloneDXSupportedVersion, ModuleType] = {
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
    cdx15.CyclonedxSoftwareBillOfMaterialsStandard
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

    def to_cyclonedx(self, spec_version: CycloneDXSupportedVersion) -> cdx15.License2 | cdx16.License2 | cdx17.License2:
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
    authors: list[ComponentAuthorSchema] = Field(default_factory=list)
    licenses: list[LicenseSchema | CustomLicenseSchema | str] = Field(default_factory=list)
    lifecycle_phase: str | None = Field(default=None, serialization_exclude_when_none=False)
    contact_profile_id: str | None = Field(default=None, serialization_exclude_when_none=False)
    contact_profile: ContactProfileSchema | None = Field(default=None, serialization_exclude_when_none=False)
    uses_custom_contact: bool = True

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

    def to_cyclonedx(self, spec_version: CycloneDXSupportedVersion) -> cdx15.Metadata | cdx16.Metadata | cdx17.Metadata:
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

        if self.authors:
            result.authors = []
            for author_data in self.authors:
                c = CycloneDx.OrganizationalContact()
                set_values_if_not_empty(c, name=author_data.name, email=author_data.email, phone=author_data.phone)
                result.authors.append(c)

        if self.licenses:
            licenses_list = []
            for component_license in self.licenses:
                if isinstance(component_license, CustomLicenseSchema):
                    licenses_list.append(component_license.to_cyclonedx(spec_version))
                elif isinstance(component_license, (str, LicenseSchema)):
                    if isinstance(component_license, Enum):
                        license_identifier = component_license.value
                    else:
                        license_identifier = str(component_license)

                    # Check if this is a license expression (contains operators)
                    license_operators = ["AND", "OR", "WITH"]
                    is_expression = any(f" {op} " in license_identifier for op in license_operators)

                    if is_expression:
                        # License expressions should be stored as name, not id
                        cdx_lic = CycloneDx.License(name=license_identifier)
                    else:
                        try:
                            # Individual SPDX IDs should be stored as id
                            cdx_lic = CycloneDx.License(id=license_identifier)
                        except Exception:  # Broad catch, consider pydantic.ValidationError if possible
                            # Fallback for non-SPDX IDs or other cases
                            cdx_lic = CycloneDx.License(name=license_identifier)
                    licenses_list.append(cdx_lic)

            if licenses_list:
                result.licenses = CycloneDx.LicenseChoice(licenses_list)

        if self.lifecycle_phase:
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
    2. If needed, create version-specific schema handling
    3. Add it to validate_spdx_sbom() function below
    4. That's it! The API will automatically support the new version.

    Note: Currently all SPDX 2.x versions use the same schema (SPDXSchema),
    but SPDX 3.0 will require a different schema structure.
    """

    v2_2 = "2.2"
    v2_3 = "2.3"
    # v3_0 = "3.0"  # Uncomment when SPDX 3.0 schema is available


def get_supported_spdx_versions() -> list[str]:
    """Get list of supported SPDX version strings."""
    return [v.value for v in SPDXSupportedVersion]


def validate_spdx_sbom(sbom_data: dict) -> tuple["SPDXSchema", str]:
    """
    Validate an SPDX SBOM and return the validated payload and spec version.

    Args:
        sbom_data: Dictionary containing the SBOM data

    Returns:
        Tuple of (validated_payload, spdx_version)

    Raises:
        ValueError: If the SPDX version is unsupported
        ValidationError: If the SBOM data is invalid for the detected version
    """
    # Extract version from spdxVersion field (e.g., "SPDX-2.3" -> "2.3")
    spdx_version_str = sbom_data.get("spdxVersion", "")
    if not spdx_version_str.startswith("SPDX-"):
        raise ValueError(f"Invalid spdxVersion format: {spdx_version_str}. Expected format: SPDX-X.X")

    version = spdx_version_str.removeprefix("SPDX-")

    # Check if version is supported
    try:
        SPDXSupportedVersion(version)
    except ValueError:
        supported = ", ".join(get_supported_spdx_versions())
        raise ValueError(f"Unsupported SPDX version: {version}. Supported versions: {supported}")

    # For now, all SPDX 2.x versions use the same schema
    # When SPDX 3.0 is added, we'll need version-specific schema selection here
    from pydantic import ValidationError as PydanticValidationError

    try:
        payload = SPDXSchema(**sbom_data)
    except PydanticValidationError as e:
        raise e

    return payload, version


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


# Patch OrganizationalContact to ignore extra fields
cdx15.OrganizationalContact.model_config = ConfigDict(extra="ignore")
cdx16.OrganizationalContact.model_config = ConfigDict(extra="ignore")


# Product/Project/Component CRUD schemas moved to core/schemas.py
