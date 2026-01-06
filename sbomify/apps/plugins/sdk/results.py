"""Result dataclasses for the assessment plugin SDK.

This module defines the data structures for plugin metadata and assessment results.
All plugins return normalized AssessmentResult objects with Finding entries.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from .enums import AssessmentCategory


@dataclass
class PluginMetadata:
    """Metadata about a plugin for tracking and reproducibility.

    The framework uses this to populate AssessmentResult fields and
    denormalize into AssessmentRun for efficient querying.

    Attributes:
        name: Plugin identifier (e.g., "ntia-minimum-elements", "osv", "checksum").
        version: Semantic version of the plugin (e.g., "1.0.0").
        category: Assessment category for classification and behavior.
    """

    name: str
    version: str
    category: AssessmentCategory

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary for serialization.

        Returns:
            Dictionary representation with category as string value.
        """
        return {
            "name": self.name,
            "version": self.version,
            "category": self.category.value,
        }


@dataclass
class Finding:
    """A single finding from an assessment.

    Findings represent individual results from an assessment, such as a
    compliance check result, a vulnerability, or a license issue.

    Attributes:
        id: Stable identifier (e.g., "ntia:supplier-present", "CVE-2024-1234").
        title: Human-readable title.
        description: Detailed description of the finding.
        severity: Severity level for security findings. Defaults to "info".
        status: Compliance status ("pass", "fail", "warning", "error").
            None for security findings.
        component: Component identification dict with name, version, purl, ecosystem.
        cvss_score: Numeric CVSS score for vulnerabilities.
        references: URLs to advisories, patches, etc.
        aliases: Cross-references (CVE-xxx, GHSA-xxx, etc.).
        published_at: ISO-8601 timestamp when vulnerability was published.
        modified_at: ISO-8601 timestamp when vulnerability was last modified.
        analysis_state: VEX analysis state (e.g., "resolved", "exploitable").
        analysis_justification: VEX justification (e.g., "code_not_present").
        analysis_response: VEX response actions (e.g., ["update", "workaround_available"]).
        analysis_detail: Free-text explanation of the analysis.
        remediation: Suggested fix or recommendation.
        evidence_key: S3 key for large evidence payloads.
        metadata: Plugin-specific additional data.
    """

    # Required fields
    id: str
    title: str
    description: str

    # Severity (required for security findings, defaults to "info" for compliance)
    severity: str = "info"

    # Compliance-oriented fields
    status: str | None = None

    # Component identification
    component: dict[str, Any] | None = None

    # Security-oriented fields
    cvss_score: float | None = None
    references: list[str] | None = None
    aliases: list[str] | None = None
    published_at: str | None = None
    modified_at: str | None = None

    # VEX fields
    analysis_state: str | None = None
    analysis_justification: str | None = None
    analysis_response: list[str] | None = None
    analysis_detail: str | None = None

    # Common optional fields
    remediation: str | None = None
    evidence_key: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary for JSON serialization.

        Returns:
            Dictionary with None values excluded for cleaner output.
        """
        result = asdict(self)
        # Remove None values for cleaner JSON output
        return {k: v for k, v in result.items() if v is not None}


@dataclass
class AssessmentSummary:
    """Summary statistics for the assessment.

    Supports both compliance-style (pass/fail counts) and
    security-style (severity counts) summaries.

    Attributes:
        total_findings: Total number of findings in the assessment.
        pass_count: Number of findings with status "pass".
        fail_count: Number of findings with status "fail".
        warning_count: Number of findings with status "warning".
        error_count: Number of findings with status "error".
        by_severity: Severity counts dict (e.g., {"critical": 0, "high": 1}).
    """

    total_findings: int
    pass_count: int = 0
    fail_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    by_severity: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert summary to dictionary for JSON serialization.

        Returns:
            Dictionary with None values excluded for cleaner output.
        """
        result = asdict(self)
        return {k: v for k, v in result.items() if v is not None}


@dataclass
class AssessmentResult:
    """Normalized result from any assessment plugin.

    All plugins return this structure, enabling consistent storage and
    querying regardless of the plugin type.

    Note: plugin_name, plugin_version, and category are copied from PluginMetadata
    by the framework. The AssessmentRun model denormalizes these fields for efficient
    querying without deserializing the JSON result.

    Attributes:
        plugin_name: Name of the plugin that produced this result.
        plugin_version: Version of the plugin.
        category: Assessment category (from PluginMetadata).
        assessed_at: ISO-8601 timestamp when assessment was performed.
        summary: Summary statistics for the assessment.
        findings: List of individual findings.
        schema_version: Version of the result schema. Defaults to "1.0".
        metadata: Plugin-specific metadata.
    """

    plugin_name: str
    plugin_version: str
    category: str
    assessed_at: str
    summary: AssessmentSummary
    findings: list[Finding] = field(default_factory=list)
    schema_version: str = "1.0"
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for JSON serialization.

        Returns:
            Full dictionary representation suitable for storing in JSONField.
        """
        result = {
            "schema_version": self.schema_version,
            "plugin_name": self.plugin_name,
            "plugin_version": self.plugin_version,
            "category": self.category,
            "assessed_at": self.assessed_at,
            "summary": self.summary.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
        }
        if self.metadata is not None:
            result["metadata"] = self.metadata
        return result
