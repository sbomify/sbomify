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
        from sbomify.apps.plugins.tasks import enqueue_assessment
        from sbomify.apps.sboms.models import SBOM

        team = instance.team
        logger.info(
            f"Plugins enabled for team {team.key} ({team.id}). "
            f"Triggering assessments for existing SBOMs. Enabled plugins: {enabled_plugins}"
        )

        # Get all SBOMs for this team that don't have assessment runs yet
        # We'll check each SBOM to see if it needs assessments
        from sbomify.apps.core.models import Component
        from sbomify.apps.plugins.models import AssessmentRun

        components = Component.objects.filter(team=team, component_type="sbom")
        sboms = list(SBOM.objects.filter(component__in=components))
        sbom_ids = [sbom.id for sbom in sboms]

        def _enqueue_for_existing_sboms():
            enqueued_count = 0

            if not sbom_ids:
                # No SBOMs to process
                logger.debug(f"No existing SBOMs found for team {team.key} when triggering plugin assessments")
                return

            # Fetch all existing assessment runs for these SBOMs and enabled plugins in a single query
            # Group by (sbom_id, plugin_name) to check which specific plugins have runs for which SBOMs
            existing_runs = {
                (run["sbom_id"], run["plugin_name"])
                for run in AssessmentRun.objects.filter(
                    sbom_id__in=sbom_ids,
                    plugin_name__in=enabled_plugins,
                ).values("sbom_id", "plugin_name")
            }

            # Get plugin configs from settings
            settings = instance

            for sbom in sboms:
                # Check which enabled plugins don't have runs for this SBOM
                # This allows re-enabling plugins to trigger new assessments
                plugins_needing_runs = [plugin for plugin in enabled_plugins if (sbom.id, plugin) not in existing_runs]

                if not plugins_needing_runs:
                    # All enabled plugins already have runs for this SBOM
                    continue

                # Enqueue only the plugins that need runs for this SBOM
                for plugin_name in plugins_needing_runs:
                    plugin_config = settings.get_plugin_config(plugin_name)
                    enqueue_assessment(
                        sbom_id=sbom.id,
                        plugin_name=plugin_name,
                        run_reason=RunReason.CONFIG_CHANGE,
                        config=plugin_config or None,
                    )
                    enqueued_count += 1
                    logger.debug(f"Enqueued assessment for plugin {plugin_name} on SBOM {sbom.id}")

            if enqueued_count > 0:
                logger.info(
                    f"Triggered assessments for {enqueued_count} plugin(s) across {len(sboms)} existing SBOM(s) "
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
