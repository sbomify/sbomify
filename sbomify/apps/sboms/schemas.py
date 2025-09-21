from __future__ import annotations

from datetime import datetime
from enum import Enum
from types import ModuleType

from ninja import Schema
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sbomify.apps.core.utils import set_values_if_not_empty

from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16
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
    v1_5 = "1.5"
    v1_6 = "1.6"


def get_cyclonedx_module(spec_version: CycloneDXSupportedVersion) -> ModuleType:
    module_map: dict[CycloneDXSupportedVersion, ModuleType] = {
        CycloneDXSupportedVersion.v1_5: cdx15,
        CycloneDXSupportedVersion.v1_6: cdx16,
    }
    return module_map[spec_version]


class BaseLicenseSchema(BaseModel):
    pass


class CustomLicenseSchema(BaseLicenseSchema):
    name: str
    url: str | None = None
    text: str | None = None

    def to_cyclonedx(self, spec_version: CycloneDXSupportedVersion) -> cdx15.License2 | cdx16.License2:
        CycloneDx = get_cyclonedx_module(spec_version)
        result: cdx15.License | cdx16.License = CycloneDx.License2(name=self.name)
        set_values_if_not_empty(result, url=self.url)

        if spec_version == CycloneDXSupportedVersion.v1_6:
            if hasattr(cdx16, "LicenseAcknowledgementEnumeration"):
                result.acknowledgement = cdx16.LicenseAcknowledgementEnumeration.declared

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


class ComponentAuthorSchema(BaseModel):
    """Schema for component author information."""

    model_config = ConfigDict(extra="ignore")
    name: str
    email: str | None = None
    phone: str | None = None
    bom_ref: str | None = None


class SupplierSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    url: list[str] | None = None
    address: str | None = None
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

    def to_cyclonedx(self, spec_version: CycloneDXSupportedVersion) -> cdx15.Metadata | cdx16.Metadata:
        CycloneDx = get_cyclonedx_module(spec_version)
        result: cdx15.Metadata | cdx16.Metadata = CycloneDx.Metadata()

        if self.supplier and (
            self.supplier.name or self.supplier.url or self.supplier.address or self.supplier.contacts
        ):
            result.supplier = CycloneDx.OrganizationalEntity()
            set_values_if_not_empty(result.supplier, name=self.supplier.name)

            if spec_version == CycloneDXSupportedVersion.v1_6 and self.supplier.address:
                result.supplier.address = cdx16.PostalAddress(streetAddress=self.supplier.address)

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
