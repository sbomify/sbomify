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
