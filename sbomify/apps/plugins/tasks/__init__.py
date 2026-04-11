"""Dramatiq tasks for the plugin framework.

This module provides async task definitions for running assessments
in the background using Dramatiq workers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any, TypedDict

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

    def cron(schedule: str) -> Callable[..., Any]:
        """Fallback decorator when dramatiq-crontab is not installed."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator


from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import broadcast_to_workspace, push_notification
from sbomify.task_utils import format_task_error

from ..orchestrator import PluginOrchestrator, PluginOrchestratorError
from ..sdk.base import RetryLaterError
from ..sdk.enums import RunReason, ScanMode

logger = logging.getLogger(__name__)


class _PluginInfo(TypedDict):
    """Registry snapshot row used by enqueue_assessments_for_sbom."""

    category: str


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
    config: dict[str, Any] | None = None,
    triggered_by_user_id: int | None = None,
    triggered_by_token_id: str | None = None,
    release_id: str | None = None,
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
        release_id: Optional ID of the triggering Release. Passed as an
            informational hint via SBOMContext.release_id (not persisted on
            AssessmentRun — releases use the M2M populated at completion).
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
                    release_id=release_id,
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
            retry_error = retry_later_info["error"]

            if _retry_later_count < len(RETRY_LATER_DELAYS_MS):
                delay_ms = RETRY_LATER_DELAYS_MS[_retry_later_count]
                logger.info(
                    f"[TASK_run_assessment] Transient condition for SBOM {sbom_id} "
                    f"(run: {run_id or 'unknown'}): {retry_error}. "
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
                    "release_id": release_id,
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
                    "error": str(retry_error),
                    "message": (
                        "Assessment could not complete after multiple retries. "
                        "The transient condition may have become permanent. "
                        f"Last error: {retry_error}"
                    ),
                }
                if run_id is not None:
                    response["assessment_run_id"] = run_id
                return response

        # If the plugin skipped this artifact (unsupported bom_type), return early
        if assessment_run is None:
            return {
                "status": "skipped",
                "plugin_name": plugin_name,
                "message": f"Plugin '{plugin_name}' does not support this artifact's bom_type",
            }

        logger.info(
            f"[TASK_run_assessment] Completed assessment run {assessment_run.id} with status {assessment_run.status}"
        )

        # Broadcast assessment completion to workspace for real-time UI updates
        try:
            workspace_key: str = assessment_run.sbom.component.team.key or ""

            from sbomify.apps.core.posthog_service import capture

            capture(
                workspace_key or "system",
                "vulnerability_scan:completed",
                {"sbom_id": sbom_id, "plugin": plugin_name, "status": assessment_run.status},
                groups={"workspace": workspace_key} if workspace_key else None,
            )

            if not workspace_key:
                logger.debug("[TASK_run_assessment] Skipping broadcast/notification — no workspace key")
            else:
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
                        action_url=f"/component/{assessment_run.sbom.component.id}/",
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
    config: dict[str, Any] | None = None,
    triggered_by_user: User | None = None,
    triggered_by_token: AccessToken | None = None,
    delay_ms: int | None = None,
    release_id: str | None = None,
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
        release_id: Optional ID of the triggering Release. Passed as an
            informational hint via SBOMContext.release_id (not persisted on
            AssessmentRun — releases use the M2M populated at completion).

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
    task_release_id = release_id

    def _send_task() -> None:
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
                "release_id": task_release_id,
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

    from sbomify.apps.core.posthog_service import capture

    def _capture_scan_initiated() -> None:
        """Resolve workspace after transaction commits and capture the event."""
        groups: dict[str, str] | None = None
        distinct_id = "system"
        try:
            from sbomify.apps.sboms.models import SBOM as SBOMModel

            sbom = SBOMModel.objects.select_related("component__team").filter(pk=task_sbom_id).first()
            if sbom and sbom.component and sbom.component.team and sbom.component.team.key:
                workspace_key: str = sbom.component.team.key or ""
                groups = {"workspace": workspace_key}
                distinct_id = workspace_key
        except Exception:
            logger.debug("Could not resolve workspace key for SBOM %s", task_sbom_id)
        capture(
            distinct_id,
            "vulnerability_scan:initiated",
            {"sbom_id": task_sbom_id, "plugin": task_plugin_name, "reason": task_run_reason},
            groups=groups,
        )

    transaction.on_commit(_capture_scan_initiated)


# Delay for attestation plugins in milliseconds (2 minutes)
# This allows time for external systems (e.g., GitHub) to process attestations
# before we attempt to verify them.
ATTESTATION_DELAY_MS = 120_000


@dramatiq.actor(
    queue_name="plugins",
    max_retries=3,
    time_limit=120000,  # 2 minutes — lightweight M2M update + optional DT tag PATCH
    store_results=True,
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def attach_release_to_runs_task(sbom_id: str, release_id: str) -> dict[str, Any]:
    """Attach a newly-created release to existing AssessmentRuns for the SBOM.

    Called by the ReleaseArtifact post_save signal handler. Finds the most
    recent completed run per plugin for the given SBOM and adds the release
    to each run's ``releases`` M2M. For plugins that expose a
    ``sync_release_tags`` hook (currently only Dependency Track), the task
    also asks the plugin to update its downstream tag state — e.g. PATCH
    the DT project version's tags so the new release shows up in DT.

    Race (Option A): if no completed run exists yet (the upload-triggered
    scan is still running), this task is a no-op. The orchestrator's
    run-completion step reads the current ReleaseArtifact set and will
    include the just-created row naturally.

    Args:
        sbom_id: The SBOM primary key.
        release_id: The Release primary key to attach.

    Returns:
        {"attached_runs": N, "synced_plugins": [...]}
    """
    connection.ensure_connection()

    from sbomify.apps.core.models import Release

    from ..models import AssessmentRun, AssessmentRunRelease
    from ..sdk.enums import RunStatus

    try:
        release = Release.objects.select_related("product").get(pk=release_id)
    except Release.DoesNotExist:
        logger.debug(
            "[TASK_attach_release] Release %s no longer exists, skipping attach for SBOM %s",
            release_id,
            sbom_id,
        )
        return {"attached_runs": 0, "synced_plugins": []}

    # One run per plugin — latest completed-or-failed wins per plugin_name.
    # Including FAILED runs ensures the M2M is populated even when the last
    # scan failed (e.g. DT server unreachable). Without this, a release
    # added after a failed scan would never get its tags synced until the
    # next successful cron re-scan. Tag sync only runs for COMPLETED runs
    # (see the sync_hook guard below).
    # Prefer COMPLETED over FAILED: if both exist for a plugin, use the
    # COMPLETED one (it has valid DT state to sync). Only fall back to
    # FAILED if no COMPLETED run exists (M2M still gets populated so the
    # next cron re-scan picks up the release).
    latest_run_ids_by_plugin: dict[str, str] = {}
    latest_run_statuses: dict[str, str] = {}
    runs_qs = (
        AssessmentRun.objects.filter(
            sbom_id=sbom_id,
            status__in=[RunStatus.COMPLETED.value, RunStatus.FAILED.value],
        )
        .order_by("plugin_name", "-created_at")
        .values("id", "plugin_name", "status")
    )
    seen_plugins: set[str] = set()
    for row in runs_qs:
        pname = row["plugin_name"]
        if pname in seen_plugins:
            # Already found a run for this plugin; only replace if the
            # existing pick was FAILED and this one is COMPLETED (prefer
            # COMPLETED for tag sync).
            if latest_run_statuses.get(pname) == RunStatus.FAILED.value and row["status"] == RunStatus.COMPLETED.value:
                latest_run_ids_by_plugin[pname] = str(row["id"])
                latest_run_statuses[pname] = row["status"]
            continue
        seen_plugins.add(pname)
        latest_run_ids_by_plugin[pname] = str(row["id"])
        latest_run_statuses[pname] = row["status"]

    if not latest_run_ids_by_plugin:
        logger.debug(
            "[TASK_attach_release] No completed/failed runs for SBOM %s yet; "
            "the in-flight scan will pick up release %s at completion",
            sbom_id,
            release_id,
        )
        return {"attached_runs": 0, "synced_plugins": []}

    # Bulk-create the M2M rows (idempotent via unique_together).
    # ignore_conflicts=True means rows that already exist are skipped silently.
    # Note: bulk_create with ignore_conflicts returns input list regardless of
    # how many were actually inserted, so we count before/after to get the
    # real number of new associations.
    new_associations = [
        AssessmentRunRelease(assessment_run_id=run_id, release_id=release_id)
        for run_id in latest_run_ids_by_plugin.values()
    ]
    with transaction.atomic():
        AssessmentRunRelease.objects.bulk_create(new_associations, ignore_conflicts=True)

    # Continuous plugins maintain release-scoped downstream state (e.g. DT
    # project version tags). Ask them to re-sync after the M2M update, but
    # ONLY for COMPLETED runs — failed runs have no DT project version to
    # tag (the upload never succeeded). The M2M row is still attached so
    # that the next successful scan picks up the release at completion.
    synced: list[str] = []
    for plugin_name, run_id in latest_run_ids_by_plugin.items():
        if latest_run_statuses.get(plugin_name) != RunStatus.COMPLETED.value:
            continue
        try:
            plugin = _load_plugin_by_name(plugin_name)
        except Exception:
            logger.debug(
                "[TASK_attach_release] Plugin %s not loadable, skipping tag sync",
                plugin_name,
            )
            continue
        if plugin.get_metadata().scan_mode == ScanMode.CONTINUOUS:
            try:
                plugin.sync_release_tags(sbom_id=sbom_id, run_id=run_id, release=release)
                synced.append(plugin_name)
            except Exception:
                logger.warning(
                    "[TASK_attach_release] Plugin %s sync_release_tags raised for SBOM %s, "
                    "release %s — M2M row is still attached",
                    plugin_name,
                    sbom_id,
                    release_id,
                    exc_info=True,
                )

    logger.info(
        "[TASK_attach_release] Attached release %s to %d run(s) for SBOM %s, synced plugins: %s",
        release_id,
        len(new_associations),
        sbom_id,
        synced,
    )
    return {"attached_runs": len(new_associations), "synced_plugins": synced}


@dramatiq.actor(
    queue_name="plugins",
    max_retries=3,
    time_limit=120000,
    store_results=True,
)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def detach_release_from_runs_task(sbom_id: str, release_id: str) -> dict[str, Any]:
    """Detach a removed release from AssessmentRuns for an SBOM (Stage 5 Issue A).

    Called by the ReleaseArtifact post_delete signal handler. Removes the
    release from every AssessmentRun M2M for the SBOM and asks each plugin
    that exposes a ``sync_release_tags`` hook to re-push the canonical tag
    set (minus the just-removed release). Uses the same Q2=B "re-read full
    canonical set" semantic as the attach path, so DT tag state converges
    correctly regardless of ordering.

    Args:
        sbom_id: The SBOM primary key.
        release_id: The Release primary key whose association was removed.

    Returns:
        {"detached_runs": N, "synced_plugins": [...]}
    """
    connection.ensure_connection()

    from sbomify.apps.core.models import Release

    from ..models import AssessmentRun, AssessmentRunRelease
    from ..sdk.enums import RunStatus

    # Remove the M2M rows for this (sbom, release) pair across all runs.
    # Note: if the Release itself was deleted, the M2M rows are already
    # gone via CASCADE, so this delete is a no-op in that case.
    with transaction.atomic():
        detached_count, _ = AssessmentRunRelease.objects.filter(
            assessment_run__sbom_id=sbom_id,
            release_id=release_id,
        ).delete()

    if detached_count == 0:
        logger.debug(
            "[TASK_detach_release] No M2M rows to detach for SBOM %s, release %s (already removed or never attached)",
            sbom_id,
            release_id,
        )

    # Find completed runs for this SBOM (one per plugin) whose tag state may
    # now be stale, and ask their plugins to re-sync from the updated M2M.
    latest_run_ids_by_plugin: dict[str, str] = {}
    runs_qs = (
        AssessmentRun.objects.filter(sbom_id=sbom_id, status=RunStatus.COMPLETED.value)
        .order_by("plugin_name", "-created_at")
        .values("id", "plugin_name")
    )
    seen_plugins: set[str] = set()
    for row in runs_qs:
        if row["plugin_name"] in seen_plugins:
            continue
        seen_plugins.add(row["plugin_name"])
        latest_run_ids_by_plugin[row["plugin_name"]] = str(row["id"])

    if not latest_run_ids_by_plugin:
        return {"detached_runs": detached_count, "synced_plugins": []}

    # Resolve a Release object to pass to sync_release_tags. If the release
    # was deleted outright (not just removed from this SBOM), pass None —
    # sync_release_tags re-reads the full canonical set from the M2M and
    # doesn't strictly need the triggering release.
    try:
        release_obj = Release.objects.get(pk=release_id)
    except Release.DoesNotExist:
        release_obj = None  # Release was deleted; canonical set is still valid

    synced: list[str] = []
    for plugin_name, run_id in latest_run_ids_by_plugin.items():
        try:
            plugin = _load_plugin_by_name(plugin_name)
        except Exception:
            logger.debug(
                "[TASK_detach_release] Plugin %s not loadable, skipping tag sync",
                plugin_name,
            )
            continue
        if plugin.get_metadata().scan_mode == ScanMode.CONTINUOUS:
            try:
                plugin.sync_release_tags(sbom_id=sbom_id, run_id=run_id, release=release_obj)
                synced.append(plugin_name)
            except Exception:
                logger.warning(
                    "[TASK_detach_release] Plugin %s sync_release_tags raised for SBOM %s, "
                    "release %s — M2M row is still detached",
                    plugin_name,
                    sbom_id,
                    release_id,
                    exc_info=True,
                )

    logger.info(
        "[TASK_detach_release] Detached release %s from %d M2M row(s) for SBOM %s, synced plugins: %s",
        release_id,
        detached_count,
        sbom_id,
        synced,
    )
    return {"detached_runs": detached_count, "synced_plugins": synced}


def _load_plugin_by_name(plugin_name: str) -> Any:
    """Instantiate a plugin by name from the registry.

    Used by attach/detach tasks to inspect metadata and call lifecycle hooks.
    Returns an instance with default config. Raises on any load failure.
    """
    from ..models import RegisteredPlugin

    plugin_record = RegisteredPlugin.objects.get(name=plugin_name)
    module_path, class_name = plugin_record.plugin_class_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    plugin_class = getattr(module, class_name)
    return plugin_class()


def enqueue_assessments_for_sbom(
    sbom_id: str,
    team_id: str,
    run_reason: RunReason,
    *,
    release_id: str | None = None,
    only_categories: set[str] | None = None,
    triggered_by_user: User | None = None,
    triggered_by_token: AccessToken | None = None,
) -> list[str]:
    """Enqueue all enabled assessments for an SBOM.

    Looks up the team's plugin settings and enqueues tasks for each enabled plugin,
    optionally filtered by category. Tasks are deferred via on_commit so the SBOM
    is visible to workers. Attestation plugins are delayed by ATTESTATION_DELAY_MS
    to give external systems (e.g., GitHub) time to process them.

    Args:
        sbom_id: The SBOM's primary key.
        team_id: The team's primary key.
        run_reason: Why assessments are being triggered.
        release_id: Optional ID of the triggering Release. Passed as an
            informational hint via SBOMContext.release_id. None means "not
            release-scoped" (upload, cron, manual).
        only_categories: Optional set of AssessmentCategory values (as strings)
            to restrict enqueueing. None means run all enabled plugins.
            See sbomify/sbomify#873 and #881.
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
    available_plugins: dict[str, _PluginInfo] = {
        p.name: {"category": p.category}
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

        plugin_info = available_plugins[plugin_name]
        plugin_category = plugin_info["category"]

        # Filter by category when only_categories is specified
        if only_categories is not None and plugin_category not in only_categories:
            continue

        # Get plugin-specific config if any
        plugin_config = settings.get_plugin_config(plugin_name)

        # Apply delay for attestation plugins to allow external systems to process
        delay_ms = ATTESTATION_DELAY_MS if plugin_category == AssessmentCategory.ATTESTATION.value else None

        enqueue_assessment(
            sbom_id=sbom_id,
            plugin_name=plugin_name,
            run_reason=run_reason,
            config=plugin_config or None,
            triggered_by_user=triggered_by_user,
            triggered_by_token=triggered_by_token,
            delay_ms=delay_ms,
            release_id=release_id,
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
    plugin_configs: dict[str, Any] | None = None,
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
                component__component_type=Component.ComponentType.BOM,
                bom_type=SBOM.BomType.SBOM,
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

        # Get plugin categories for filtering and delay calculation
        available_plugins: dict[str, _PluginInfo] = {
            p.name: {"category": p.category}
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
                plugin_info = available_plugins.get(plugin_name)

                plugin_category = plugin_info["category"] if plugin_info else None

                # The backfill skips security category plugins (e.g., dependency-track,
                # osv) because vulnerability scanners need release context and are
                # handled by the scheduled cron tasks. Compliance/attestation plugins
                # are deterministic on SBOM bytes and safe to backfill immediately.
                if plugin_category == AssessmentCategory.SECURITY.value:
                    continue

                plugin_config = plugin_configs.get(plugin_name)

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


# --- Scheduled security plugin scanning tasks ---
# Scan-once-per-SBOM cron scans with plugin- and plan-based cadences:
# - OSV community teams: weekly (Sundays at 2 AM)
# - OSV business/enterprise teams: daily (at 2 AM)
# - DT business/enterprise teams: hourly
# Each SBOM is scanned at most once per skip window, regardless of how many
# releases it is linked to. Release tracking uses the AssessmentRun.releases M2M.


def _is_community_team(team: Any) -> bool:
    """Check if team is on Community plan (or no plan)."""
    return not team.billing_plan or team.billing_plan == "community"


def _is_paid_team(team: Any) -> bool:
    """Check if team is on a paid plan (Business or Enterprise)."""
    return team.billing_plan in ("business", "enterprise")


def _run_scheduled_security_scans(
    plugin_name: str,
    plan_filter: Callable[..., bool],
    skip_hours: int,
    task_name: str,
    only_cyclonedx: bool = False,
) -> dict[str, Any]:
    """Generic helper for scheduled security plugin scans (scan-once-per-SBOM).

    Iterates unique SBOMs (with at least one ReleaseArtifact) for teams with the
    plugin enabled and matching the billing-plan filter. Enqueues one assessment
    per SBOM unless a recent AssessmentRun exists within the skip window. Release
    tracking is handled by the AssessmentRun.releases M2M at scan completion.

    Args:
        plugin_name: Registered plugin slug (e.g. "osv", "dependency-track").
        plan_filter: Callable(team) -> bool selecting teams for this cadence.
        skip_hours: Skip SBOMs scanned within this many hours.
        task_name: Short label used in log messages.
        only_cyclonedx: If True, restrict to CycloneDX SBOMs (required for DT).

    Returns:
        Dictionary with scan statistics.
    """
    from sbomify.apps.sboms.models import SBOM

    from ..models import AssessmentRun, TeamPluginSettings

    logger.info(f"[TASK_{task_name}] Starting {plugin_name} scan")
    connection.ensure_connection()

    stats: dict[str, Any] = {
        "status": "completed",
        "plugin_name": plugin_name,
        "teams_scanned": 0,
        "sboms_found": 0,
        "assessments_enqueued": 0,
        "skipped_recent": 0,
    }

    try:
        # Find teams with this plugin enabled, filtered by billing plan.
        team_configs: dict[int, dict[str, Any]] = {}
        for settings_obj in TeamPluginSettings.objects.select_related("team"):
            if not settings_obj.is_plugin_enabled(plugin_name):
                continue
            if not plan_filter(settings_obj.team):
                continue
            team_configs[settings_obj.team_id] = settings_obj.get_plugin_config(plugin_name) or {}

        if not team_configs:
            logger.info(f"[TASK_{task_name}] No teams with {plugin_name} enabled")
            return stats

        team_ids = set(team_configs.keys())
        stats["teams_scanned"] = len(team_ids)

        # Recent-run dedup: unique sbom_ids already scanned by this plugin
        # within the skip window. Scan-once-per-SBOM model — we no longer
        # dedup per (sbom, release) pair because one scan covers all the
        # SBOM's current releases via the AssessmentRun.releases M2M.
        cutoff = timezone.now() - timedelta(hours=skip_hours)
        recent_sbom_ids: set[str] = set(
            AssessmentRun.objects.filter(
                plugin_name=plugin_name,
                created_at__gte=cutoff,
                status__in=["completed", "running", "pending"],
                sbom__component__team_id__in=team_ids,
            ).values_list("sbom_id", flat=True)
        )

        # Stream eligible SBOMs directly (not ReleaseArtifact rows). Any SBOM
        # with at least one ReleaseArtifact link is eligible — the scan will
        # cover all of its current releases via the M2M populated at run
        # completion. Uses Exists() on ReleaseArtifact rather than a reverse
        # accessor join to keep the query small and avoid name-coupling.
        from django.db.models import Exists, OuterRef

        from sbomify.apps.core.models import ReleaseArtifact

        sbom_qs = (
            SBOM.objects.filter(
                bom_type=SBOM.BomType.SBOM,
                component__team_id__in=team_ids,
            )
            .annotate(
                has_release_artifact=Exists(
                    ReleaseArtifact.objects.filter(
                        sbom_id=OuterRef("pk"),
                        # Defense-in-depth: only count same-team release artifacts
                        release__product__team_id=OuterRef("component__team_id"),
                    )
                )
            )
            .filter(has_release_artifact=True)
            .values("id", "component__team_id", "format")
            .distinct()
        )

        if only_cyclonedx:
            sbom_qs = sbom_qs.filter(format="cyclonedx")

        for sbom_row in sbom_qs.iterator(chunk_size=500):
            stats["sboms_found"] += 1
            sbom_id_str = str(sbom_row["id"])

            if sbom_id_str in recent_sbom_ids:
                stats["skipped_recent"] += 1
                continue

            team_id = sbom_row["component__team_id"]
            plugin_config = team_configs.get(team_id) or None

            enqueue_assessment(
                sbom_id=sbom_id_str,
                plugin_name=plugin_name,
                run_reason=RunReason.SCHEDULED_REFRESH,
                config=plugin_config,
            )
            stats["assessments_enqueued"] += 1

        logger.info(
            "[TASK_%s] Completed: %d %s assessments enqueued across %d teams, %d skipped (recent)",
            task_name,
            stats["assessments_enqueued"],
            plugin_name,
            stats["teams_scanned"],
            stats["skipped_recent"],
        )
        return stats

    except Exception as e:
        logger.exception(f"[TASK_{task_name}] Failed: {e}")
        return {**stats, "status": "failed", "error": str(e)}


@cron("0 2 * * Sun")  # type: ignore[untyped-decorator]  # Weekly on Sundays at 2 AM
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

    Scans eligible SBOMs (with at least one release association) for Community-plan
    teams. Skips SBOMs with an OSV run within 7 days.

    Returns:
        Dictionary with scan statistics.
    """
    return _run_scheduled_security_scans(
        plugin_name="osv",
        plan_filter=_is_community_team,
        skip_hours=168,  # 7 days
        task_name="weekly_osv_scan",
    )


@cron("0 2 * * *")  # type: ignore[untyped-decorator]  # Daily at 2 AM
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

    Scans eligible SBOMs (with at least one release association) for paid teams.
    Skips SBOMs with an OSV run within 24 hours.

    Returns:
        Dictionary with scan statistics.
    """
    return _run_scheduled_security_scans(
        plugin_name="osv",
        plan_filter=_is_paid_team,
        skip_hours=24,
        task_name="daily_osv_scan",
    )


# --- Scheduled Dependency Track scanning task ---


@cron("0 * * * *")  # type: ignore[untyped-decorator]  # Hourly at minute 0
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

    Scans eligible CycloneDX SBOMs (with at least one release association) for paid
    teams with DT enabled. Skips SBOMs with a DT run within 1 hour.

    Returns:
        Dictionary with scan statistics.
    """
    return _run_scheduled_security_scans(
        plugin_name="dependency-track",
        plan_filter=_is_paid_team,
        skip_hours=1,
        task_name="hourly_dt_scan",
        only_cyclonedx=True,
    )
