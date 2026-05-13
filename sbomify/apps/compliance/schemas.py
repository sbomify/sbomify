"""Request/response schemas for the CRA Compliance API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ninja import Schema


class CRAAssessmentSchema(Schema):
    id: str
    product_id: str
    product_name: str
    # ``stale`` is a valid read-side value (issue #921) — the schema must
    # admit it so ``GET /cra/{id}`` on a stale assessment serialises
    # without tripping Pydantic validation and 500-ing the response.
    status: Literal["draft", "in_progress", "complete", "stale"]
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
    # ``unanswered`` is allowed so the Alpine Step 3 UI can save notes
    # on a finding before the operator picks a terminal status. Without
    # it, the debounced ``persistFinding`` PUT 422s on any finding
    # whose status is still ``unanswered`` and notes silently drop.
    status: Literal["satisfied", "not-satisfied", "not-applicable", "unanswered"]
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


class SignatureSchema(Schema):
    """Manufacturer signature block for the Declaration of Conformity.

    ``signature_image`` is a ``data:image/png;base64,...`` URL produced by
    the front-end signature pad. Field-level size and format checks live
    on the API side (see ``save_doc_signature``); the schema simply types
    the wire payload.
    """

    place: str
    name: str
    function: str
    image: str


class SignatureResponseSchema(Schema):
    """Read-side view of the signature block."""

    place: str
    name: str
    function: str
    image: str
    signed_at: str | None = None
    is_signed: bool
