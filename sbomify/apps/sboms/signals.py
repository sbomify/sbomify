from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


@receiver(post_save, sender="core.ReleaseArtifact")
def trigger_release_dependent_assessments(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Enqueue release-dependent plugin assessments when an SBOM is linked to a named release.

    Plugins marked ``requires_release=True`` (currently only dependency-track)
    are excluded from the SBOM upload signal and instead triggered from this
    handler. This eliminates a race condition where the SBOM upload signal
    fires before the action's separate POST /sboms/{id}/releases call has
    created the ReleaseArtifact row.

    Only fires for newly-created ReleaseArtifact rows that:
    - link an SBOM (not a document)
    - belong to a named release (not the auto-maintained "latest" release)
    - are not being created under a _suppress_collection_signals context

    The "latest" release is skipped because every SBOM upload synchronously
    auto-adds the SBOM to "latest" via update_latest_release_on_sbom_created,
    which would cause DT to run twice per upload. Named releases are the
    authoritative scan targets.

    See spec: docs/superpowers/specs/2026-04-07-release-dependent-plugin-trigger-design.md
    """
    if not created:
        return
    if instance.sbom_id is None:
        return

    # Honor the same suppression context used by sibling ReleaseArtifact handlers
    # (e.g., during bulk refresh_latest_artifacts). The is_latest guard below
    # covers the latest-release use case; this guard covers any future bulk
    # operations that may touch non-latest releases.
    from sbomify.apps.core.models import Release, _suppress_collection_signals

    if _suppress_collection_signals.get(False):
        return

    release_info = Release.objects.filter(pk=instance.release_id).values_list("is_latest", "product__team_id").first()
    if release_info is None:
        logger.debug(
            "ReleaseArtifact %s has no reachable release/product/team, skipping plugin assessments",
            instance.pk,
        )
        return

    is_latest, team_id_value = release_info
    if is_latest:
        return

    team_id = str(team_id_value)

    from sbomify.apps.plugins.sdk.enums import RunReason
    from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

    sbom_id = instance.sbom_id
    artifact_id = instance.pk

    def _enqueue() -> None:
        try:
            enqueued = enqueue_assessments_for_sbom(
                sbom_id=sbom_id,
                team_id=team_id,
                run_reason=RunReason.ON_RELEASE_ASSOCIATION,
                release_dependent_only=True,
            )
            if enqueued:
                logger.info(
                    "Enqueued %d release-dependent plugin assessments for SBOM %s (via ReleaseArtifact %s): %s",
                    len(enqueued),
                    sbom_id,
                    artifact_id,
                    enqueued,
                )
            else:
                logger.debug(
                    "No release-dependent plugins enqueued for SBOM %s (none enabled)",
                    sbom_id,
                )
        except Exception:
            logger.warning(
                "Failed to enqueue release-dependent plugin assessments for "
                "SBOM %s (message broker may be unavailable)",
                sbom_id,
                exc_info=True,
            )

    run_on_commit(_enqueue)


# License processing task has been removed - functionality moved to native model fields
# License processing is now handled directly during SBOM upload via ComponentLicense model


@receiver(post_save, sender=SBOM)
def trigger_plugin_assessments(sender: type[SBOM], instance: SBOM, created: bool, **kwargs: Any) -> None:
    """Trigger all enabled plugin assessments when a new SBOM is created.

    Uses the plugin framework to run all plugins that the team has enabled
    in their plugin settings. Both OSV and Dependency Track vulnerability
    scanning are handled by the plugin framework.

    Plugin access is controlled by:
    1. Team's enabled_plugins in TeamPluginSettings
    2. Plugin's global is_enabled flag in RegisteredPlugin
    3. Billing plan restrictions (enforced when enabling plugins)
    """
    if created:
        try:
            team = instance.component.team
        except AttributeError:
            logger.debug(f"SBOM {instance.id} has no component.team, skipping plugin assessments")
            return

        try:
            from sbomify.apps.plugins.sdk.enums import RunReason
            from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

            logger.info(f"Triggering plugin assessments for SBOM {instance.id} (team: {team.key})")

            def _enqueue_assessments() -> None:
                try:
                    enqueued = enqueue_assessments_for_sbom(
                        sbom_id=instance.id,
                        team_id=str(team.id),
                        run_reason=RunReason.ON_UPLOAD,
                        release_dependent_only=False,
                    )
                    if enqueued:
                        logger.info(f"Enqueued {len(enqueued)} plugin assessments for SBOM {instance.id}: {enqueued}")
                    else:
                        logger.debug(f"No plugin assessments enqueued for SBOM {instance.id} (no plugins enabled)")
                except Exception:
                    logger.warning(
                        f"Failed to enqueue plugin assessments for SBOM {instance.id} "
                        "(message broker may be unavailable)",
                        exc_info=True,
                    )

            run_on_commit(_enqueue_assessments)

        except ImportError as e:
            logger.error(f"Failed to import plugin modules for SBOM {instance.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error triggering plugin assessments for SBOM {instance.id}: {e}", exc_info=True)
