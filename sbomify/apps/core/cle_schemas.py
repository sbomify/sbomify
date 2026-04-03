from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CLE_EVENT_TYPES = Literal[
    "released",
    "endOfDevelopment",
    "endOfSupport",
    "endOfLife",
    "endOfDistribution",
    "endOfMarketing",
    "supersededBy",
    "componentRenamed",
    "withdrawn",
]


class CLEVersionSpecifierSchema(BaseModel):
    """ECMA-428 version specifier (version or range, at least one required)."""

    model_config = ConfigDict(extra="forbid")

    version: str | None = Field(None, max_length=255)
    range: str | None = Field(None, max_length=512)


class CLEIdentifierSchema(BaseModel):
    """CLE identifier (e.g., PURL for componentRenamed events)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., max_length=50)
    value: str = Field(..., max_length=2048)


class CLEEventCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: CLE_EVENT_TYPES
    effective: datetime
    version: str = Field("", max_length=255)
    versions: list[CLEVersionSpecifierSchema] = Field(default=[], max_length=100)
    support_id: str = Field("", max_length=255)
    license: str = Field("", max_length=255)
    superseded_by_version: str = Field("", max_length=255)
    identifiers: list[CLEIdentifierSchema] = Field(default=[], max_length=100)
    withdrawn_event_id: int | None = None
    reason: str = Field("", max_length=5000)
    description: str = Field("", max_length=10000)
    references: list[Annotated[str, Field(max_length=2048)]] = Field(default=[], max_length=100)


class CLEEventResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    event_type: str
    effective: datetime
    published: datetime
    version: str
    versions: list[CLEVersionSpecifierSchema]
    support_id: str
    license: str
    superseded_by_version: str
    identifiers: list[CLEIdentifierSchema]
    withdrawn_event_id: int | None
    reason: str
    description: str
    references: list[str]


class CLESupportDefinitionCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support_id: str = Field(..., max_length=255)
    description: str = Field(..., max_length=5000)
    url: str = Field("", max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if v and not v.startswith(("http://", "https://")):
            msg = "URL must start with http:// or https://"
            raise ValueError(msg)
        return v


class CLESupportDefinitionResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    support_id: str
    description: str
    url: str


# --- Full CLE Document Schema (ECMA-428 top-level) ---

CLE_SCHEMA_URI = "https://ecma-tc54.github.io/ECMA-428/cle.v1.0.0.json"


class CLEDocumentSchema(BaseModel):
    """Full ECMA-428 CLE document with $schema and updatedAt."""

    schema_uri: str = Field(CLE_SCHEMA_URI, alias="$schema")
    identifier: str | list[str]
    updated_at: datetime = Field(..., alias="updatedAt")
    definitions: dict[str, list[CLESupportDefinitionResponseSchema]] | None = None
    events: list[CLEEventResponseSchema]

    model_config = ConfigDict(populate_by_name=True)
