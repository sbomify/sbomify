"""Signal handlers for the plugins app."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.logging import getLogger

from .models import TeamPluginSettings

logger = getLogger(__name__)


@receiver(post_save, sender=TeamPluginSettings)
def trigger_assessments_for_existing_sboms(sender, instance, created, **kwargs):
    """Trigger assessments for existing SBOMs when plugins are enabled.

    When plugins are enabled for a team, this signal triggers assessments
    for all existing SBOMs in that team that don't have assessment runs yet.

    This ensures that when users enable plugins, their existing SBOMs
    get assessed without requiring re-upload.
    """
    # Check if there are actually enabled plugins
    enabled_plugins = instance.enabled_plugins or []
    if not enabled_plugins:
        # No plugins enabled, nothing to do
        return

    # Trigger assessments for all SBOMs that don't have runs yet
    # The task will check if runs already exist to avoid duplicates

    try:
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom
        from sbomify.apps.sboms.models import SBOM

        team = instance.team
        logger.info(
            f"Plugins enabled for team {team.key} ({team.id}). "
            f"Triggering assessments for existing SBOMs. Enabled plugins: {enabled_plugins}"
        )

        # Get all SBOMs for this team that don't have assessment runs yet
        # We'll check each SBOM to see if it needs assessments
        from sbomify.apps.core.models import Component

        components = Component.objects.filter(team=team, component_type="sbom")
        sboms = SBOM.objects.filter(component__in=components)

        def _enqueue_for_existing_sboms():
            enqueued_count = 0
            for sbom in sboms:
                # Check if this SBOM already has assessment runs for the enabled plugins
                from sbomify.apps.plugins.models import AssessmentRun

                existing_runs = AssessmentRun.objects.filter(sbom_id=sbom.id, plugin_name__in=enabled_plugins).exists()

                # Only enqueue if there are no existing runs for enabled plugins
                # This avoids re-running assessments that already completed
                if not existing_runs:
                    enqueued = enqueue_assessments_for_sbom(
                        sbom_id=sbom.id,
                        team_id=str(team.id),
                        run_reason=RunReason.CONFIG_CHANGE,
                    )
                    if enqueued:
                        enqueued_count += len(enqueued)
                        logger.info(f"Enqueued {len(enqueued)} assessments for existing SBOM {sbom.id}: {enqueued}")

            if enqueued_count > 0:
                logger.info(
                    f"Triggered assessments for {enqueued_count} plugin(s) across {sboms.count()} existing SBOM(s) "
                    f"for team {team.key}"
                )
            else:
                logger.debug(
                    f"No new assessments needed for existing SBOMs in team {team.key} "
                    f"(all SBOMs already have assessments for enabled plugins)"
                )

        # Defer until transaction commits to ensure settings are saved
        run_on_commit(_enqueue_for_existing_sboms)

    except (AttributeError, ImportError) as e:
        logger.error(
            f"Failed to trigger assessments for existing SBOMs when plugins enabled for team {instance.team.id}: {e}",
            exc_info=True,
        )
    except Exception as e:
        logger.error(
            f"Unexpected error triggering assessments for existing SBOMs for team {instance.team.id}: {e}",
            exc_info=True,
        )
