from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

    @model_validator(mode="after")
    def require_version_or_range(self) -> CLEVersionSpecifierSchema:
        if not self.version and not self.range:
            msg = "At least one of 'version' or 'range' must be provided"
            raise ValueError(msg)
        return self


class CLEIdentifierSchema(BaseModel):
    """CLE identifier (e.g., PURL for componentRenamed events)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., max_length=50)
    value: str = Field(..., max_length=2048)


class CLEEventCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: CLE_EVENT_TYPES
    effective: datetime

    @field_validator("effective")
    @classmethod
    def effective_must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            msg = "effective must be timezone-aware (include tzinfo, e.g. 'Z' or '+00:00')"
            raise ValueError(msg)
        return v

    version: str = Field("", max_length=255)
    versions: list[CLEVersionSpecifierSchema] = Field(default_factory=list, max_length=100)
    support_id: str = Field("", max_length=255)
    license: str = Field("", max_length=255)
    superseded_by_version: str = Field("", max_length=255)
    identifiers: list[CLEIdentifierSchema] = Field(default_factory=list, max_length=100)
    withdrawn_event_id: int | None = None
    reason: str = Field("", max_length=5000)
    description: str = Field("", max_length=10000)
    references: list[Annotated[str, Field(max_length=2048)]] = Field(default_factory=list, max_length=100)


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

    support_id: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=5000)
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
