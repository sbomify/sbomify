from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CatalogSchema(BaseModel):
    """Schema for ControlCatalog API responses."""

    id: str
    name: str
    version: str
    source: str
    is_active: bool
    created_at: datetime


class CatalogDetailSchema(CatalogSchema):
    """Schema for ControlCatalog detail with controls count."""

    controls_count: int


class ControlSchema(BaseModel):
    """Schema for Control API responses."""

    id: str
    control_id: str
    group: str
    title: str
    description: str


class ControlWithStatusSchema(ControlSchema):
    """Schema for Control with its status information."""

    status: str = "not_implemented"
    notes: str = ""
    updated_at: datetime | None = None


class StatusUpdateSchema(BaseModel):
    """Schema for updating a single control status."""

    status: str
    product_id: str | None = None
    notes: str = ""


class BulkStatusUpdateItemSchema(BaseModel):
    """Schema for a single item in a bulk status update."""

    control_id: str
    status: str
    product_id: str | None = None
    notes: str = ""


class BulkStatusUpdateSchema(BaseModel):
    """Schema for bulk updating control statuses."""

    items: list[BulkStatusUpdateItemSchema] = Field(..., max_length=500)


class BulkResultSchema(BaseModel):
    """Schema for bulk update result."""

    updated: int


class ControlStatusSchema(BaseModel):
    """Schema for a ControlStatus response."""

    id: str
    control_id: str
    status: str
    notes: str
    product_id: str | None = None
    updated_at: datetime


class PublicControlItemSchema(BaseModel):
    """Schema for a single control in the public summary."""

    control_id: str
    title: str
    status: str


class CategorySummarySchema(BaseModel):
    """Schema for category-level compliance summary."""

    name: str
    total: int
    addressed: float
    percentage: float
    icon: str
    controls: list[PublicControlItemSchema] = Field(default_factory=list)


class PublicControlsSummarySchema(BaseModel):
    """Schema for public controls compliance summary."""

    catalog_name: str
    catalog_version: str = ""
    total: int
    addressed: float
    percentage: float
    by_status: dict[str, int]
    categories: list[CategorySummarySchema]


class ActivateCatalogSchema(BaseModel):
    """Schema for activating a built-in catalog."""

    catalog_name: str = Field(..., description="Name of the built-in catalog to activate (e.g., 'soc2-type2')")


class CatalogPatchSchema(BaseModel):
    """Schema for partially updating a catalog."""

    is_active: bool
