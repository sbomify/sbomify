"""Dramatiq tasks for the plugin framework.

This module provides async task definitions for running assessments
in the background using Dramatiq workers.
"""

from __future__ import annotations

import logging
from typing import Any

import dramatiq
from django.db import connection, transaction
from django.db.utils import DatabaseError, OperationalError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import User
from sbomify.task_utils import format_task_error

from ..orchestrator import PluginOrchestrator, PluginOrchestratorError
from ..sdk.enums import RunReason

logger = logging.getLogger(__name__)


@dramatiq.actor(
    queue_name="plugins",
    max_retries=3,
    time_limit=300000,  # 5 minutes
    store_results=True,
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def run_assessment_task(
    sbom_id: str,
    plugin_name: str,
    run_reason: str,
    config: dict | None = None,
    triggered_by_user_id: int | None = None,
    triggered_by_token_id: str | None = None,
) -> dict[str, Any]:
    """Run an assessment asynchronously.

    This task is enqueued by the framework when an assessment needs to be run.
    It handles database connection management and error reporting.

    Args:
        sbom_id: The SBOM's primary key.
        plugin_name: The plugin identifier to run.
        run_reason: Why this assessment is being triggered (RunReason value).
        config: Optional configuration overrides for the plugin.
        triggered_by_user_id: Optional ID of user who triggered a manual run.
        triggered_by_token_id: Optional ID of API token used to trigger the run.

    Returns:
        Dictionary with assessment run details:
        - assessment_run_id: UUID of the created AssessmentRun
        - status: Final status of the run
        - plugin_name: Name of the plugin that was run
        - error: Error message if the run failed
    """
    logger.info(
        f"[TASK_run_assessment] Starting assessment for SBOM {sbom_id} with plugin {plugin_name} (reason: {run_reason})"
    )

    # Ensure database connection is fresh
    connection.ensure_connection()

    try:
        # Convert string run_reason back to enum
        reason = RunReason(run_reason)

        # Look up user and token if provided
        triggered_by_user = None
        triggered_by_token = None

        if triggered_by_user_id:
            try:
                triggered_by_user = User.objects.get(id=triggered_by_user_id)
            except User.DoesNotExist:
                logger.warning(f"[TASK_run_assessment] User {triggered_by_user_id} not found")

        if triggered_by_token_id:
            try:
                triggered_by_token = AccessToken.objects.get(id=triggered_by_token_id)
            except AccessToken.DoesNotExist:
                logger.warning(f"[TASK_run_assessment] Token {triggered_by_token_id} not found")

        # Run the assessment within a transaction for atomicity
        with transaction.atomic():
            orchestrator = PluginOrchestrator()
            assessment_run = orchestrator.run_assessment_by_name(
                sbom_id=sbom_id,
                plugin_name=plugin_name,
                run_reason=reason,
                config=config,
                triggered_by_user=triggered_by_user,
                triggered_by_token=triggered_by_token,
            )

        logger.info(
            f"[TASK_run_assessment] Completed assessment run {assessment_run.id} with status {assessment_run.status}"
        )

        return {
            "assessment_run_id": str(assessment_run.id),
            "status": assessment_run.status,
            "plugin_name": plugin_name,
            "error": assessment_run.error_message or None,
        }

    except PluginOrchestratorError as e:
        logger.error(f"[TASK_run_assessment] Orchestrator error: {e}")
        return format_task_error("run_assessment", sbom_id, str(e))

    except Exception as e:
        logger.exception(f"[TASK_run_assessment] Unexpected error: {e}")
        raise  # Re-raise for Dramatiq retry


def enqueue_assessment(
    sbom_id: str,
    plugin_name: str,
    run_reason: RunReason,
    config: dict | None = None,
    triggered_by_user: User | None = None,
    triggered_by_token: AccessToken | None = None,
) -> None:
    """Enqueue an assessment to be run asynchronously.

    This is the primary interface for triggering assessments. It serializes
    the arguments and sends the task to the Dramatiq queue.

    The task dispatch is wrapped in transaction.on_commit() to ensure that
    the SBOM and any related data are visible to the worker when the task
    runs. If called outside a transaction, the task is sent immediately.

    Args:
        sbom_id: The SBOM's primary key.
        plugin_name: The plugin identifier to run.
        run_reason: Why this assessment is being triggered.
        config: Optional configuration overrides for the plugin.
        triggered_by_user: Optional user who triggered a manual run.
        triggered_by_token: Optional API token used to trigger the run.

    Example:
        >>> from sbomify.apps.plugins.tasks import enqueue_assessment
        >>> from sbomify.apps.plugins.sdk import RunReason
        >>> enqueue_assessment(
        ...     sbom_id="abc123",
        ...     plugin_name="checksum",
        ...     run_reason=RunReason.ON_UPLOAD,
        ... )
    """
    # Capture values at call time for the closure, as on_commit callbacks execute after this function returns
    task_sbom_id = sbom_id
    task_plugin_name = plugin_name
    task_run_reason = run_reason.value
    task_config = config
    task_user_id = triggered_by_user.id if triggered_by_user else None
    task_token_id = str(triggered_by_token.id) if triggered_by_token else None

    def _send_task():
        """Send the assessment task to the queue."""
        run_assessment_task.send(
            sbom_id=task_sbom_id,
            plugin_name=task_plugin_name,
            run_reason=task_run_reason,
            config=task_config,
            triggered_by_user_id=task_user_id,
            triggered_by_token_id=task_token_id,
        )
        logger.info(
            f"[PLUGIN] Enqueued assessment for SBOM {task_sbom_id} with plugin {task_plugin_name} "
            f"(reason: {task_run_reason})"
        )

    # Defer task dispatch until after transaction commits to ensure SBOM is visible to workers.
    # If called outside a transaction (autocommit mode), the callback runs immediately.
    transaction.on_commit(_send_task)


def enqueue_assessments_for_sbom(
    sbom_id: str,
    team_id: str,
    run_reason: RunReason,
    triggered_by_user: User | None = None,
    triggered_by_token: AccessToken | None = None,
) -> list[str]:
    """Enqueue all enabled assessments for an SBOM.

    This convenience function looks up the team's plugin settings
    and enqueues tasks for each enabled plugin.

    Task dispatch is transaction-safe: tasks are deferred until after the
    current transaction commits (via enqueue_assessment's on_commit wrapper),
    ensuring the SBOM is visible to workers when tasks run.

    Args:
        sbom_id: The SBOM's primary key.
        team_id: The team's primary key.
        run_reason: Why assessments are being triggered.
        triggered_by_user: Optional user who triggered the assessments.
        triggered_by_token: Optional API token used to trigger the assessments.

    Returns:
        List of plugin names that were enqueued.
    """
    from ..models import RegisteredPlugin, TeamPluginSettings

    # Get team settings
    try:
        settings = TeamPluginSettings.objects.get(team_id=team_id)
        enabled_plugins = settings.enabled_plugins or []
    except TeamPluginSettings.DoesNotExist:
        # No settings configured, no plugins to run
        logger.debug(f"[PLUGIN] No settings for team {team_id}, skipping assessments")
        return []

    # Filter to only enabled plugins in the registry
    available_plugins = set(
        RegisteredPlugin.objects.filter(
            is_enabled=True,
            name__in=enabled_plugins,
        ).values_list("name", flat=True)
    )

    enqueued = []
    for plugin_name in enabled_plugins:
        if plugin_name not in available_plugins:
            logger.warning(f"[PLUGIN] Plugin '{plugin_name}' enabled for team {team_id} but not available in registry")
            continue

        # Get plugin-specific config if any
        plugin_config = settings.get_plugin_config(plugin_name)

        enqueue_assessment(
            sbom_id=sbom_id,
            plugin_name=plugin_name,
            run_reason=run_reason,
            config=plugin_config or None,
            triggered_by_user=triggered_by_user,
            triggered_by_token=triggered_by_token,
        )
        enqueued.append(plugin_name)

    logger.info(f"[PLUGIN] Enqueued {len(enqueued)} assessments for SBOM {sbom_id}: {enqueued}")

    return enqueued
