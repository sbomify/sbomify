from __future__ import annotations

from datetime import datetime
from enum import Enum
from types import ModuleType

from ninja import Schema
from pydantic import BaseModel, ConfigDict, Field

from core.utils import set_values_if_not_empty

from .sbom_format_schemas import cyclonedx_1_5 as cdx15
from .sbom_format_schemas import cyclonedx_1_6 as cdx16


class PublicStatusSchema(Schema):
    is_public: bool


class SBOMUploadRequest(Schema):
    id: str


class ComponentUploadInfo(Schema):
    component_id: str | None = None
    component_name: str | None = None
    sbom_id: str | None = None
    sbom_name: str | None = None
    sbom_version: str | None = None
    sbom_created_at: datetime | None = None


class StatsResponse(Schema):
    total_products: int | None = None
    total_projects: int | None = None
    total_components: int | None = None
    license_count: dict[str, int] | None = None
    component_uploads: list[ComponentUploadInfo] | None = None


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
    # name="acme", acknowledgement="declared", text={"content": "Screenly license"}, url="http://screenly.com
    # ...: /license.html"

    def to_cyclonedx(self, spec_version: CycloneDXSupportedVersion) -> cdx15.License2 | cdx16.License2:
        CycloneDx = get_cyclonedx_module(spec_version)

        result: cdx15.License | cdx16.License = CycloneDx.License2(name=self.name)
        set_values_if_not_empty(result, url=self.url)

        if spec_version == CycloneDXSupportedVersion.v1_6:
            result.acknowledgement = cdx16.LicenseAcknowledgementEnumeration.declared

        if self.text:
            result.text = CycloneDx.Attachment(content=self.text)

        return result


class DBSBOMLicense(BaseModel):
    id: str | None = None
    name: str | None = None
    url: str | None = None
    text: str | None = None


class SupplierSchema(BaseModel):
    name: str | None = None
    url: str | None = None
    address: str | None = None
    contacts: list[cdx15.OrganizationalContact | cdx16.OrganizationalContact] = []


class ComponentMetaData(BaseModel):
    """
    Metadata for a component.

    Extra information stored with the component. Used for sbom augmentation.
    """

    model_config = ConfigDict(extra="ignore")

    supplier: SupplierSchema = SupplierSchema()
    authors: list[cdx15.OrganizationalContact | cdx16.OrganizationalContact] = []
    license_expression: str | None = None
    lifecycle_phase: cdx15.Phase | cdx16.Phase | None = None

    # TODO: The 'license' field is temporary and will be removed in the future.
    # It will be replaced by license expressions in the next API version and generated
    # ad-hoc from the view for backward compatibility.

    def to_cyclonedx(self, spec_version: CycloneDXSupportedVersion) -> cdx15.Metadata | cdx16.Metadata:
        CycloneDx = get_cyclonedx_module(spec_version)

        result: cdx15.CycloneDX16Metadata | cdx16.CycloneDX15Metadata = CycloneDx.Metadata()

        if self.supplier:
            result.supplier = CycloneDx.OrganizationalEntity()
            set_values_if_not_empty(result.supplier, name=self.supplier.name)

            # CycloneDX 1.5 does not have address field.
            if spec_version == CycloneDXSupportedVersion.v1_6 and self.supplier.address:
                result.supplier.address = cdx16.PostalAddress(streetAddress=self.supplier.address)

            # Special handling for URL field convert str to list.
            if self.supplier.url:
                result.supplier.url = [self.supplier.url]

            if self.supplier.contacts:
                result.supplier.contact = []
                for contact in self.supplier.contacts:
                    c = CycloneDx.OrganizationalContact()
                    set_values_if_not_empty(c, name=contact.name, email=contact.email, phone=contact.phone)
                    result.supplier.contact.append(c)

        if self.authors:
            result.authors = []
            for author in self.authors:
                c = CycloneDx.OrganizationalContact()
                set_values_if_not_empty(c, name=author.name, email=author.email, phone=author.phone)
                result.authors.append(c)

        # Use the single license_expression string if present
        if self.license_expression:
            licenses = [{"license": {"id": self.license_expression}}]
            result.licenses = CycloneDx.LicenseChoice(licenses)

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
    packages: list[SPDXPackage] = []
