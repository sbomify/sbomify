"""Pydantic schemas for the plugins API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("aliases", mode="before")
    @classmethod
    def flatten_alias_dicts(cls, v: Any) -> list[str] | None:
        """DT stores aliases as [{"cveId": "...", "ghsaId": "..."}] dicts.

        Flatten to list[str] so existing stored results don't crash Pydantic.
        """
        if not v:
            return None
        if not isinstance(v, list):
            return [str(v)] if isinstance(v, str) else None
        flat: list[str] = []
        for item in v:
            if isinstance(item, dict):
                flat.extend(str(val) for val in item.values() if val)
            elif isinstance(item, str):
                flat.append(item)
        return flat if flat else None


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
    release_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Release IDs whose SBOM this run's result covers. Under the scan-once-per-SBOM "
            "model (sbomify/sbomify#881), one run covers all releases currently linked to "
            "the SBOM via ReleaseArtifact at scan completion. Empty list for SBOM-level "
            "runs (e.g. NTIA on a component not yet tied to a product). Populated from "
            "the AssessmentRun.releases M2M."
        ),
    )
    release_names: list[str] = Field(
        default_factory=list,
        description="Human-readable release names corresponding to release_ids (for template rendering).",
    )
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
    skipped_count: int = Field(
        default=0,
        description=(
            "Count of runs that completed but were skipped (e.g., Dependency Track "
            "when the SBOM had no release association). Skipped runs are NOT counted "
            "in passing_count so they don't inflate 'clean scan' metrics."
        ),
    )


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
    skipped_count: int = 0
    plugins: list[dict[str, Any]] = Field(description="Summary per plugin: name, display_name, status, findings_count")
