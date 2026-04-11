"""Enumerations for the assessment plugin SDK.

This module defines the core enumerations used throughout the plugin framework.
"""

from enum import Enum


class AssessmentCategory(str, Enum):
    """Category of assessment plugin.

    These categories help organize plugins by their primary purpose and
    determine default behaviors like re-run triggers.
    """

    SECURITY = "security"
    """Security assessments (e.g., OSV, Dependency-Track vulnerability scanning)."""

    LICENSE = "license"
    """License policy assessments (e.g., allowed/denied license lists)."""

    COMPLIANCE = "compliance"
    """Compliance assessments (e.g., NTIA Minimum Elements, CRA)."""

    ATTESTATION = "attestation"
    """Attestation verification (e.g., Sigstore bundles, in-toto)."""


class RunStatus(str, Enum):
    """Status of an assessment run.

    Tracks the lifecycle of an assessment execution from pending through
    completion or failure.
    """

    PENDING = "pending"
    """Assessment is queued but not yet started."""

    RUNNING = "running"
    """Assessment is currently executing."""

    COMPLETED = "completed"
    """Assessment finished successfully."""

    FAILED = "failed"
    """Assessment encountered an error."""


class ScanMode(str, Enum):
    """Declares whether a plugin completes in a single pass or polls externally.

    One-shot plugins (e.g., NTIA, checksum, OSV) run ``assess()`` once and
    return a final ``AssessmentResult`` immediately.

    Continuous plugins (e.g., Dependency Track, GitHub Attestation) upload
    data or call an external service, then raise ``RetryLaterError`` to poll
    for results over multiple retries. The framework uses this annotation to
    call ``sync_release_tags()`` after M2M population so the plugin can
    reconcile downstream state (e.g., DT project version tags). One-shot
    plugins have no downstream state to reconcile, so the hook is skipped.
    """

    ONE_SHOT = "one_shot"
    """Plugin completes assessment in a single pass — no polling or retries."""

    CONTINUOUS = "continuous"
    """Plugin polls an external system and raises RetryLaterError until done."""


class RunReason(str, Enum):
    """Reason why an assessment run was triggered.

    Used for audit trails and to understand the context of each assessment.
    """

    ON_UPLOAD = "on_upload"
    """Triggered automatically when an SBOM was uploaded."""

    SCHEDULED_REFRESH = "scheduled_refresh"
    """Triggered by a scheduled job (e.g., weekly security scans)."""

    MANUAL = "manual"
    """Triggered manually by a user or API request."""

    CONFIG_CHANGE = "config_change"
    """Triggered because plugin configuration changed."""

    PLUGIN_UPDATE = "plugin_update"
    """Triggered because the plugin version was updated."""

    ON_RELEASE_ASSOCIATION = "on_release_association"
    """Triggered because the SBOM was associated with a release via ReleaseArtifact."""
