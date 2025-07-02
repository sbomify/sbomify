from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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

    # Billing errors
    BILLING_LIMIT_EXCEEDED = "BILLING_LIMIT_EXCEEDED"
    NO_BILLING_PLAN = "NO_BILLING_PLAN"
    INVALID_BILLING_PLAN = "INVALID_BILLING_PLAN"

    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"

    # General errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[ErrorCode] = None

    class Config:
        use_enum_values = True


# Product/Project/Component schemas moved from sboms
class ProductCreateSchema(BaseModel):
    """Schema for creating a new Product."""

    name: str = Field(..., max_length=255, min_length=1)


class ProductUpdateSchema(BaseModel):
    """Schema for updating a Product."""

    name: str = Field(..., max_length=255, min_length=1)
    is_public: bool = False


class ProductPatchSchema(BaseModel):
    """Schema for partially updating a Product using PATCH."""

    name: str | None = Field(None, max_length=255, min_length=1)
    is_public: bool | None = None
    project_ids: list[str] | None = None


class ProductResponseSchema(BaseModel):
    """Schema for Product API responses."""

    id: str
    name: str
    team_id: str
    created_at: datetime
    is_public: bool
    project_count: int | None = None
    projects: list["ProjectSummarySchema"] | None = None


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
    is_public: bool = False
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


class ComponentCreateSchema(BaseModel):
    """Schema for creating a new Component."""

    name: str = Field(..., max_length=255, min_length=1)
    metadata: dict = Field(default_factory=dict)


class ComponentUpdateSchema(BaseModel):
    """Schema for updating a Component."""

    name: str = Field(..., max_length=255, min_length=1)
    is_public: bool = False
    metadata: dict = Field(default_factory=dict)


class ComponentPatchSchema(BaseModel):
    """Schema for partially updating a Component using PATCH."""

    name: str | None = Field(None, max_length=255, min_length=1)
    is_public: bool | None = None
    metadata: dict | None = None


class ComponentResponseSchema(BaseModel):
    """Schema for Component API responses."""

    id: str
    name: str
    team_id: str
    created_at: datetime
    is_public: bool
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
    authors: list[ContactInfo] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    lifecycle_phase: str | None = None


class ComponentMetadataUpdateCore(BaseModel):
    """Core schema for updating component metadata."""

    supplier: SupplierInfo | None = None
    authors: list[ContactInfo] | None = None
    licenses: list[str] | None = None
    lifecycle_phase: str | None = None


class ComponentMetadataPatchCore(BaseModel):
    """Core schema for partially updating component metadata using PATCH."""

    supplier: SupplierInfo | None = None
    authors: list[ContactInfo] | None = None
    licenses: list[str] | None = None
    lifecycle_phase: str | None = None
