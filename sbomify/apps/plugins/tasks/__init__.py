"""Dramatiq tasks for the plugin framework.

This module provides async task definitions for running assessments
in the background using Dramatiq workers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import dramatiq
from django.db import connection, transaction
from django.db.utils import DatabaseError, OperationalError
from django.utils import timezone
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

try:
    from dramatiq_crontab import cron
except ImportError:
    logging.getLogger(__name__).warning("dramatiq-crontab not installed - cron scheduling disabled for plugin tasks")

    def cron(schedule):
        """Fallback decorator when dramatiq-crontab is not installed."""

        def decorator(func):
            return func

        return decorator


from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import broadcast_to_workspace, push_notification
from sbomify.task_utils import format_task_error

from ..orchestrator import PluginOrchestrator, PluginOrchestratorError
from ..sdk.base import RetryLaterError
from ..sdk.enums import RunReason

logger = logging.getLogger(__name__)

# Default cutoff for backfilling SBOMs when plugins are enabled (in hours)
# Only SBOMs created within this window will be queued for assessment
BACKFILL_CUTOFF_HOURS = 24

# Retry delays for RetryLaterError (in milliseconds)
# These delays give external systems time to process:
# - 1st retry: 2 minutes
# - 2nd retry: 5 minutes
# - 3rd retry: 10 minutes
# - 4th retry: 15 minutes
RETRY_LATER_DELAYS_MS = [
    2 * 60 * 1000,  # 2 minutes
    5 * 60 * 1000,  # 5 minutes
    10 * 60 * 1000,  # 10 minutes
    15 * 60 * 1000,  # 15 minutes
]


@dramatiq.actor(
    queue_name="plugins",
    # Dramatiq-level retries for unhandled exceptions (e.g., DB errors).
    # RetryLaterError is handled separately and does not count toward this limit.
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
    _retry_later_count: int = 0,
    _existing_run_id: str | None = None,
) -> dict[str, Any]:
    """Run an assessment asynchronously.

    This task is enqueued by the framework when an assessment needs to be run.
    It handles database connection management and error reporting.

    If a plugin raises RetryLaterError (e.g., attestation not yet available,
    external service still processing), the task will retry with increasing
    delays: 2 min, 5 min, 10 min, 15 min.

    Args:
        sbom_id: The SBOM's primary key.
        plugin_name: The plugin identifier to run.
        run_reason: Why this assessment is being triggered (RunReason value).
        config: Optional configuration overrides for the plugin.
        triggered_by_user_id: Optional ID of user who triggered a manual run.
        triggered_by_token_id: Optional ID of API token used to trigger the run.
        _retry_later_count: Internal counter for RetryLaterError retries.
        _existing_run_id: Internal ID of existing AssessmentRun to reuse (for retries).

    Returns:
        Dictionary with assessment run details:
        - assessment_run_id: UUID of the created AssessmentRun
        - status: Final status of the run
        - plugin_name: Name of the plugin that was run
        - error: Error message if the run failed
    """
    logger.info(
        f"[TASK_run_assessment] Starting assessment for SBOM {sbom_id} with plugin {plugin_name} "
        f"(reason: {run_reason}, retry_later_count: {_retry_later_count}, existing_run: {_existing_run_id})"
    )

    # Ensure database connection is fresh
    connection.ensure_connection()

    # Track retry info if RetryLaterError occurs (set inside atomic block)
    # This allows the transaction to commit before scheduling the retry
    retry_later_info: dict[str, Any] | None = None

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
            try:
                assessment_run = orchestrator.run_assessment_by_name(
                    sbom_id=sbom_id,
                    plugin_name=plugin_name,
                    run_reason=reason,
                    config=config,
                    triggered_by_user=triggered_by_user,
                    triggered_by_token=triggered_by_token,
                    existing_run_id=_existing_run_id,
                )
            except RetryLaterError as e:
                # Capture retry info inside atomic block so transaction commits
                # with the AssessmentRun in PENDING state (not rolled back)
                retry_later_info = {
                    "run_id": getattr(e, "assessment_run_id", None),
                    "error": e,
                }
                # Don't re-raise - let transaction commit with the PENDING run

        # Handle retry AFTER transaction commits (AssessmentRun is now persisted)
        if retry_later_info:
            run_id = retry_later_info["run_id"]
            e = retry_later_info["error"]

            if _retry_later_count < len(RETRY_LATER_DELAYS_MS):
                delay_ms = RETRY_LATER_DELAYS_MS[_retry_later_count]
                logger.info(
                    f"[TASK_run_assessment] Transient condition for SBOM {sbom_id} "
                    f"(run: {run_id or 'unknown'}): {e}. "
                    f"Scheduling retry {_retry_later_count + 1}/{len(RETRY_LATER_DELAYS_MS)} "
                    f"in {delay_ms // 1000}s"
                )

                # Prepare kwargs for the retry; include existing run ID only if we have one
                retry_kwargs: dict[str, Any] = {
                    "sbom_id": sbom_id,
                    "plugin_name": plugin_name,
                    "run_reason": run_reason,
                    "config": config,
                    "triggered_by_user_id": triggered_by_user_id,
                    "triggered_by_token_id": triggered_by_token_id,
                    "_retry_later_count": _retry_later_count + 1,
                }
                if run_id is not None:
                    retry_kwargs["_existing_run_id"] = run_id

                # Re-enqueue the task with incremented retry count
                run_assessment_task.send_with_options(
                    args=(),
                    kwargs=retry_kwargs,
                    delay=delay_ms,
                )

                # Return a pending status - the task will continue later
                response: dict[str, Any] = {
                    "status": "pending_retry",
                    "plugin_name": plugin_name,
                    "message": f"Transient condition, retry scheduled in {delay_ms // 1000}s",
                    "retry_count": _retry_later_count + 1,
                }
                if run_id is not None:
                    response["assessment_run_id"] = run_id
                return response
            else:
                # All retries exhausted - return graceful failure
                logger.warning(
                    f"[TASK_run_assessment] Transient condition persists for SBOM {sbom_id} "
                    f"(run: {run_id or 'unknown'}) "
                    f"after {len(RETRY_LATER_DELAYS_MS)} retries. Returning graceful failure."
                )
                response = {
                    "status": "retry_exhausted",
                    "plugin_name": plugin_name,
                    "error": str(e),
                    "message": (
                        "Assessment could not complete after multiple retries. "
                        "The transient condition may have become permanent. "
                        f"Last error: {e}"
                    ),
                }
                if run_id is not None:
                    response["assessment_run_id"] = run_id
                return response

        logger.info(
            f"[TASK_run_assessment] Completed assessment run {assessment_run.id} with status {assessment_run.status}"
        )

        # Broadcast assessment completion to workspace for real-time UI updates
        try:
            workspace_key = assessment_run.sbom.component.team.key
            broadcast_to_workspace(
                workspace_key=workspace_key,
                message_type="assessment_complete",
                data={
                    "sbom_id": sbom_id,
                    "plugin_name": plugin_name,
                    "status": assessment_run.status,
                },
            )

            # Push notification for failed assessments
            if assessment_run.status == "failed":
                push_notification(
                    workspace_key=workspace_key,
                    message=f"Assessment '{plugin_name}' failed for {assessment_run.sbom.name}",
                    severity="warning",
                    notification_type="assessment",
                    action_url=f"/dashboard/components/{assessment_run.sbom.component.id}/",
                )
        except Exception as broadcast_error:
            # Don't fail the task if broadcast fails
            logger.warning(f"[TASK_run_assessment] Failed to broadcast assessment completion: {broadcast_error}")

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
    delay_ms: int | None = None,
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
        delay_ms: Optional delay in milliseconds before the task runs.
            Useful for plugins that depend on external systems (e.g., attestation
            plugins that need to wait for GitHub to process attestations).

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
    task_delay_ms = delay_ms

    def _send_task():
        """Send the assessment task to the queue."""
        run_assessment_task.send_with_options(
            args=(),
            kwargs={
                "sbom_id": task_sbom_id,
                "plugin_name": task_plugin_name,
                "run_reason": task_run_reason,
                "config": task_config,
                "triggered_by_user_id": task_user_id,
                "triggered_by_token_id": task_token_id,
                "_retry_later_count": 0,
                "_existing_run_id": None,
            },
            delay=task_delay_ms,
        )
        delay_info = f", delay={task_delay_ms}ms" if task_delay_ms else ""
        logger.info(
            f"[PLUGIN] Enqueued assessment for SBOM {task_sbom_id} with plugin {task_plugin_name} "
            f"(reason: {task_run_reason}{delay_info})"
        )

    # Defer task dispatch until after transaction commits to ensure SBOM is visible to workers.
    # If called outside a transaction (autocommit mode), the callback runs immediately.
    transaction.on_commit(_send_task)


# Delay for attestation plugins in milliseconds (2 minutes)
# This allows time for external systems (e.g., GitHub) to process attestations
# before we attempt to verify them.
ATTESTATION_DELAY_MS = 120_000


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

    Attestation plugins are delayed by ATTESTATION_DELAY_MS to allow external
    systems (e.g., GitHub) time to process attestations before verification.

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
    from ..sdk.enums import AssessmentCategory

    # Get team settings
    try:
        settings = TeamPluginSettings.objects.get(team_id=team_id)
        enabled_plugins = settings.enabled_plugins or []
    except TeamPluginSettings.DoesNotExist:
        # No settings configured, no plugins to run
        logger.debug(f"[PLUGIN] No settings for team {team_id}, skipping assessments")
        return []

    # Filter to only enabled plugins in the registry and get their categories
    available_plugins = {
        p.name: p.category
        for p in RegisteredPlugin.objects.filter(
            is_enabled=True,
            name__in=enabled_plugins,
        )
    }

    enqueued = []
    for plugin_name in enabled_plugins:
        if plugin_name not in available_plugins:
            logger.warning(f"[PLUGIN] Plugin '{plugin_name}' enabled for team {team_id} but not available in registry")
            continue

        # Get plugin-specific config if any
        plugin_config = settings.get_plugin_config(plugin_name)

        # Apply delay for attestation plugins to allow external systems to process
        plugin_category = available_plugins[plugin_name]
        delay_ms = ATTESTATION_DELAY_MS if plugin_category == AssessmentCategory.ATTESTATION.value else None

        enqueue_assessment(
            sbom_id=sbom_id,
            plugin_name=plugin_name,
            run_reason=run_reason,
            config=plugin_config or None,
            triggered_by_user=triggered_by_user,
            triggered_by_token=triggered_by_token,
            delay_ms=delay_ms,
        )
        enqueued.append(plugin_name)

    logger.info(f"[PLUGIN] Enqueued {len(enqueued)} assessments for SBOM {sbom_id}: {enqueued}")

    return enqueued


@dramatiq.actor(
    queue_name="plugins",
    max_retries=1,
    time_limit=600000,  # 10 minutes for large teams
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def enqueue_assessments_for_existing_sboms_task(
    team_id: str,
    enabled_plugins: list[str],
    plugin_configs: dict | None = None,
    cutoff_hours: int = BACKFILL_CUTOFF_HOURS,
) -> dict[str, Any]:
    """Background task to enqueue assessments for existing SBOMs when plugins are enabled.

    This task runs in a worker process, not the web server, so it won't block
    HTTP requests. It handles the bulk work of:
    1. Querying SBOMs within the cutoff period
    2. Checking which SBOMs already have assessment runs
    3. Enqueueing individual assessment tasks for SBOMs that need them

    Args:
        team_id: The team's primary key.
        enabled_plugins: List of plugin names that are enabled.
        plugin_configs: Optional plugin-specific configuration overrides.
        cutoff_hours: Only assess SBOMs created within this many hours (default: 24).

    Returns:
        Dictionary with task results:
        - team_id: The team ID that was processed
        - sboms_found: Number of SBOMs found within the cutoff period
        - assessments_enqueued: Total number of assessment tasks enqueued
        - plugins_processed: List of plugins that were processed
    """
    # Imports inside function to avoid circular imports at module load time
    from sbomify.apps.sboms.models import SBOM, Component
    from sbomify.apps.teams.models import Team

    from ..models import AssessmentRun, RegisteredPlugin
    from ..sdk.enums import AssessmentCategory

    logger.info(
        f"[TASK_bulk_enqueue] Starting bulk assessment enqueuing for team {team_id}. "
        f"Plugins: {enabled_plugins}, cutoff: {cutoff_hours}h"
    )

    # Ensure database connection is fresh
    connection.ensure_connection()

    try:
        # Look up the team
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.error(f"[TASK_bulk_enqueue] Team {team_id} not found")
            return {
                "team_id": team_id,
                "error": "Team not found",
                "sboms_found": 0,
                "assessments_enqueued": 0,
                "plugins_processed": [],
            }

        # Calculate cutoff time
        cutoff_time = timezone.now() - timedelta(hours=cutoff_hours)

        # Query SBOMs within the cutoff period
        sboms = list(
            SBOM.objects.filter(
                component__team=team,
                component__component_type=Component.ComponentType.SBOM,
                created_at__gte=cutoff_time,
            ).select_related("component")
        )
        sbom_ids = [sbom.id for sbom in sboms]

        logger.info(
            f"[TASK_bulk_enqueue] Found {len(sboms)} SBOMs for team {team.key} created within last {cutoff_hours} hours"
        )

        if not sbom_ids:
            logger.debug(f"[TASK_bulk_enqueue] No recent SBOMs found for team {team.key}")
            return {
                "team_id": team_id,
                "sboms_found": 0,
                "assessments_enqueued": 0,
                "plugins_processed": enabled_plugins,
            }

        # Fetch all existing assessment runs for these SBOMs and enabled plugins
        existing_runs = {
            (run["sbom_id"], run["plugin_name"])
            for run in AssessmentRun.objects.filter(
                sbom_id__in=sbom_ids,
                plugin_name__in=enabled_plugins,
            ).values("sbom_id", "plugin_name")
        }

        # Get plugin categories for delay calculation
        available_plugins = {
            p.name: p.category
            for p in RegisteredPlugin.objects.filter(
                is_enabled=True,
                name__in=enabled_plugins,
            )
        }

        plugin_configs = plugin_configs or {}
        enqueued_count = 0

        for sbom in sboms:
            # Check which enabled plugins don't have runs for this SBOM
            plugins_needing_runs = [
                plugin
                for plugin in enabled_plugins
                if (sbom.id, plugin) not in existing_runs and plugin in available_plugins
            ]

            if not plugins_needing_runs:
                continue

            # Enqueue assessments for plugins that need runs
            for plugin_name in plugins_needing_runs:
                plugin_config = plugin_configs.get(plugin_name)
                plugin_category = available_plugins.get(plugin_name)

                # Apply delay for attestation plugins
                delay_ms = ATTESTATION_DELAY_MS if plugin_category == AssessmentCategory.ATTESTATION.value else None

                enqueue_assessment(
                    sbom_id=str(sbom.id),
                    plugin_name=plugin_name,
                    run_reason=RunReason.CONFIG_CHANGE,
                    config=plugin_config,
                    delay_ms=delay_ms,
                )
                enqueued_count += 1

        logger.info(
            f"[TASK_bulk_enqueue] Completed for team {team.key}: "
            f"enqueued {enqueued_count} assessments across {len(sboms)} SBOMs"
        )

        return {
            "team_id": team_id,
            "sboms_found": len(sboms),
            "assessments_enqueued": enqueued_count,
            "plugins_processed": enabled_plugins,
        }

    except Exception as e:
        logger.exception(f"[TASK_bulk_enqueue] Unexpected error for team {team_id}: {e}")
        return {
            "team_id": team_id,
            "error": str(e),
            "sboms_found": 0,
            "assessments_enqueued": 0,
            "plugins_processed": [],
        }


# --- Scheduled OSV scanning tasks ---
# These tasks run release-centric scans with plan-based cadence:
# - Community teams: weekly (Sundays at 2 AM)
# - Business/Enterprise teams: daily (at 2 AM)


@cron("0 2 * * Sun")  # Weekly on Sundays at 2 AM
@dramatiq.actor(
    queue_name="plugins",
    max_retries=2,
    time_limit=3600000,  # 1 hour
    store_results=True,
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_delay(120),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def weekly_osv_scan_task() -> dict[str, Any]:
    """Weekly OSV vulnerability scan for Community teams.

    Scans all SBOMs in releases and latest component SBOMs for teams
    on the Community plan (or no billing plan). Skips SBOMs that already
    have a recent OSV assessment run (within 7 days).

    Returns:
        Dictionary with scan statistics.
    """
    logger.info("[TASK_weekly_osv_scan] Starting weekly OSV scan for Community teams")
    return _run_scheduled_osv_scans(
        plan_filter=_is_community_team,
        skip_hours=168,  # 7 days
        task_name="weekly_osv_scan",
    )


@cron("0 2 * * *")  # Daily at 2 AM
@dramatiq.actor(
    queue_name="plugins",
    max_retries=2,
    time_limit=3600000,  # 1 hour
    store_results=True,
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_delay(120),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def daily_osv_scan_task() -> dict[str, Any]:
    """Daily OSV vulnerability scan for Business/Enterprise teams.

    Scans all SBOMs in releases and latest component SBOMs for teams
    on Business or Enterprise plans. Skips SBOMs that already have
    a recent OSV assessment run (within 24 hours).

    Returns:
        Dictionary with scan statistics.
    """
    logger.info("[TASK_daily_osv_scan] Starting daily OSV scan for Business/Enterprise teams")
    return _run_scheduled_osv_scans(
        plan_filter=_is_paid_team,
        skip_hours=24,
        task_name="daily_osv_scan",
    )


def _is_community_team(team) -> bool:
    """Check if team is on Community plan (or no plan)."""
    return not team.billing_plan or team.billing_plan == "community"


def _is_paid_team(team) -> bool:
    """Check if team is on a paid plan (Business or Enterprise)."""
    return team.billing_plan in ("business", "enterprise")


def _run_scheduled_osv_scans(
    plan_filter: Callable[..., bool],
    skip_hours: int,
    task_name: str,
) -> dict[str, Any]:
    """Shared logic for scheduled OSV scans.

    Queries all releases with SBOMs and latest component SBOMs,
    filters teams by billing plan, and enqueues OSV assessments.

    Args:
        plan_filter: Callable that takes a team and returns True if it
            should be included in this scan cadence.
        skip_hours: Skip SBOMs with a recent OSV assessment run within
            this many hours.
        task_name: Name for logging.

    Returns:
        Dictionary with scan statistics.
    """
    from sbomify.apps.core.models import ReleaseArtifact
    from sbomify.apps.sboms.models import SBOM

    from ..models import AssessmentRun

    connection.ensure_connection()

    stats: dict[str, Any] = {
        "status": "completed",
        "teams_scanned": 0,
        "sboms_found": 0,
        "assessments_enqueued": 0,
        "skipped_recent": 0,
        "skipped_team_filter": 0,
    }

    try:
        # Collect unique SBOMs from releases (all releases with SBOMs)
        sboms_to_scan: dict[str, tuple[SBOM, str]] = {}  # sbom_id -> (sbom, source)

        release_artifacts = (
            ReleaseArtifact.objects.filter(sbom__isnull=False)
            .select_related("sbom__component__team", "release__product")
            .only(
                "sbom__id",
                "sbom__component__team__id",
                "sbom__component__team__billing_plan",
                "sbom__component__team__key",
                "release__product__name",
                "release__name",
            )
        )

        for artifact in release_artifacts:
            sbom = artifact.sbom
            team = sbom.component.team

            if not plan_filter(team):
                stats["skipped_team_filter"] += 1
                continue

            if sbom.id not in sboms_to_scan:
                sboms_to_scan[sbom.id] = (sbom, "release")

        # Also include latest SBOM per component (for component-view coverage)
        from sbomify.apps.sboms.models import Component

        components = Component.objects.filter(
            component_type=Component.ComponentType.SBOM,
        ).select_related("team")

        for component in components:
            team = component.team
            if not plan_filter(team):
                continue

            latest_sbom = component.latest_sbom
            if latest_sbom and latest_sbom.id not in sboms_to_scan:
                sboms_to_scan[latest_sbom.id] = (latest_sbom, "component_latest")

        stats["sboms_found"] = len(sboms_to_scan)

        if not sboms_to_scan:
            logger.info(f"[TASK_{task_name}] No SBOMs found for scanning")
            return stats

        # Check for recent assessment runs to skip
        cutoff = timezone.now() - timedelta(hours=skip_hours)
        recent_run_sbom_ids = set(
            AssessmentRun.objects.filter(
                plugin_name="osv",
                sbom_id__in=list(sboms_to_scan.keys()),
                created_at__gte=cutoff,
                status__in=["completed", "running", "pending"],
            ).values_list("sbom_id", flat=True)
        )

        # Track unique teams
        teams_seen: set[str] = set()

        for sbom_id, (sbom, source) in sboms_to_scan.items():
            if sbom_id in recent_run_sbom_ids:
                stats["skipped_recent"] += 1
                continue

            team = sbom.component.team
            teams_seen.add(team.key)

            enqueue_assessment(
                sbom_id=str(sbom_id),
                plugin_name="osv",
                run_reason=RunReason.SCHEDULED_REFRESH,
            )
            stats["assessments_enqueued"] += 1

        stats["teams_scanned"] = len(teams_seen)

        logger.info(
            f"[TASK_{task_name}] Completed: {stats['assessments_enqueued']} assessments enqueued "
            f"across {stats['teams_scanned']} teams, {stats['skipped_recent']} skipped (recent)"
        )

        return stats

    except Exception as e:
        logger.exception(f"[TASK_{task_name}] Failed: {e}")
        return {**stats, "status": "failed", "error": str(e)}


# --- Scheduled Dependency Track scanning task ---


@cron("0 * * * *")  # Hourly at minute 0
@dramatiq.actor(
    queue_name="plugins",
    max_retries=2,
    time_limit=3600000,  # 1 hour
    store_results=True,
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_delay(120),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def hourly_dt_scan_task() -> dict[str, Any]:
    """Hourly DT vulnerability scan for Business/Enterprise teams.

    Enqueues DT plugin assessments for all releases with SBOMs where
    the team uses Dependency Track. Skips recently-assessed SBOMs
    (within 1 hour).

    Returns:
        Dictionary with scan statistics.
    """
    from sbomify.apps.core.models import ReleaseArtifact
    from sbomify.apps.sboms.models import SBOM

    from ..models import AssessmentRun, TeamPluginSettings

    logger.info("[TASK_hourly_dt_scan] Starting hourly DT scan for Business/Enterprise teams")

    connection.ensure_connection()

    stats: dict[str, Any] = {
        "status": "completed",
        "teams_scanned": 0,
        "sboms_found": 0,
        "assessments_enqueued": 0,
        "skipped_recent": 0,
        "skipped_non_cyclonedx": 0,
    }

    try:
        # Find teams with DT plugin enabled and paid plans
        dt_team_configs: dict[str, dict] = {}  # team_id -> plugin_config
        for settings in TeamPluginSettings.objects.filter(
            team__billing_plan__in=["business", "enterprise"],
        ).select_related("team"):
            if settings.is_plugin_enabled("dependency-track"):
                dt_team_configs[settings.team_id] = settings.get_plugin_config("dependency-track")

        if not dt_team_configs:
            logger.info("[TASK_hourly_dt_scan] No teams with DT enabled")
            return stats

        dt_team_ids = set(dt_team_configs.keys())

        # Collect SBOMs from releases for these teams
        sboms_to_scan: dict[str, tuple[SBOM, str]] = {}

        release_artifacts = ReleaseArtifact.objects.filter(
            sbom__isnull=False,
            sbom__component__team_id__in=dt_team_ids,
        ).select_related("sbom__component__team", "release__product")

        for artifact in release_artifacts:
            sbom = artifact.sbom
            if sbom.id not in sboms_to_scan:
                sboms_to_scan[sbom.id] = (sbom, "release")

        stats["sboms_found"] = len(sboms_to_scan)
        stats["teams_scanned"] = len(dt_team_ids)

        if not sboms_to_scan:
            logger.info("[TASK_hourly_dt_scan] No SBOMs found for DT scanning")
            return stats

        # Check for recent DT assessment runs to skip (within 1 hour)
        cutoff = timezone.now() - timedelta(hours=1)
        recent_run_sbom_ids = set(
            AssessmentRun.objects.filter(
                plugin_name="dependency-track",
                sbom_id__in=list(sboms_to_scan.keys()),
                created_at__gte=cutoff,
                status__in=["completed", "running", "pending"],
            ).values_list("sbom_id", flat=True)
        )

        for sbom_id, (sbom, source) in sboms_to_scan.items():
            if sbom_id in recent_run_sbom_ids:
                stats["skipped_recent"] += 1
                continue

            # DT only supports CycloneDX — skip SPDX and other formats
            if getattr(sbom, "format", None) != "cyclonedx":
                stats["skipped_non_cyclonedx"] += 1
                continue

            # Pass team's plugin config for DT server selection
            team_id = sbom.component.team_id
            plugin_config = dt_team_configs.get(team_id) or None

            enqueue_assessment(
                sbom_id=str(sbom_id),
                plugin_name="dependency-track",
                run_reason=RunReason.SCHEDULED_REFRESH,
                config=plugin_config,
            )
            stats["assessments_enqueued"] += 1

        logger.info(
            f"[TASK_hourly_dt_scan] Completed: {stats['assessments_enqueued']} DT assessments enqueued "
            f"across {stats['teams_scanned']} teams, {stats['skipped_recent']} skipped (recent), "
            f"{stats['skipped_non_cyclonedx']} skipped (non-CycloneDX)"
        )

        return stats

    except Exception as e:
        logger.exception(f"[TASK_hourly_dt_scan] Failed: {e}")
        return {**stats, "status": "failed", "error": str(e)}
