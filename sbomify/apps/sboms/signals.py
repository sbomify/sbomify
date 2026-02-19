from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


# License processing task has been removed - functionality moved to native model fields
# License processing is now handled directly during SBOM upload via ComponentLicense model


@receiver(post_save, sender=SBOM)
def trigger_plugin_assessments(sender, instance, created, **kwargs):
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

            def _enqueue_assessments():
                enqueued = enqueue_assessments_for_sbom(
                    sbom_id=instance.id,
                    team_id=team.id,
                    run_reason=RunReason.ON_UPLOAD,
                )
                if enqueued:
                    logger.info(f"Enqueued {len(enqueued)} plugin assessments for SBOM {instance.id}: {enqueued}")
                else:
                    logger.debug(f"No plugin assessments enqueued for SBOM {instance.id} (no plugins enabled)")

            run_on_commit(_enqueue_assessments)

        except ImportError as e:
            logger.error(f"Failed to import plugin modules for SBOM {instance.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error triggering plugin assessments for SBOM {instance.id}: {e}", exc_info=True)
