from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CLEVersionSpecifierSchema(BaseModel):
    """ECMA-428 version specifier (version or range, at least one required)."""

    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    range: str | None = None


class CLEIdentifierSchema(BaseModel):
    """CLE identifier (e.g., PURL for componentRenamed events)."""

    model_config = ConfigDict(extra="forbid")

    type: str
    value: str


class CLEEventCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    effective: datetime
    version: str = ""
    versions: list[CLEVersionSpecifierSchema] = []
    support_id: str = ""
    license: str = ""
    superseded_by_version: str = ""
    identifiers: list[CLEIdentifierSchema] = []
    withdrawn_event_id: int | None = None
    reason: str = ""
    description: str = ""
    references: list[str] = []


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

    support_id: str
    description: str
    url: str = ""


class CLESupportDefinitionResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    support_id: str
    description: str
    url: str
