from __future__ import annotations

from datetime import datetime
from typing import Literal

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

    status: Literal["compliant", "partial", "not_implemented", "not_applicable"]
    product_id: str | None = None
    notes: str = ""


class BulkStatusUpdateItemSchema(BaseModel):
    """Schema for a single item in a bulk status update."""

    control_id: str
    status: Literal["compliant", "partial", "not_implemented", "not_applicable"]
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


class ControlMappingSchema(BaseModel):
    """Schema for ControlMapping API responses."""

    id: str
    source_control_id: str
    source_control_label: str
    source_catalog_name: str
    target_control_id: str
    target_control_label: str
    target_catalog_name: str
    relation_type: str
    notes: str = ""
    created_at: datetime


class CreateMappingSchema(BaseModel):
    """Schema for creating a control mapping."""

    source_control_id: str
    target_control_id: str
    relation_type: Literal["equivalent", "subset", "superset", "related"]
    notes: str = ""


class BulkMappingItemSchema(BaseModel):
    """Schema for a single item in a bulk mapping import."""

    source_control_id: str
    target_control_id: str
    relation_type: str
    notes: str = ""


class BulkMappingSchema(BaseModel):
    """Schema for bulk importing control mappings."""

    items: list[BulkMappingItemSchema] = Field(..., max_length=500)


class ControlEvidenceSchema(BaseModel):
    """Schema for ControlEvidence API responses."""

    id: str
    evidence_type: str
    title: str
    url: str = ""
    document_id: str = ""
    description: str = ""
    created_at: datetime


class CreateEvidenceSchema(BaseModel):
    """Schema for creating evidence on a control."""

    evidence_type: Literal["url", "document", "note"]
    title: str
    url: str = ""
    document_id: str = ""
    description: str = ""


class AutomationSyncResultSchema(BaseModel):
    """Schema for the automation sync endpoint response."""

    total_updated: int
    by_plugin: dict[str, int]


class AutomationMappingSchema(BaseModel):
    """Schema for the automation mappings endpoint response."""

    mappings: dict[str, list[str]]
