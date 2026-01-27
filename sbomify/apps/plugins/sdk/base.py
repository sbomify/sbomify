"""Base class for assessment plugins.

This module defines the abstract base class that all assessment plugins must implement.
Plugins are responsible for analyzing SBOMs and returning normalized results.
"""

from abc import ABC, abstractmethod
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


class AssessmentPlugin(ABC):
    """Base class for all assessment plugins.

    Plugins implement specific assessment logic (security scanning, compliance
    checking, license validation, etc.) and return normalized results.

    The framework handles:
    - Fetching the SBOM from object storage
    - Writing it to a temporary file
    - Passing the path to the assess() method
    - Cleaning up the temporary file after assessment

    Plugins receive:
    - sbom_id: The SBOM's primary key for result association
    - sbom_path: A Path to the SBOM file on disk (temporary, managed by framework)
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
        ...     def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        ...         # Read SBOM and perform assessment
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
    def assess(self, sbom_id: str, sbom_path: Path) -> AssessmentResult:
        """Run the assessment against the SBOM.

        The framework handles:
        - Fetching the SBOM from object storage
        - Writing it to a temporary file
        - Passing the path to this method
        - Cleaning up the temporary file after assessment

        Args:
            sbom_id: The SBOM's primary key (for result association).
            sbom_path: Path to the SBOM file on disk (read-only, temporary).

        Returns:
            Normalized AssessmentResult with findings and summary.

        Raises:
            Any exception will be caught by the framework and recorded
            as a failed assessment run with the error message.
        """
