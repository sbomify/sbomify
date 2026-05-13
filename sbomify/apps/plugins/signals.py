"""Signal handlers for the plugins app."""

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.apps.plugins.tasks import enqueue_assessment, enqueue_assessments_for_existing_sboms_task
from sbomify.logging import getLogger

from .models import AssessmentRun, TeamPluginSettings
from .sdk.enums import RunReason, RunStatus

logger = getLogger(__name__)


@receiver(post_save, sender=TeamPluginSettings)
def trigger_assessments_for_existing_sboms(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Trigger assessments for recent SBOMs when plugins are enabled.

    When plugins are enabled for a team, this signal dispatches a background
    task to assess recent SBOMs (within the last 24 hours by default).

    The actual work of querying SBOMs and enqueueing assessments is done in
    a background Dramatiq task to avoid blocking the web server.

    To avoid unnecessary work, this handler only runs when:
    - The instance is created with plugins enabled, or
    - An update explicitly touches the ``enabled_plugins`` field.
    """
    # Determine the current set of enabled plugins
    enabled_plugins = instance.enabled_plugins or []

    if created:
        # On creation, only proceed if plugins are actually enabled
        if not enabled_plugins:
            # No plugins enabled on creation, nothing to do
            return
    else:
        # On update, only proceed if enabled_plugins may have changed
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "enabled_plugins" not in update_fields:
            # enabled_plugins was not part of this update, nothing to do
            return
        if not enabled_plugins:
            # Plugins have been disabled or are empty, nothing to do
            return

    # Dispatch a background task to handle the bulk work
    # This ensures the web request returns immediately without blocking

    try:
        team = instance.team
        team_id = str(team.id)
        team_key = team.key  # Capture primitive values for safe use in the deferred on-commit callback
        plugin_configs = instance.plugin_configs or {}

        logger.info(
            f"Plugins enabled for team {team_key} ({team_id}). "
            f"Dispatching background task to assess recent SBOMs. Enabled plugins: {enabled_plugins}"
        )

        def _dispatch_bulk_task() -> None:
            enqueue_assessments_for_existing_sboms_task.send(
                team_id=team_id,
                enabled_plugins=enabled_plugins,
                plugin_configs=plugin_configs,
            )
            logger.debug(f"Dispatched bulk assessment task for team {team_key}")

        # Defer until transaction commits to ensure settings are saved
        run_on_commit(_dispatch_bulk_task)

    except AttributeError as e:
        # Missing required attribute (e.g., instance.team doesn't exist)
        team_id = getattr(instance, "team_id", None) or "unknown"
        logger.error(
            f"Missing required attribute when triggering assessments for team {team_id}: {e}",
            exc_info=True,
        )
    except Exception as e:
        # Unexpected error
        team_id = getattr(instance, "team_id", None) or "unknown"
        logger.error(
            f"Unexpected error triggering assessments for existing SBOMs for team {team_id}: {e}",
            exc_info=True,
        )


def enqueue_dependents_for_completion(run: AssessmentRun) -> None:
    """Re-fire dependent plugins when an upstream completes.

    Closes the BSI ↔ sbom-verification race: ``BSI.scan_mode == ONE_SHOT``,
    so it runs immediately on upload and never refreshes — but
    ``sbom-verification`` (attestation-category) is delayed by
    ``ATTESTATION_DELAY_MS`` (currently 120 s) so it doesn't finish until
    well after BSI has already evaluated ``_check_one_of`` against zero
    completed attestation runs. BSI's stored *"No attestation plugin has
    been run for this SBOM"* finding then sits frozen forever.

    The handler is exposed as a module-level helper (rather than only
    living inside the post_save receiver) so completion paths that bypass
    Django signals — notably ``PluginOrchestrator.finalize_retry_exhausted``
    which writes ``status=COMPLETED`` via ``QuerySet.update()`` — can
    still cascade dependents by calling this directly.

    Logic:

    1. Resolve the SBOM's team and read ``TeamPluginSettings`` —
       ``RegisteredPlugin.is_enabled`` is the *global* switch, but a
       team's actual scan set is ``settings.enabled_plugins``. Restricting
       candidates to that intersection prevents a re-enqueue for plugins
       a team has explicitly opted out of.
    2. Look up every dependent in that intersection whose ``dependencies``
       JSON references the just-completed plugin's *category* or *name*.
    3. For each dependent, find its latest run on the same SBOM
       (any status). Three skip conditions:

       a. PENDING/RUNNING latest → a refresh is already in flight,
          don't double-queue.
       b. No run at all → ON_UPLOAD's enqueue is already in the queue,
          don't compete.
       c. COMPLETED with ``completed_at >= upstream.completed_at`` →
          dependent already saw an at-least-as-fresh snapshot, no
          refresh needed (also prevents ping-pong loops when the
          dependent's own completion fires this handler).

    4. Surviving dependents are enqueued with ``RunReason.DEPENDENCY_CHANGED``
       and the team's stored ``plugin_config`` for that plugin (so the
       refresh runs with the same overrides as a normal scan).
    """
    if run.status != RunStatus.COMPLETED.value:
        return
    if not run.completed_at:
        return

    # Defer the dependent enqueue to ``on_commit`` so the just-saved row is
    # visible to the dependents' workers. Avoids a race where the dependent
    # re-runs and queries for the upstream that hasn't been committed yet.
    sbom_id = str(run.sbom_id)
    upstream_plugin_name = run.plugin_name
    upstream_category = run.category
    upstream_completed_at = run.completed_at

    # Resolve the SBOM's team eagerly while ``run.sbom`` is in scope so the
    # deferred closure doesn't have to re-traverse the relation.
    try:
        team_id = run.sbom.component.team_id
    except Exception:
        logger.warning(
            f"[DEPENDENCY_TRIGGER] Could not resolve team for SBOM {sbom_id}; skipping dependent re-fire",
            exc_info=True,
        )
        return

    def _enqueue_dependents() -> None:
        from .models import RegisteredPlugin, TeamPluginSettings

        team_settings = (
            TeamPluginSettings.objects.filter(team_id=team_id).only("enabled_plugins", "plugin_configs").first()
        )
        team_enabled_plugins = list((team_settings.enabled_plugins if team_settings else None) or [])
        if not team_enabled_plugins:
            # The team has opted out of all plugins — nothing to refresh.
            return

        candidates = RegisteredPlugin.objects.filter(is_enabled=True, name__in=team_enabled_plugins).exclude(
            name=upstream_plugin_name
        )

        dependents: list[str] = []
        for plugin in candidates:
            deps = plugin.dependencies or {}
            clauses = list(deps.get("requires_one_of", [])) + list(deps.get("requires_all", []))
            for clause in clauses:
                ctype = clause.get("type")
                cvalue = clause.get("value")
                if (ctype == "category" and cvalue == upstream_category) or (
                    ctype == "plugin" and cvalue == upstream_plugin_name
                ):
                    dependents.append(plugin.name)
                    break

        if not dependents:
            return

        for dep_name in dependents:
            latest = (
                AssessmentRun.objects.filter(sbom_id=sbom_id, plugin_name=dep_name)
                .only("plugin_name", "status", "completed_at")
                .order_by("-created_at")
                .first()
            )
            # If the dependent has never been queued, ON_UPLOAD already
            # owns the first run; don't compete with that enqueue.
            if latest is None:
                continue
            # In-flight refresh wins — a PENDING/RUNNING run will pick
            # up the newly-completed upstream when it executes, so
            # don't queue another redundant task.
            if latest.status in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
                continue
            # Skip when the dependent's last completion is at least as
            # fresh as ours (handles the dependent-completes-after-us
            # ping-pong case naturally).
            if (
                latest.status == RunStatus.COMPLETED.value
                and latest.completed_at
                and latest.completed_at >= upstream_completed_at
            ):
                continue

            plugin_config = team_settings.get_plugin_config(dep_name) if team_settings is not None else None

            logger.info(
                f"[DEPENDENCY_TRIGGER] Re-enqueueing {dep_name} on SBOM {sbom_id} "
                f"because upstream {upstream_plugin_name} (category={upstream_category}) "
                f"completed at {upstream_completed_at.isoformat()} "
                f"(dependent's latest status={latest.status}, "
                f"completed_at={latest.completed_at.isoformat() if latest.completed_at else 'n/a'})"
            )
            try:
                enqueue_assessment(
                    sbom_id=sbom_id,
                    plugin_name=dep_name,
                    run_reason=RunReason.DEPENDENCY_CHANGED,
                    config=plugin_config or None,
                )
            except Exception:
                # Re-firing dependents is a best-effort UX refresh — log and
                # carry on rather than letting a single dependent's enqueue
                # failure block the upstream's completion path.
                logger.warning(
                    f"[DEPENDENCY_TRIGGER] Failed to enqueue dependent {dep_name} for SBOM {sbom_id}",
                    exc_info=True,
                )

    run_on_commit(_enqueue_dependents)


@receiver(post_save, sender=AssessmentRun)
def trigger_dependents_on_completion(
    sender: Any, instance: AssessmentRun, created: bool, update_fields: Any = None, **kwargs: Any
) -> None:
    """Wire ``post_save`` on AssessmentRun into the dependent-trigger helper.

    The helper itself is reusable from non-signal paths (e.g.
    ``finalize_retry_exhausted``'s ``QuerySet.update()`` write that
    bypasses ``post_save``).
    """
    enqueue_dependents_for_completion(instance)
