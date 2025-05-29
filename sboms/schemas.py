from __future__ import annotations

from datetime import datetime
from enum import Enum
from types import ModuleType

from ninja import Schema
from pydantic import BaseModel, ConfigDict, Field

from core.utils import set_values_if_not_empty

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


class ItemTypes(str, Enum):
    component = "component"
    project = "project"
    product = "product"


class UserItemsResponse(BaseModel):
    team_key: str
    team_name: str
    item_key: str
    item_name: str


class CopyComponentMetadataRequest(BaseModel):
    source_component_id: str
    target_component_id: str


class CycloneDXSupportedVersion(str, Enum):
    v1_5 = "1.5"
    v1_6 = "1.6"


def get_cyclonedx_module(spec_version: CycloneDXSupportedVersion) -> ModuleType:
    module_map: dict[CycloneDXSupportedVersion, ModuleType] = {
        CycloneDXSupportedVersion.v1_5: cdx15,
        CycloneDXSupportedVersion.v1_6: cdx16,
    }
    return module_map[spec_version]


class CustomLicenseSchema(BaseModel):
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


class SupplierSchema(BaseModel):
    name: str | None = None
    url: str | None = None
    address: str | None = None
    contacts: list[cdx15.OrganizationalContact | cdx16.OrganizationalContact] = Field(default_factory=list)


class ComponentMetaData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    supplier: SupplierSchema = Field(default_factory=SupplierSchema)
    authors: list[cdx15.OrganizationalContact | cdx16.OrganizationalContact] = Field(default_factory=list)
    licenses: list[LicenseSchema | CustomLicenseSchema] = Field(default_factory=list)
    lifecycle_phase: cdx15.Phase | cdx16.Phase | None = None

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
                result.supplier.url = [self.supplier.url]

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
                    try:
                        # Primarily expect SPDX IDs from LicenseSchema
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
