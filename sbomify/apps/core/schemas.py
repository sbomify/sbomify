from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from sbomify.apps.teams.schemas import ContactProfileSchema


class ErrorCode(str, Enum):
    """Structured error codes for API responses"""

    # Authentication errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NO_CURRENT_TEAM = "NO_CURRENT_TEAM"

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_NAME = "DUPLICATE_NAME"
    INVALID_DATA = "INVALID_DATA"
    BAD_REQUEST = "BAD_REQUEST"

    # Billing errors
    BILLING_LIMIT_EXCEEDED = "BILLING_LIMIT_EXCEEDED"
    NO_BILLING_PLAN = "NO_BILLING_PLAN"
    INVALID_BILLING_PLAN = "INVALID_BILLING_PLAN"

    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    COMPONENT_NOT_FOUND = "COMPONENT_NOT_FOUND"
    RELEASE_NOT_FOUND = "RELEASE_NOT_FOUND"

    # Permission errors
    TEAM_MISMATCH = "TEAM_MISMATCH"
    RELEASE_MODIFICATION_NOT_ALLOWED = "RELEASE_MODIFICATION_NOT_ALLOWED"
    RELEASE_DELETION_NOT_ALLOWED = "RELEASE_DELETION_NOT_ALLOWED"

    # General errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[ErrorCode] = None

    class Config:
        use_enum_values = True


# Component type choices matching the model
class ComponentType(str, Enum):
    """Available component types."""

    SBOM = "sbom"
    DOCUMENT = "document"


# Product identifier types matching the model
class ProductIdentifierType(str, Enum):
    """Types of product identifiers."""

    GTIN_12 = "gtin_12"
    GTIN_13 = "gtin_13"
    GTIN_14 = "gtin_14"
    GTIN_8 = "gtin_8"
    SKU = "sku"
    MPN = "mpn"
    ASIN = "asin"
    GS1_GPC_BRICK = "gs1_gpc_brick"
    CPE = "cpe"
    PURL = "purl"


class ProductIdentifierSchema(BaseModel):
    """Schema for product identifier responses."""

    id: str
    identifier_type: ProductIdentifierType
    value: str
    created_at: datetime


class ProductIdentifierCreateSchema(BaseModel):
    """Schema for creating a new product identifier."""

    identifier_type: ProductIdentifierType
    value: str = Field(..., max_length=255, min_length=1)


class ProductIdentifierUpdateSchema(BaseModel):
    """Schema for updating a product identifier."""

    identifier_type: ProductIdentifierType
    value: str = Field(..., max_length=255, min_length=1)


class ProductIdentifierBulkUpdateSchema(BaseModel):
    """Schema for bulk updating product identifiers."""

    identifiers: list[ProductIdentifierCreateSchema]


# Product link types matching the model
class ProductLinkType(str, Enum):
    """Types of product links."""

    WEBSITE = "website"
    SUPPORT = "support"
    DOCUMENTATION = "documentation"
    REPOSITORY = "repository"
    CHANGELOG = "changelog"
    RELEASE_NOTES = "release_notes"
    SECURITY = "security"
    ISSUE_TRACKER = "issue_tracker"
    DOWNLOAD = "download"
    CHAT = "chat"
    SOCIAL = "social"
    OTHER = "other"


class ProductLinkSchema(BaseModel):
    """Schema for product link responses."""

    id: str
    link_type: ProductLinkType
    title: str
    url: str
    description: str
    created_at: datetime


class ProductLinkCreateSchema(BaseModel):
    """Schema for creating a new product link."""

    link_type: ProductLinkType
    title: str = Field(..., max_length=255, min_length=1)
    url: str = Field(..., max_length=500, min_length=1)
    description: str = Field(default="", max_length=1000)


class ProductLinkUpdateSchema(BaseModel):
    """Schema for updating a product link."""

    link_type: ProductLinkType
    title: str = Field(..., max_length=255, min_length=1)
    url: str = Field(..., max_length=500, min_length=1)
    description: str = Field(default="", max_length=1000)


class ProductLinkBulkUpdateSchema(BaseModel):
    """Schema for bulk updating product links."""

    links: list[ProductLinkCreateSchema]


# Product/Project/Component schemas moved from sboms
class ProductCreateSchema(BaseModel):
    """Schema for creating a new Product."""

    name: str = Field(..., max_length=255, min_length=1)
    description: str = Field(default="", max_length=1000)


class ProductUpdateSchema(BaseModel):
    """Schema for updating a Product."""

    name: str = Field(..., max_length=255, min_length=1)
    description: str = Field(default="", max_length=1000)
    is_public: bool


class ProductPatchSchema(BaseModel):
    """Schema for partially updating a Product using PATCH."""

    name: str | None = Field(None, max_length=255, min_length=1)
    description: str | None = Field(None, max_length=1000)
    is_public: bool | None = None
    project_ids: list[str] | None = None


class ProductResponseSchema(BaseModel):
    """Schema for Product API responses."""

    id: str
    name: str
    description: str
    team_id: str
    created_at: datetime
    is_public: bool
    project_count: int | None = None
    projects: list["ProjectSummarySchema"] | None = None
    identifiers: list[ProductIdentifierSchema] | None = None
    links: list[ProductLinkSchema] | None = None


class ProjectSummarySchema(BaseModel):
    """Summary schema for projects when included in other responses."""

    id: str
    name: str
    is_public: bool


class ProjectCreateSchema(BaseModel):
    """Schema for creating a new Project."""

    name: str = Field(..., max_length=255, min_length=1)
    metadata: dict = Field(default_factory=dict)


class ProjectUpdateSchema(BaseModel):
    """Schema for updating a Project."""

    name: str = Field(..., max_length=255, min_length=1)
    is_public: bool
    metadata: dict = Field(default_factory=dict)


class ProjectPatchSchema(BaseModel):
    """Schema for partially updating a Project using PATCH."""

    name: str | None = Field(None, max_length=255, min_length=1)
    is_public: bool | None = None
    metadata: dict | None = None
    component_ids: list[str] | None = None


class ProjectResponseSchema(BaseModel):
    """Schema for Project API responses."""

    id: str
    name: str
    team_id: str
    created_at: datetime
    is_public: bool
    metadata: dict
    component_count: int | None = None
    components: list["ComponentSummarySchema"] | None = None


class ComponentSummarySchema(BaseModel):
    """Summary schema for components when included in other responses."""

    id: str
    name: str
    is_public: bool
    is_global: bool
    component_type: ComponentType
    component_type_display: str


class ComponentCreateSchema(BaseModel):
    """Schema for creating a new Component."""

    name: str = Field(..., max_length=255, min_length=1)
    component_type: ComponentType = ComponentType.SBOM
    metadata: dict = Field(default_factory=dict)
    is_global: bool = False


class ComponentUpdateSchema(BaseModel):
    """Schema for updating a Component."""

    name: str = Field(..., max_length=255, min_length=1)
    component_type: ComponentType = ComponentType.SBOM
    is_public: bool
    # is_global defaults to None so existing clients that omit it do not overwrite scope
    is_global: bool
    metadata: dict = Field(default_factory=dict)


class ComponentPatchSchema(BaseModel):
    """Schema for partially updating a Component using PATCH."""

    name: str | None = Field(None, max_length=255, min_length=1)
    component_type: ComponentType | None = None
    is_public: bool | None = None
    is_global: bool | None = None
    metadata: dict | None = None


class ComponentResponseSchema(BaseModel):
    """Schema for Component API responses."""

    id: str
    name: str
    team_id: str
    created_at: datetime
    is_public: bool
    is_global: bool
    component_type: ComponentType
    metadata: dict
    sbom_count: int | None = None


class ProductProjectLinkSchema(BaseModel):
    """Schema for linking/unlinking projects to/from products."""

    project_ids: list[str]


class ProjectComponentLinkSchema(BaseModel):
    """Schema for linking/unlinking components to/from projects."""

    component_ids: list[str]


# Additional schemas for core functionality
class DashboardSBOMUploadInfo(BaseModel):
    component_name: str
    sbom_name: str
    sbom_version: str | None = None
    created_at: datetime


class DashboardStatsResponse(BaseModel):
    total_products: int
    total_projects: int
    total_components: int
    latest_uploads: list[DashboardSBOMUploadInfo]


class UserItemsResponse(BaseModel):
    team_key: str
    team_name: str
    item_key: str
    item_name: str


class ItemTypes(str, Enum):
    """Types of items in the system."""

    component = "component"
    project = "project"
    product = "product"


class PaginationMeta(BaseModel):
    """Pagination metadata for list responses."""

    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_previous: bool = Field(..., description="Whether there is a previous page")
    has_next: bool = Field(..., description="Whether there is a next page")


class PaginatedProductsResponse(BaseModel):
    """Paginated response for products list."""

    items: list[ProductResponseSchema]
    pagination: PaginationMeta


class PaginatedProductIdentifiersResponse(BaseModel):
    """Paginated response for product identifiers list."""

    items: list[ProductIdentifierSchema]
    pagination: PaginationMeta


class PaginatedProductLinksResponse(BaseModel):
    """Paginated response for product links list."""

    items: list[ProductLinkSchema]
    pagination: PaginationMeta


class PaginatedProjectsResponse(BaseModel):
    """Paginated response for projects list."""

    items: list[ProjectResponseSchema]
    pagination: PaginationMeta


class PaginatedComponentsResponse(BaseModel):
    """Paginated response for components list."""

    items: list[ComponentResponseSchema]
    pagination: PaginationMeta


class SBOMWithReleasesSchema(BaseModel):
    """Schema for SBOM with releases information."""

    sbom: dict = Field(..., description="SBOM information")
    has_vulnerabilities_report: bool
    releases: list[ReleaseReferenceSchema]


class PaginatedSBOMsResponse(BaseModel):
    """Paginated response for component SBOMs list."""

    items: list[SBOMWithReleasesSchema]
    pagination: PaginationMeta


class PaginatedReleasesResponse(BaseModel):
    """Paginated response for releases list."""

    items: list[ReleaseResponseSchema]
    pagination: PaginationMeta


class ReleaseArtifactSchema(BaseModel):
    """Schema for release artifact responses."""

    id: str
    artifact_type: str = Field(..., description="Type of artifact: 'sbom' or 'document'")
    artifact_name: str = Field(..., description="Name of the artifact")
    component_id: str
    component_name: str
    created_at: str
    sbom_id: str | None = Field(None, description="ID of the SBOM artifact (only for sbom type)")
    document_id: str | None = Field(None, description="ID of the Document artifact (only for document type)")
    sbom_format: str | None = None
    sbom_format_version: str | None = None
    sbom_version: str | None = None
    document_type: str | None = None
    document_version: str | None = None
    component_slug: str | None = None


class AvailableArtifactSchema(BaseModel):
    """Schema for available artifact responses."""

    id: str
    artifact_type: str = Field(..., description="Type of artifact: 'sbom' or 'document'")
    name: str
    component: dict = Field(..., description="Component information with id and name")
    format: str | None = None
    format_version: str | None = None
    version: str | None = None
    document_type: str | None = None
    created_at: str


class PaginatedReleaseArtifactsResponse(BaseModel):
    """Paginated response for release artifacts list."""

    items: list[ReleaseArtifactSchema | AvailableArtifactSchema]
    pagination: PaginationMeta


class ReleaseReferenceSchema(BaseModel):
    """Schema for release references in document/SBOM responses."""

    id: str
    name: str
    description: str | None = None
    is_prerelease: bool
    is_latest: bool
    product_id: str
    product_name: str
    is_public: bool


class PaginatedDocumentReleasesResponse(BaseModel):
    """Paginated response for document releases list."""

    items: list[ReleaseReferenceSchema]
    pagination: PaginationMeta


class PaginatedSBOMReleasesResponse(BaseModel):
    """Paginated response for SBOM releases list."""

    items: list[ReleaseReferenceSchema]
    pagination: PaginationMeta


class DocumentWithReleasesSchema(BaseModel):
    """Schema for document with releases information."""

    document: dict = Field(..., description="Document information")
    releases: list[ReleaseReferenceSchema]


class PaginatedDocumentsResponse(BaseModel):
    """Paginated response for component documents list."""

    items: list[DocumentWithReleasesSchema]
    pagination: PaginationMeta


class CopyComponentMetadataRequest(BaseModel):
    """Schema for copying metadata from one component to another."""

    source_component_id: str
    target_component_id: str


class ContactInfo(BaseModel):
    """Basic contact information schema."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None


class SupplierInfo(BaseModel):
    """Supplier information schema."""

    name: str | None = None
    url: list[str] | None = None
    address: str | None = None
    contacts: list[ContactInfo] = Field(default_factory=list)


class ComponentMetadataCore(BaseModel):
    """Core component metadata schema without SBOM-specific dependencies."""

    id: str
    name: str
    supplier: SupplierInfo = Field(default_factory=SupplierInfo)
    manufacturer: SupplierInfo = Field(default_factory=SupplierInfo)
    authors: list[ContactInfo] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    lifecycle_phase: str | None = None
    contact_profile_id: str | None = None
    contact_profile: ContactProfileSchema | None = None
    uses_custom_contact: bool = True


class ComponentMetadataUpdateCore(BaseModel):
    """Core schema for updating component metadata."""

    contact_profile_id: str | None = None
    supplier: SupplierInfo | None = None
    authors: list[ContactInfo] | None = None
    licenses: list[str] | None = None
    lifecycle_phase: str | None = None


class ComponentMetadataPatchCore(BaseModel):
    """Core schema for partially updating component metadata using PATCH."""

    contact_profile_id: str | None = None
    supplier: SupplierInfo | None = None
    authors: list[ContactInfo] | None = None
    licenses: list[str] | None = None
    lifecycle_phase: str | None = None


# Release schemas
class ArtifactSBOMSchema(BaseModel):
    """Schema for SBOM artifacts in release responses."""

    id: str
    name: str
    format: str
    format_version: str
    version: str | None
    created_at: datetime
    component: dict  # {"id": str, "name": str}


class ArtifactDocumentSchema(BaseModel):
    """Schema for Document artifacts in release responses."""

    id: str
    name: str
    document_type: str
    version: str | None
    created_at: datetime
    component: dict  # {"id": str, "name": str}


class ReleaseArtifactDetailSchema(BaseModel):
    """Schema for release artifacts in detailed responses."""

    id: str
    sbom: ArtifactSBOMSchema | None = None
    document: ArtifactDocumentSchema | None = None


class ReleaseCreateSchema(BaseModel):
    """Schema for creating a new Release via top-level API endpoint."""

    name: str = Field(..., max_length=255, min_length=1)
    description: str | None = Field(default="", max_length=1000)
    is_prerelease: bool = Field(default=False)
    product_id: str = Field(..., description="ID of the product this release belongs to")
    created_at: datetime | None = None
    released_at: datetime | None = None


class ReleaseUpdateSchema(BaseModel):
    """Schema for updating a Release."""

    name: str = Field(..., max_length=255, min_length=1)
    description: str | None = Field(default="", max_length=1000)
    is_prerelease: bool = Field(default=False)
    created_at: datetime | None = None
    released_at: datetime | None = None


class ReleasePatchSchema(BaseModel):
    """Schema for partially updating a Release using PATCH."""

    name: str | None = Field(None, max_length=255, min_length=1)
    description: str | None = None
    is_prerelease: bool | None = None
    created_at: datetime | None = None
    released_at: datetime | None = None


class ReleaseResponseSchema(BaseModel):
    """Schema for Release API responses."""

    id: str
    name: str
    description: str
    product_id: str
    product_name: str
    is_latest: bool
    is_prerelease: bool
    is_public: bool
    created_at: datetime
    released_at: datetime | None = None
    artifact_count: int | None = None
    artifacts: list[ReleaseArtifactDetailSchema] | None = None


class ReleaseArtifactCreateSchema(BaseModel):
    """Schema for adding artifacts to a release."""

    sbom_id: str | None = None
    document_id: str | None = None

    def __init__(self, **data):
        super().__init__(**data)
        # Validate that exactly one of sbom_id or document_id is provided
        if not self.sbom_id and not self.document_id:
            raise ValueError("Either sbom_id or document_id must be provided")
        if self.sbom_id and self.document_id:
            raise ValueError("Cannot provide both sbom_id and document_id")


class ReleaseArtifactsUpdateSchema(BaseModel):
    """Schema for bulk updating artifacts in a release."""

    artifacts: list[ReleaseArtifactCreateSchema]


class SBOMReleaseTaggingSchema(BaseModel):
    """Schema for tagging SBOMs to releases."""

    release_ids: list[str] = Field(..., min_length=1, description="List of release IDs to tag the SBOM to")


class SBOMReleaseTaggingArtifactSchema(BaseModel):
    """Schema for individual artifacts in SBOM tagging response."""

    artifact_id: str
    release_id: str
    release_name: str
    product_id: str
    product_name: str
    created_at: datetime
    replaced_sbom: str | None = None  # Only present if this was a replacement


class SBOMReleaseTaggingResponseSchema(BaseModel):
    """Schema for SBOM tagging operation response."""

    created_artifacts: list[SBOMReleaseTaggingArtifactSchema]
    replaced_artifacts: list[SBOMReleaseTaggingArtifactSchema]
    errors: list[str]


class DocumentReleaseTaggingSchema(BaseModel):
    """Schema for tagging documents to releases."""

    release_ids: list[str] = Field(..., min_length=1, description="List of release IDs to tag the document to")


class DocumentReleaseTaggingArtifactSchema(BaseModel):
    """Schema for individual artifacts in document tagging response."""

    artifact_id: str
    release_id: str
    release_name: str
    product_id: str
    product_name: str
    created_at: datetime
    replaced_document: str | None = None  # Only present if this was a replacement


class DocumentReleaseTaggingResponseSchema(BaseModel):
    """Schema for document tagging operation response."""

    created_artifacts: list[DocumentReleaseTaggingArtifactSchema]
    replaced_artifacts: list[DocumentReleaseTaggingArtifactSchema]
    errors: list[str]


class ReleaseArtifactAddResponseSchema(BaseModel):
    """Schema for the response when adding an artifact to a release."""

    id: str
    artifact_type: str  # "sbom" or "document"
    artifact_name: str
    component_id: str
    component_name: str
    created_at: str
    sbom_format: str | None = None
    sbom_version: str | None = None
    document_type: str | None = None
    document_version: str | None = None
    component_slug: str | None = None
