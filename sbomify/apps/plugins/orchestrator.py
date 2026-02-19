"""Assessment orchestrator for managing plugin execution.

This module provides the AssessmentOrchestrator class that handles the
lifecycle of assessment runs, including fetching SBOMs from storage,
executing plugins, and storing results.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from django.utils import timezone

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import SBOMDataError, get_sbom_data_bytes
from sbomify.logging import getLogger

from .models import AssessmentRun, RegisteredPlugin
from .sdk.base import AssessmentPlugin, RetryLaterError, SBOMContext
from .sdk.enums import RunReason, RunStatus
from .utils import compute_config_hash, compute_content_digest

if TYPE_CHECKING:
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.core.models import User

logger = getLogger(__name__)


class DependencyCheckResult(TypedDict):
    """Result of checking a single dependency group."""

    satisfied: bool
    passing_plugins: list[str]
    failed_plugins: list[str]


class DependencyStatus(TypedDict, total=False):
    """Status of plugin dependencies passed to assess().

    This TypedDict is partial (total=False). A key is present only if
    the plugin declares the corresponding dependency type in its
    dependencies configuration:

    - requires_one_of is included when the plugin defines a
      requires_one_of dependency group.
    - requires_all is included when the plugin defines a
      requires_all dependency group.
    """

    requires_one_of: DependencyCheckResult
    requires_all: DependencyCheckResult


class PluginOrchestratorError(Exception):
    """Exception raised for orchestrator-specific errors."""

    pass


class PluginOrchestrator:
    """Framework component that manages plugin execution.

    The orchestrator handles all aspects of running assessments:
    1. Fetching SBOM from object storage to temporary file
    2. Computing config_hash from plugin configuration
    3. Calling plugin.assess() with sbom_id and file path
    4. Storing AssessmentRun record with results
    5. Cleaning up temporary files

    Example:
        >>> orchestrator = PluginOrchestrator()
        >>> run = orchestrator.run_assessment(
        ...     sbom_id="abc123",
        ...     plugin=ChecksumPlugin(),
        ...     run_reason=RunReason.ON_UPLOAD,
        ... )
        >>> print(run.status)
        'completed'
    """

    def run_assessment(
        self,
        sbom_id: str,
        plugin: AssessmentPlugin,
        run_reason: RunReason,
        triggered_by_user: User | None = None,
        triggered_by_token: AccessToken | None = None,
        existing_run_id: str | None = None,
    ) -> AssessmentRun:
        """Execute a plugin assessment with full lifecycle management.

        This method:
        1. Creates an AssessmentRun record in PENDING state (or reuses existing)
        2. Fetches SBOM from object storage to temporary file
        3. Computes config_hash from plugin.config
        4. Calls plugin.assess() with sbom_id and file path
        5. Updates AssessmentRun with results
        6. Cleans up temporary file

        Args:
            sbom_id: The SBOM's primary key.
            plugin: An initialized AssessmentPlugin instance.
            run_reason: Why this assessment is being triggered.
            triggered_by_user: Optional user who triggered a manual run.
            triggered_by_token: Optional API token used to trigger the run.
            existing_run_id: Optional ID of an existing AssessmentRun to reuse
                (for retries after RetryLaterError).

        Returns:
            The AssessmentRun record with results.

        Raises:
            PluginOrchestratorError: If the SBOM cannot be fetched or
                other orchestration errors occur.
        """
        # Verify SBOM exists before creating the run
        if not SBOM.objects.filter(id=sbom_id).exists():
            raise PluginOrchestratorError(f"SBOM '{sbom_id}' not found - it may have been deleted")

        # Get plugin metadata
        metadata = plugin.get_metadata()
        config_hash = compute_config_hash(plugin.config)

        # Reuse existing run if provided (for retries), otherwise create new
        if existing_run_id:
            try:
                assessment_run = AssessmentRun.objects.get(id=existing_run_id)
            except AssessmentRun.DoesNotExist:
                raise PluginOrchestratorError(f"AssessmentRun '{existing_run_id}' not found")

            # Validate that the existing run matches the current parameters
            if assessment_run.sbom_id != sbom_id:
                raise PluginOrchestratorError(
                    f"AssessmentRun '{existing_run_id}' belongs to SBOM '{assessment_run.sbom_id}', not '{sbom_id}'"
                )
            if assessment_run.plugin_name != metadata.name:
                raise PluginOrchestratorError(
                    f"AssessmentRun '{existing_run_id}' belongs to plugin '{assessment_run.plugin_name}', "
                    f"not '{metadata.name}'"
                )

            logger.info(
                f"[PLUGIN] Reusing existing run {assessment_run.id} for SBOM {sbom_id} "
                f"with plugin {metadata.name} v{metadata.version}"
            )
        else:
            # Create the AssessmentRun record in PENDING state
            assessment_run = AssessmentRun.objects.create(
                sbom_id=sbom_id,
                plugin_name=metadata.name,
                plugin_version=metadata.version,
                plugin_config_hash=config_hash,
                category=metadata.category.value,
                run_reason=run_reason.value,
                status=RunStatus.PENDING.value,
                triggered_by_user=triggered_by_user,
                triggered_by_token=triggered_by_token,
            )
            logger.info(
                f"[PLUGIN] Created run {assessment_run.id} for SBOM {sbom_id} "
                f"with plugin {metadata.name} v{metadata.version}"
            )

        try:
            # Update status to RUNNING
            assessment_run.status = RunStatus.RUNNING.value
            # Only set started_at on first attempt (not on retries)
            if not assessment_run.started_at:
                assessment_run.started_at = timezone.now()
                assessment_run.save(update_fields=["status", "started_at"])
            else:
                assessment_run.save(update_fields=["status"])

            # Fetch SBOM from storage
            sbom_instance, sbom_bytes = get_sbom_data_bytes(sbom_id)

            # Compute content digest for auditability
            content_digest = compute_content_digest(sbom_bytes)
            assessment_run.input_content_digest = content_digest
            assessment_run.save(update_fields=["input_content_digest"])

            # Build SBOMContext with pre-computed metadata from database
            # This allows plugins to skip redundant computations (e.g., sha256_hash)
            sbom_context = SBOMContext(
                sha256_hash=sbom_instance.sha256_hash,
                sbom_format=sbom_instance.format,
                format_version=sbom_instance.format_version,
                sbom_name=sbom_instance.name,
                sbom_version=sbom_instance.version,
                component_id=sbom_instance.component_id,
                team_id=sbom_instance.component.team_id if sbom_instance.component else None,
            )

            # Write to temporary file and execute plugin
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".json",
                delete=True,
            ) as temp_file:
                temp_file.write(sbom_bytes)
                temp_file.flush()
                temp_path = Path(temp_file.name)

                logger.debug(f"[PLUGIN] Running plugin {metadata.name} on SBOM {sbom_id} (temp file: {temp_path})")

                # Check dependencies and pass status to plugin
                dependency_status = self._check_dependencies(sbom_id, metadata.name)

                # Execute the plugin with dependency status and context
                result = plugin.assess(sbom_id, temp_path, dependency_status, context=sbom_context)

            # Update AssessmentRun with results
            assessment_run.result = result.to_dict()
            assessment_run.result_schema_version = result.schema_version
            assessment_run.status = RunStatus.COMPLETED.value
            assessment_run.completed_at = timezone.now()
            assessment_run.save(
                update_fields=[
                    "result",
                    "result_schema_version",
                    "status",
                    "completed_at",
                ]
            )

            logger.info(
                f"[PLUGIN] Completed run {assessment_run.id} for SBOM {sbom_id} "
                f"with {result.summary.total_findings} findings"
            )

        except SBOMDataError as e:
            # SBOM fetch error
            logger.error(f"[PLUGIN] SBOM fetch error for run {assessment_run.id}: {e}")
            self._mark_failed(assessment_run, str(e))

        except RetryLaterError as e:
            # Re-raise with run ID attached to allow task layer to reuse the run.
            # This is expected for transient conditions (e.g., attestations not yet processed).
            logger.info(f"[PLUGIN] Transient condition for run {assessment_run.id}, will be retried by task layer")
            # Mark as pending so it can be retried
            assessment_run.status = RunStatus.PENDING.value
            assessment_run.save(update_fields=["status"])
            # Attach run ID to exception for task layer to use
            e.assessment_run_id = str(assessment_run.id)
            raise

        except Exception as e:
            # Plugin execution error
            logger.exception(f"[PLUGIN] Plugin error for run {assessment_run.id}: {e}")
            self._mark_failed(assessment_run, str(e))

        return assessment_run

    def _mark_failed(self, assessment_run: AssessmentRun, error_message: str) -> None:
        """Mark an assessment run as failed.

        Args:
            assessment_run: The run to mark as failed.
            error_message: The error message to record.
        """
        assessment_run.status = RunStatus.FAILED.value
        assessment_run.error_message = error_message
        assessment_run.completed_at = timezone.now()
        assessment_run.save(update_fields=["status", "error_message", "completed_at"])

    def _check_dependencies(self, sbom_id: str, plugin_name: str) -> DependencyStatus | None:
        """Check dependency status for a plugin.

        This method checks the plugin's declared dependencies and returns
        a status dict that can be passed to the plugin's assess() method.
        Plugins can use this to report dependency status without directly
        querying the database (per ADR-003).

        Args:
            sbom_id: The SBOM's primary key.
            plugin_name: The plugin identifier.

        Returns:
            dependency_status dict to pass to plugin.assess(), or None if
            the plugin has no dependencies.
        """
        try:
            registered = RegisteredPlugin.objects.get(name=plugin_name)
        except RegisteredPlugin.DoesNotExist:
            logger.warning(f"[PLUGIN] Plugin '{plugin_name}' not found in registry")
            return None

        dependencies = registered.dependencies or {}

        if not dependencies:
            return None

        dependency_status: DependencyStatus = {}

        # Check requires_one_of (OR logic - at least one must pass)
        if "requires_one_of" in dependencies:
            dependency_status["requires_one_of"] = self._check_one_of(sbom_id, dependencies["requires_one_of"])

        # Check requires_all (AND logic - all must pass)
        if "requires_all" in dependencies:
            dependency_status["requires_all"] = self._check_all_of(sbom_id, dependencies["requires_all"])

        return dependency_status if dependency_status else None

    def _check_one_of(self, sbom_id: str, deps: list) -> DependencyCheckResult:
        """Check if at least one dependency is satisfied (OR logic).

        Args:
            sbom_id: The SBOM's primary key.
            deps: List of dependency specs ({"type": "category|plugin", "value": "..."}).

        Returns:
            Status dict with satisfied, passing_plugins, and failed_plugins.
        """
        passing: list[str] = []
        failed: list[str] = []

        for dep in deps:
            dep_type = dep.get("type")
            dep_value = dep.get("value")

            if dep_type == "category":
                # Find any passing plugin in this category
                runs = AssessmentRun.objects.filter(
                    sbom_id=sbom_id,
                    category=dep_value,
                    status=RunStatus.COMPLETED.value,
                ).only("plugin_name", "result")
                for run in runs:
                    if self._is_passing(run):
                        passing.append(run.plugin_name)
                    else:
                        failed.append(run.plugin_name)

            elif dep_type == "plugin":
                # Check specific plugin
                run = (
                    AssessmentRun.objects.filter(
                        sbom_id=sbom_id,
                        plugin_name=dep_value,
                        status=RunStatus.COMPLETED.value,
                    )
                    .only("plugin_name", "result")
                    .order_by("-created_at")
                    .first()
                )

                if run:
                    if self._is_passing(run):
                        passing.append(run.plugin_name)
                    else:
                        failed.append(run.plugin_name)

        return {
            "satisfied": len(passing) > 0,
            "passing_plugins": list(set(passing)),
            "failed_plugins": list(set(failed)),
        }

    def _check_all_of(self, sbom_id: str, deps: list) -> DependencyCheckResult:
        """Check if all dependencies are satisfied (AND logic).

        Args:
            sbom_id: The SBOM's primary key.
            deps: List of dependency specs ({"type": "category|plugin", "value": "..."}).

        Returns:
            Status dict with satisfied, passing_plugins, and failed_plugins.
        """
        passing: list[str] = []
        failed: list[str] = []
        all_satisfied = True

        for dep in deps:
            dep_type = dep.get("type")
            dep_value = dep.get("value")
            dep_satisfied = False

            if dep_type == "category":
                # At least one plugin in this category must pass
                runs = AssessmentRun.objects.filter(
                    sbom_id=sbom_id,
                    category=dep_value,
                    status=RunStatus.COMPLETED.value,
                ).only("plugin_name", "result")
                for run in runs:
                    if self._is_passing(run):
                        passing.append(run.plugin_name)
                        dep_satisfied = True
                    else:
                        failed.append(run.plugin_name)

            elif dep_type == "plugin":
                # Specific plugin must pass
                run = (
                    AssessmentRun.objects.filter(
                        sbom_id=sbom_id,
                        plugin_name=dep_value,
                        status=RunStatus.COMPLETED.value,
                    )
                    .only("plugin_name", "result")
                    .order_by("-created_at")
                    .first()
                )

                if run:
                    if self._is_passing(run):
                        passing.append(run.plugin_name)
                        dep_satisfied = True
                    else:
                        failed.append(run.plugin_name)

            if not dep_satisfied:
                all_satisfied = False

        return {
            "satisfied": all_satisfied,
            "passing_plugins": list(set(passing)),
            "failed_plugins": list(set(failed)),
        }

    def _is_passing(self, run: AssessmentRun) -> bool:
        """Check if an assessment run is passing.

        For security plugins: passing means no vulnerabilities found (by_severity all zero).
        For compliance/other plugins: passing means no failures and no errors.

        Args:
            run: The AssessmentRun to check.

        Returns:
            True if the run is passing, False otherwise.
        """
        if not run.result or not isinstance(run.result, dict):
            return False

        summary = run.result.get("summary")
        if not isinstance(summary, dict):
            return False

        if run.category == "security":
            by_severity = summary.get("by_severity") or {}
            total_from_severity = sum(
                by_severity.get(sev, 0) for sev in ("critical", "high", "medium", "low", "info", "unknown")
            )
            return total_from_severity == 0

        return summary.get("fail_count", 0) == 0 and summary.get("error_count", 0) == 0

    def get_plugin_instance(
        self,
        plugin_name: str,
        config: dict | None = None,
    ) -> AssessmentPlugin:
        """Load and instantiate a plugin by name.

        Looks up the plugin in RegisteredPlugin and dynamically imports it.

        Args:
            plugin_name: The plugin identifier.
            config: Optional configuration to pass to the plugin.

        Returns:
            An initialized AssessmentPlugin instance.

        Raises:
            PluginOrchestratorError: If the plugin is not found or disabled.
        """
        try:
            registered = RegisteredPlugin.objects.get(name=plugin_name)
        except RegisteredPlugin.DoesNotExist:
            raise PluginOrchestratorError(f"Plugin '{plugin_name}' is not registered")

        if not registered.is_enabled:
            raise PluginOrchestratorError(f"Plugin '{plugin_name}' is disabled")

        # Merge default config with provided config
        merged_config = {**registered.default_config, **(config or {})}

        # Import and instantiate the plugin class
        try:
            module_path, class_name = registered.plugin_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            plugin_class = getattr(module, class_name)
            return plugin_class(config=merged_config)
        except (ImportError, AttributeError) as e:
            raise PluginOrchestratorError(
                f"Failed to load plugin '{plugin_name}' from '{registered.plugin_class_path}': {e}"
            )

    def run_assessment_by_name(
        self,
        sbom_id: str,
        plugin_name: str,
        run_reason: RunReason,
        config: dict | None = None,
        triggered_by_user: User | None = None,
        triggered_by_token: AccessToken | None = None,
        existing_run_id: str | None = None,
    ) -> AssessmentRun:
        """Run an assessment by plugin name.

        Convenience method that loads the plugin by name and runs the assessment.

        Args:
            sbom_id: The SBOM's primary key.
            plugin_name: The plugin identifier to run.
            run_reason: Why this assessment is being triggered.
            config: Optional configuration overrides for the plugin.
            triggered_by_user: Optional user who triggered a manual run.
            triggered_by_token: Optional API token used to trigger the run.
            existing_run_id: Optional ID of an existing AssessmentRun to reuse
                (for retries after RetryLaterError).

        Returns:
            The AssessmentRun record with results.
        """
        plugin = self.get_plugin_instance(plugin_name, config)
        return self.run_assessment(
            sbom_id=sbom_id,
            plugin=plugin,
            run_reason=run_reason,
            triggered_by_user=triggered_by_user,
            triggered_by_token=triggered_by_token,
            existing_run_id=existing_run_id,
        )
