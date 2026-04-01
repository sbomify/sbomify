"""Request/response schemas for the CRA Compliance API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ninja import Schema


class CRAAssessmentSchema(Schema):
    id: str
    product_id: str
    product_name: str
    status: Literal["draft", "in_progress", "complete"]
    current_step: int
    completed_steps: list[int]
    product_category: str
    is_open_source_steward: bool
    conformity_assessment_procedure: str | None
    created_at: datetime
    updated_at: datetime


class FindingSchema(Schema):
    id: str
    control_id: str
    control_title: str
    group_id: str
    group_title: str
    status: Literal["satisfied", "not-satisfied", "not-applicable", "unanswered"]
    notes: str
    justification: str
    is_mandatory: bool
    annex_part: str
    annex_reference: str
    annex_url: str
    updated_at: datetime


class FindingUpdateSchema(Schema):
    status: Literal["satisfied", "not-satisfied", "not-applicable"]
    notes: str = ""
    justification: str = ""


class ObservationCreateSchema(Schema):
    description: str
    method: Literal["EXAMINE", "INTERVIEW", "TEST"]
    evidence_document_id: str | None = None


class ObservationSchema(Schema):
    id: str
    description: str
    method: str
    evidence_document_id: str | None
    collected_at: datetime


class DocumentSchema(Schema):
    id: str
    document_kind: str
    version: int
    is_stale: bool
    content_hash: str
    generated_at: datetime


class ExportPackageSchema(Schema):
    id: str
    content_hash: str
    manifest: dict[str, Any]
    created_at: datetime


class SBOMStatusSchema(Schema):
    components: list[dict[str, Any]]
    summary: dict[str, Any]


class StalenessSchema(Schema):
    stale_documents: list[str]
    stale_steps: list[int]
    has_new_sbom: bool


class StepDataSchema(Schema):
    """Flexible schema — fields vary by step."""

    data: dict[str, Any]


class StepContextSchema(Schema):
    """Step context — shape varies by step number."""

    step: int
    data: dict[str, Any]
    is_complete: bool
    validation_errors: list[str] = []


class ErrorResponse(Schema):
    error: str
    error_code: str = "error"
