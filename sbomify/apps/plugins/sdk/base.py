"""Base class for assessment plugins.

This module defines the abstract base class that all assessment plugins must implement.
Plugins are responsible for analyzing SBOMs and returning normalized results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .results import AssessmentResult, AssessmentSummary, Finding, PluginMetadata


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
        bom_type: The BOM type discriminator (e.g., 'sbom', 'vex', 'cbom'). See ADR-006.
        release_id: The primary key of the Release whose association triggered
            this assessment (from the ReleaseArtifact post_save signal).
            Under the scan-once-per-SBOM model, a single scan covers ALL
            releases linked to the SBOM — this field is an informational
            hint only, NOT a scoping key. Continuous plugins (scan_mode=
            CONTINUOUS) should use ``sync_release_tags()`` to reconcile
            release state after completion rather than acting on this field.
            None means the trigger was not release-scoped (upload, cron,
            manual).
        signature_blob_key: S3 key for the stored cryptographic signature (if attached).
        signature_type: Signature format (e.g., 'cosign-bundle', 'pgp-detached').
        provenance_blob_key: S3 key for the stored in-toto DSSE provenance envelope (if attached).
    """

    sha256_hash: str | None = None
    sbom_format: str | None = None
    format_version: str | None = None
    sbom_name: str | None = None
    sbom_version: str | None = None
    component_id: str | None = None
    team_id: int | None = None
    bom_type: str | None = None
    release_id: str | None = None
    signature_blob_key: str | None = None
    signature_type: str | None = None
    provenance_blob_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


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

    def __init__(self, config: dict[str, Any] | None = None) -> None:
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
        dependency_status: dict[str, Any] | None = None,
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

    def build_single_finding_result(
        self,
        *,
        finding_id: str,
        title: str,
        description: str,
        status: str,
        severity: str,
        metadata: dict[str, Any],
        pass_count: int = 0,
        fail_count: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
    ) -> AssessmentResult:
        """Construct an AssessmentResult carrying a single status marker.

        For the results that say something about the run rather than about the
        artifact: an operational failure, or a precondition the plugin could not
        meet. Plugin name, version, category and timestamp are read from
        ``get_metadata()``, so every plugin's markers come out the same shape
        and a change here reaches all of them.

        Args:
            finding_id: Stable identifier, namespaced with the plugin slug
                (e.g. ``"osv:unsupported-spec-version"``). That namespace is
                what ``vulnerability_scanning.utils.is_vulnerability`` reads to
                keep a marker out of the CVE rows and severity counts.
            title: Human-readable title.
            description: What happened, in terms the operator can act on.
            status: Finding status ("warning" for a skip, "error" for a failure).
            severity: Finding severity.
            metadata: Result-level metadata (e.g. ``{"skipped": True}``).
            pass_count: Summary pass count.
            fail_count: Summary fail count.
            warning_count: Summary warning count.
            error_count: Summary error count.

        Returns:
            AssessmentResult with exactly one finding.
        """
        finding = Finding(
            id=finding_id,
            title=title,
            description=description,
            status=status,
            severity=severity,
        )
        # The status marker rides the findings array so the run panel can show
        # why nothing was scanned, but it is not a vulnerability: the summary
        # must not count it, or a skipped run reads as "1 finding".
        summary = AssessmentSummary(
            total_findings=0,
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            error_count=error_count,
        )
        plugin_metadata = self.get_metadata()
        return AssessmentResult(
            plugin_name=plugin_metadata.name,
            plugin_version=plugin_metadata.version,
            category=plugin_metadata.category.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            findings=[finding],
            metadata=metadata,
        )

    def create_skipped_result(
        self,
        *,
        finding_id: str,
        title: str,
        description: str,
        unsupported_input: bool = False,
        extra_metadata: dict[str, Any] | None = None,
    ) -> AssessmentResult:
        """Create a non-failing result indicating the assessment was skipped.

        For when the plugin's preconditions aren't met but the situation is not
        an error: an SBOM with no release association, an artifact the scanner
        cannot read, a spec version the scanner has not caught up to. A
        capability gap is not a fault, and recording one as an error puts a
        high-severity Scan Error on a valid artifact, again on every sweep.

        The returned finding uses status="warning" with severity="info", and
        the top-level AssessmentResult metadata contains {"skipped": True}.
        API consumers that aggregate plugin results into an overall posture
        MUST check metadata["skipped"] to distinguish "assessment was skipped"
        from "assessment ran and reported a real warning finding". A raw
        status check alone is not sufficient.

        Args:
            finding_id: Stable identifier for the finding.
            title: Human-readable title.
            description: Detailed reason the assessment was skipped.
            unsupported_input: True when the skip is because the scanner could
                not read the artifact at all, rather than because a per-run
                precondition was unmet. Re-running such an SBOM on the next
                sweep repeats the rejection verbatim, so the scheduled task
                backs it off; see ``UNSUPPORTED_INPUT_SKIP_HOURS``.
            extra_metadata: Further result-level keys to merge in, for plugins
                that record how they stood down.

        Returns:
            AssessmentResult with a single warning finding and metadata
            containing ``skipped: True``, plus ``unsupported_input: True`` when
            that argument is set. Consumers should test for the keys they care
            about rather than compare the dict, since this shape grows.
        """
        metadata: dict[str, Any] = {"skipped": True}
        if unsupported_input:
            metadata["unsupported_input"] = True
        if extra_metadata:
            metadata.update(extra_metadata)
        return self.build_single_finding_result(
            finding_id=finding_id,
            title=title,
            description=description,
            status="warning",
            severity="info",
            metadata=metadata,
            warning_count=1,
        )

    def sync_release_tags(self, *, sbom_id: str, run_id: str, release: Any) -> None:
        """Reconcile downstream release state after the AssessmentRun.releases M2M changes.

        Called by the framework (orchestrator at run completion, attach/detach
        tasks on release association changes) for plugins whose metadata
        declares ``scan_mode = ScanMode.CONTINUOUS``. One-shot plugins do
        not need this because they have no long-lived downstream state to
        keep in sync.

        The default implementation is a no-op. Continuous plugins that
        maintain release-scoped state in an external system (e.g.,
        Dependency Track project version tags) should override this
        method to push the canonical release set from the M2M.

        Args:
            sbom_id: The SBOM primary key.
            run_id: The AssessmentRun primary key whose M2M changed.
            release: The Release instance that triggered the change, or
                None when called at run completion or after a release
                deletion.
        """
