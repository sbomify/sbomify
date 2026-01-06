"""Assessment orchestrator for managing plugin execution.

This module provides the AssessmentOrchestrator class that handles the
lifecycle of assessment runs, including fetching SBOMs from storage,
executing plugins, and storing results.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from django.utils import timezone

from sbomify.apps.sboms.utils import SBOMDataError, get_sbom_data_bytes
from sbomify.logging import getLogger

from .models import AssessmentRun, RegisteredPlugin
from .sdk.base import AssessmentPlugin
from .sdk.enums import RunReason, RunStatus
from .utils import compute_config_hash, compute_content_digest

if TYPE_CHECKING:
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.core.models import User

logger = getLogger(__name__)


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
    ) -> AssessmentRun:
        """Execute a plugin assessment with full lifecycle management.

        This method:
        1. Creates an AssessmentRun record in PENDING state
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

        Returns:
            The AssessmentRun record with results.

        Raises:
            PluginOrchestratorError: If the SBOM cannot be fetched or
                other orchestration errors occur.
        """
        # Get plugin metadata
        metadata = plugin.get_metadata()
        config_hash = compute_config_hash(plugin.config)

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
            assessment_run.started_at = timezone.now()
            assessment_run.save(update_fields=["status", "started_at"])

            # Fetch SBOM from storage
            sbom_instance, sbom_bytes = get_sbom_data_bytes(sbom_id)

            # Compute content digest for auditability
            content_digest = compute_content_digest(sbom_bytes)
            assessment_run.input_content_digest = content_digest
            assessment_run.save(update_fields=["input_content_digest"])

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

                # Execute the plugin
                result = plugin.assess(sbom_id, temp_path)

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
        )
