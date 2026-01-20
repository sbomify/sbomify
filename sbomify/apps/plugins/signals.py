"""Signal handlers for the plugins app."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.apps.plugins.tasks import enqueue_assessments_for_existing_sboms_task
from sbomify.logging import getLogger

from .models import TeamPluginSettings

logger = getLogger(__name__)


@receiver(post_save, sender=TeamPluginSettings)
def trigger_assessments_for_existing_sboms(sender, instance, created, **kwargs):
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
        plugin_configs = instance.plugin_configs or {}

        logger.info(
            f"Plugins enabled for team {team.key} ({team_id}). "
            f"Dispatching background task to assess recent SBOMs. Enabled plugins: {enabled_plugins}"
        )

        def _dispatch_bulk_task():
            enqueue_assessments_for_existing_sboms_task.send(
                team_id=team_id,
                enabled_plugins=enabled_plugins,
                plugin_configs=plugin_configs,
            )
            logger.debug(f"Dispatched bulk assessment task for team {team.key}")

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
