from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# Summary schemas for use in relationships
class ProductSummarySchema(BaseModel):
    """Summary schema for products when included in other responses."""

    id: str
    name: str
    is_public: bool


class ProjectSummarySchema(BaseModel):
    """Summary schema for projects when included in other responses."""

    id: str
    name: str
    is_public: bool


class ComponentSummarySchema(BaseModel):
    """Summary schema for components when included in other responses."""

    id: str
    name: str
    is_public: bool


# Product CRUD schemas
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


class ProductResponseSchema(BaseModel):
    """Schema for Product API responses."""

    id: str
    name: str
    team_id: str
    created_at: datetime
    is_public: bool
    project_count: int | None = None
    projects: list[ProjectSummarySchema] | None = None


# Project CRUD schemas
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


class ProjectResponseSchema(BaseModel):
    """Schema for Project API responses."""

    id: str
    name: str
    team_id: str
    created_at: datetime
    is_public: bool
    metadata: dict
    component_count: int | None = None
    components: list[ComponentSummarySchema] | None = None


# Component CRUD schemas
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


# Relationship linking schemas
class ProductProjectLinkSchema(BaseModel):
    """Schema for linking/unlinking projects to/from products."""

    project_ids: list[str]


class ProjectComponentLinkSchema(BaseModel):
    """Schema for linking/unlinking components to/from projects."""

    component_ids: list[str]
