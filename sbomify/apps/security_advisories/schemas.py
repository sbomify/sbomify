"""Wire shapes for the advisories API.

Deliberately a subset of what the service projections carry. Those are built
for the pages and include presentation (a badge variant, an icon name, a
pre-formatted date), and none of that belongs in a contract a client writes
against. The names here follow the model rather than the templates, so
``status`` is the publication state the model calls ``status`` and the fix's
progress is ``remediation_status``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import Field


class AdvisoryProductSchema(Schema):
    """A product an advisory names.

    ``id`` is null when the advisory names a product this workspace does not
    track, or tracked and has since deleted; the name is kept either way.
    """

    id: str | None = None
    name: str
    affected_ranges: list[str] = []


class AdvisoryVulnerabilitySchema(Schema):
    id: str
    cve_id: str = ""
    title: str = ""
    description: str = ""
    severity: str = ""
    cwe_ids: list[str] = []
    cvss_scores: list[dict[str, Any]] = []
    exploitation_status: str = ""
    recommendation: str = ""


class AdvisoryReferenceSchema(Schema):
    id: str
    type: str = ""
    external_id: str = ""
    url: str = ""
    summary: str = ""
    category: str = ""


class AdvisoryEventSchema(Schema):
    """One entry in the advisory's append-only history."""

    id: str
    kind: str
    body: str = ""
    actor: str = ""
    from_status: str | None = None
    to_status: str | None = None
    created_at: datetime


class AdvisorySchema(Schema):
    id: str
    tracking_id: str = Field(description="The workspace's own identifier, allocated at publication.")
    title: str
    summary: str = ""
    description: str = ""
    advisory_type: str
    severity: str = ""
    cvss_score: float | None = None
    cvss_vector: str = ""
    status: str = Field(description="Publication state: draft, published or withdrawn.")
    remediation_status: str = Field(description="Where the fix is, which is not whether it is published.")
    is_open: bool
    visibility: str
    vulnerability_count: int = 0
    vulnerability_id: str = Field("", description="The first CVE the advisory cites, when it cites one.")
    products: list[AdvisoryProductSchema] = []
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class AdvisoryDetailSchema(AdvisorySchema):
    vulnerabilities: list[AdvisoryVulnerabilitySchema] = []
    references: list[AdvisoryReferenceSchema] = []
    timeline: list[AdvisoryEventSchema] = []


class CreateAdvisorySchema(Schema):
    title: str = Field(min_length=1, max_length=255)
    severity: str = ""
    description: str = ""
    identifier: str = Field("", description="A CVE or other identifier the advisory is about.")
    remediation_status: str = ""
    cvss_score: float | None = None
    cvss_vector: str = ""
    product_ids: list[str] = []


class UpdateAdvisorySchema(Schema):
    title: str = Field(min_length=1, max_length=255)
    severity: str | None = None
    description: str = ""
    cvss_score: float | None = None
    cvss_vector: str | None = None


class PublishAdvisorySchema(Schema):
    """Publication moves both axes at once: a draft nobody can read becomes a
    published advisory with the visibility asked for here."""

    visibility: str = Field(description="The visibility to disclose at.")
