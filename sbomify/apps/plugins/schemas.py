"""Pydantic schemas for the plugins API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FindingSchema(BaseModel):
    """Schema for a single assessment finding."""

    id: str
    title: str
    description: str
    status: str | None = None  # pass, fail, warning, info, error (None for security findings)
    severity: str | None = None
    cvss_score: float | None = None
    component: dict[str, Any] | None = None
    references: list[str] | None = None
    aliases: list[str] | None = None
    remediation: str | None = None
    metadata: dict[str, Any] | None = None


class AssessmentSummarySchema(BaseModel):
    """Schema for assessment summary statistics."""

    total_findings: int = 0
    pass_count: int = 0
    fail_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    error_count: int = 0
    by_severity: dict[str, int] | None = None


class AssessmentResultSchema(BaseModel):
    """Schema for the full assessment result."""

    plugin_name: str
    plugin_version: str
    category: str
    assessed_at: str
    summary: AssessmentSummarySchema
    findings: list[FindingSchema]
    metadata: dict[str, Any] | None = None


class AssessmentRunSchema(BaseModel):
    """Schema for an assessment run record."""

    id: str
    sbom_id: str
    plugin_name: str
    plugin_version: str
    plugin_display_name: str | None = None
    category: str
    run_reason: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result: AssessmentResultSchema | None = None
    created_at: datetime

    class Config:
        """Pydantic config."""

        from_attributes = True


class AssessmentStatusSummary(BaseModel):
    """Summary status across all assessments for an SBOM."""

    overall_status: str = Field(
        description="Overall status: all_pass, has_failures, pending, in_progress, no_assessments, no_plugins_enabled"
    )
    total_assessments: int = 0
    passing_count: int = 0
    failing_count: int = 0
    pending_count: int = 0
    in_progress_count: int = 0


class SBOMAssessmentsResponse(BaseModel):
    """Response schema for SBOM assessments endpoint."""

    sbom_id: str
    status_summary: AssessmentStatusSummary
    latest_runs: list[AssessmentRunSchema] = Field(description="Latest run for each plugin")
    all_runs: list[AssessmentRunSchema] = Field(description="All assessment runs, ordered by date")


class AssessmentBadgeData(BaseModel):
    """Minimal data needed for the assessment badge display."""

    sbom_id: str
    overall_status: str
    total_assessments: int
    passing_count: int
    failing_count: int
    pending_count: int
    plugins: list[dict[str, Any]] = Field(description="Summary per plugin: name, display_name, status, findings_count")
