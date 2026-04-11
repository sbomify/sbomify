from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


@receiver(post_save, sender="core.ReleaseArtifact")
def attach_release_to_existing_runs(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Attach a newly-created ReleaseArtifact to an existing scan, no rescan.

    Scan-once-per-SBOM model (sbomify/sbomify#873, #881):
      - Each SBOM gets ONE run per plugin (not per release).
      - When a new ReleaseArtifact is created for an already-scanned SBOM,
        we attach the new release to the existing run's ``releases`` M2M
        and ask the plugin to sync any downstream tag state (e.g. DT project
        tags).
      - We do NOT enqueue a new scan. The result from the original scan is
        the correct result for this release because the scan is deterministic
        on SBOM bytes.

    Race handling (user-chosen Option A): if the upload-triggered scan is
    still running when the association is created, we do nothing here. The
    orchestrator's run-completion step reads the current ReleaseArtifact set
    and populates the M2M from scratch — our new association is already
    committed by then, so it gets picked up naturally.

    Defense-in-depth cross-team check is still enforced here (admin/migration
    paths can bypass the API-layer check).
    """
    if not created:
        return
    if instance.sbom_id is None:
        return

    # Intentionally does NOT honor ``_suppress_collection_signals``, matching
    # the detach handler below. That flag is scoped to collection_version
    # bumps on the Release model and is set by ``refresh_latest_artifacts``.
    # When the latest pointer moves from SBOM-A to SBOM-B, the detach fires
    # for the old artifacts and this attach fires for the new ones — both are
    # needed so DT tags stay correct on both SBOMs. Without this, the new
    # SBOM would not get the "latest" tag until the next cron re-scan.
    from sbomify.apps.core.models import Release

    team_id_value = Release.objects.filter(pk=instance.release_id).values_list("product__team_id", flat=True).first()
    if team_id_value is None:
        logger.debug(
            "ReleaseArtifact %s has no reachable release/product/team, skipping M2M attach",
            instance.pk,
        )
        return

    # Defense-in-depth cross-team check. Loads the SBOM's component team via
    # a single values_list query and compares to the release's team. If the
    # chain is unreachable (missing component) or the teams differ, skip
    # with a log entry — we refuse to touch plugin state under a team that
    # doesn't own the SBOM.
    sbom_team_id_value = SBOM.objects.filter(pk=instance.sbom_id).values_list("component__team_id", flat=True).first()
    if sbom_team_id_value is None:
        logger.debug(
            "ReleaseArtifact %s references SBOM %s without a reachable component/team, skipping M2M attach",
            instance.pk,
            instance.sbom_id,
        )
        return
    if sbom_team_id_value != team_id_value:
        logger.warning(
            "ReleaseArtifact %s links release team %s to SBOM %s owned by team %s; skipping M2M attach",
            instance.pk,
            team_id_value,
            instance.sbom_id,
            sbom_team_id_value,
        )
        return

    sbom_id = instance.sbom_id
    artifact_id = instance.pk
    release_id = str(instance.release_id)

    def _attach_to_existing_runs() -> None:
        """Find recent completed runs for this SBOM and attach the new release."""
        try:
            from sbomify.apps.plugins.tasks import attach_release_to_runs_task

            attach_release_to_runs_task.send(sbom_id=str(sbom_id), release_id=release_id)
            logger.debug(
                "Enqueued attach-release task for SBOM %s, release %s (via ReleaseArtifact %s)",
                sbom_id,
                release_id,
                artifact_id,
            )
        except Exception:
            logger.warning(
                "Failed to enqueue attach-release task for SBOM %s (broker may be unavailable)",
                sbom_id,
                exc_info=True,
            )

    run_on_commit(_attach_to_existing_runs)


# License processing task has been removed - functionality moved to native model fields
# License processing is now handled directly during SBOM upload via ComponentLicense model


@receiver(post_save, sender=SBOM)
def trigger_plugin_assessments(sender: type[SBOM], instance: SBOM, created: bool, **kwargs: Any) -> None:
    """Trigger plugin assessments when a new SBOM is created.

    Scan-once-per-SBOM model: enqueues ONE run per (SBOM, plugin) regardless of
    how many releases the SBOM is linked to. The orchestrator reads the current
    ReleaseArtifact set at run completion and populates AssessmentRun.releases
    M2M — the scan covers whatever releases point at the SBOM at that moment.

    Why one call per SBOM instead of per release:
      - A vulnerability scan is deterministic on SBOM bytes. Scanning the same
        bytes N times for N releases produces identical results and wastes DT
        uploads + OSV API calls.
      - Viktor's requirement "v1 and v2 with different component versions must
        both be tracked" still holds: v1 and v2 have different SBOMs, so each
        gets its own independent scan. It's only the "same bytes linked to
        multiple releases" case that gets collapsed into one run.

    Plugin access is controlled by:
    1. Team's enabled_plugins in TeamPluginSettings
    2. Plugin's global is_enabled flag in RegisteredPlugin
    3. Billing plan restrictions (enforced when enabling plugins)
    """
    if not created:
        return

    try:
        team = instance.component.team
    except AttributeError:
        logger.debug(f"SBOM {instance.id} has no component.team, skipping plugin assessments")
        return

    try:
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

        logger.info(f"Triggering plugin assessments for SBOM {instance.id} (team: {team.key})")

        sbom_id = instance.id
        team_id = str(team.id)

        def _enqueue_assessments() -> None:
            try:
                # One enqueue call per SBOM. No category filter — all enabled
                # plugins run once against this SBOM. The orchestrator populates
                # the releases M2M at completion time from the current
                # ReleaseArtifact state (which update_latest_release_on_sbom_created
                # has already committed by the time this on_commit callback runs).
                enqueued = enqueue_assessments_for_sbom(
                    sbom_id=sbom_id,
                    team_id=team_id,
                    run_reason=RunReason.ON_UPLOAD,
                )
                if enqueued:
                    logger.info(f"Enqueued {len(enqueued)} plugin assessments for SBOM {sbom_id}: {enqueued}")
                else:
                    logger.debug(f"No plugin assessments enqueued for SBOM {sbom_id}")
            except Exception:
                logger.warning(
                    f"Failed to enqueue plugin assessments for SBOM {sbom_id} (message broker may be unavailable)",
                    exc_info=True,
                )

        run_on_commit(_enqueue_assessments)

    except ImportError as e:
        logger.error(f"Failed to import plugin modules for SBOM {instance.id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error triggering plugin assessments for SBOM {instance.id}: {e}", exc_info=True)


@receiver(post_delete, sender="core.ReleaseArtifact")
def detach_release_from_runs_on_artifact_removal(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Stage 5 Issue A: remove the release from any AssessmentRun M2M when its
    ReleaseArtifact is deleted, and re-sync DT project tags to match.

    Triggered when:
      - A named ReleaseArtifact is explicitly removed by a user
      - The auto-'latest' pointer moves to a new SBOM (the old SBOM's latest
        ReleaseArtifact is deleted and a new one created for the new SBOM)
      - A Release is deleted (cascades to its ReleaseArtifacts)

    Under the scan-once-per-SBOM model, leaving the release attached to the
    old run after the ReleaseArtifact is gone would produce two lies:
      1. The UI would show "this scan covers release X" when X is no longer
         linked to this SBOM.
      2. DT project tags would keep the stale release name, making DT UI
         filters return the wrong project version.

    The fix: drop the M2M rows pointing at this (sbom, release) and enqueue
    a lightweight dramatiq task (``detach_release_from_runs_task``) that
    asks each affected plugin to re-sync its downstream tag state from the
    updated M2M. The task is idempotent and Q2=B-compliant (re-reads the
    full canonical set).
    """
    if instance.sbom_id is None:
        return

    # Intentionally does NOT honor ``_suppress_collection_signals`` — that
    # flag is scoped to collection_version bumps on the Release model and is
    # set by ``Release.refresh_latest_artifacts``. When the latest pointer
    # moves from one SBOM to another during a new-SBOM upload,
    # refresh_latest_artifacts clears all artifacts (triggering our
    # post_delete) under the suppression flag — but we WANT the detach/sync
    # to happen in that case so DT tags and M2M rows stay consistent with
    # the new latest state. The detach task is idempotent, so the extra
    # fires during a bulk refresh converge to the correct state.

    sbom_id = str(instance.sbom_id)
    release_id = str(instance.release_id) if instance.release_id else None
    if release_id is None:
        return

    def _detach() -> None:
        try:
            from sbomify.apps.plugins.tasks import detach_release_from_runs_task

            detach_release_from_runs_task.send(sbom_id=sbom_id, release_id=release_id)
            logger.debug(
                "Enqueued detach-release task for SBOM %s, release %s",
                sbom_id,
                release_id,
            )
        except Exception:
            logger.warning(
                "Failed to enqueue detach-release task for SBOM %s (broker may be unavailable)",
                sbom_id,
                exc_info=True,
            )

    run_on_commit(_detach)
