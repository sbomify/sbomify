"""Base class for assessment plugins.

This module defines the abstract base class that all assessment plugins must implement.
Plugins are responsible for analyzing SBOMs and returning normalized results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .results import AssessmentResult, PluginMetadata


class RetryLaterError(Exception):
    """Exception that signals the assessment should be retried later.

    Plugins can raise this exception when a transient condition prevents
    the assessment from completing successfully, but the condition may
    resolve itself over time (e.g., external service processing delays).

    The framework will catch this exception and schedule a retry with
    appropriate backoff delays, rather than marking the assessment as failed.

    Example:
        >>> class MyPlugin(AssessmentPlugin):
        ...     def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        ...         response = external_api.check_status()
        ...         if response.status == "pending":
        ...             raise RetryLaterError("External service still processing")
        ...         ...

    Attributes:
        message: Human-readable description of why retry is needed.
        assessment_run_id: Optional ID of the AssessmentRun (set by orchestrator).
    """

    def __init__(self, message: str = "", assessment_run_id: str | None = None) -> None:
        """Initialize RetryLaterError.

        Args:
            message: Human-readable description of why retry is needed.
            assessment_run_id: Optional ID of the AssessmentRun. This is typically
                set by the orchestrator when re-raising the exception.
        """
        super().__init__(message)
        self.assessment_run_id = assessment_run_id


@dataclass
class SBOMContext:
    """Context information about an SBOM passed to plugins.

    This provides pre-computed metadata from the database to avoid
    redundant calculations. All fields are optional to maintain
    backward compatibility with older SBOMs that may lack some data.

    Attributes:
        sha256_hash: Pre-computed SHA256 hash of the SBOM content (from database).
            Plugins can use this instead of recalculating from the file.
        sbom_format: The SBOM format (e.g., 'cyclonedx', 'spdx').
        format_version: The format version (e.g., '1.6', 'SPDX-2.3').
        sbom_name: The name of the SBOM as stored in the database.
        sbom_version: The version of the SBOM as stored in the database.
        component_id: The ID of the component this SBOM belongs to.
        team_id: The ID of the team that owns the component.
    """

    sha256_hash: str | None = None
    sbom_format: str | None = None
    format_version: str | None = None
    sbom_name: str | None = None
    sbom_version: str | None = None
    component_id: str | None = None
    team_id: int | None = None
    extra: dict = field(default_factory=dict)


class AssessmentPlugin(ABC):
    """Base class for all assessment plugins.

    Plugins implement specific assessment logic (security scanning, compliance
    checking, license validation, etc.) and return normalized results.

    The framework handles:
    - Fetching the SBOM from object storage
    - Writing it to a temporary file
    - Passing the path to the assess() method
    - Providing pre-computed context (sha256_hash, etc.) via SBOMContext
    - Cleaning up the temporary file after assessment

    Plugins receive:
    - sbom_id: The SBOM's primary key for result association
    - sbom_path: A Path to the SBOM file on disk (temporary, managed by framework)
    - context: Optional SBOMContext with pre-computed metadata (sha256_hash, etc.)
    - config: Optional plugin-specific configuration via __init__

    Example:
        >>> class MyPlugin(AssessmentPlugin):
        ...     VERSION = "1.0.0"
        ...
        ...     def get_metadata(self) -> PluginMetadata:
        ...         return PluginMetadata(
        ...             name="my-plugin",
        ...             version=self.VERSION,
        ...             category=AssessmentCategory.COMPLIANCE,
        ...         )
        ...
        ...     def assess(self, sbom_id: str, sbom_path: Path, context: SBOMContext | None = None) -> AssessmentResult:
        ...         # Use context.sha256_hash if available, otherwise compute from file
        ...         sha256 = context.sha256_hash if context else self._compute_hash(sbom_path)
        ...         ...
    """

    def __init__(self, config: dict | None = None) -> None:
        """Initialize plugin with optional configuration.

        Args:
            config: Plugin-specific configuration (e.g., policy rules, thresholds).
                The framework computes config_hash from this for tracking.
        """
        self.config = config or {}

    @abstractmethod
    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata including name, version, and category.

        This metadata is used by the framework to:
        - Identify the plugin in AssessmentRun records
        - Determine plugin behavior (re-run triggers, etc.)
        - Display plugin information in the UI

        Returns:
            PluginMetadata with name, version, and category.
        """

    @abstractmethod
    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        """Run the assessment against the SBOM.

        The framework handles:
        - Fetching the SBOM from object storage
        - Writing it to a temporary file
        - Passing the path to this method
        - Providing pre-computed context when available
        - Cleaning up the temporary file after assessment
        - Checking plugin dependencies and passing the status

        Args:
            sbom_id: The SBOM's primary key (for result association).
            sbom_path: Path to the SBOM file on disk (read-only, temporary).
            dependency_status: Optional dependency status provided by the orchestrator.
                Structure:
                {
                    "requires_one_of": {
                        "satisfied": bool,
                        "passing_plugins": ["plugin-name", ...],
                        "failed_plugins": ["plugin-name", ...]
                    },
                    "requires_all": {
                        "satisfied": bool,
                        "passing_plugins": ["plugin-name", ...],
                        "failed_plugins": ["plugin-name", ...]
                    }
                }
                Plugins can use this to report dependency status in their findings
                without directly querying the database (per ADR-003).
            context: Optional SBOMContext with pre-computed metadata.
                When available, plugins should use context.sha256_hash
                instead of recalculating from the file.

        Returns:
            Normalized AssessmentResult with findings and summary.

        Raises:
            Any exception will be caught by the framework and recorded
            as a failed assessment run with the error message.
        """
