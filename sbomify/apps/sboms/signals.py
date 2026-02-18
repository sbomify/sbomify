from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.billing.models import BillingPlan
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
    in their plugin settings. Plugin access is controlled by:
    1. Team's enabled_plugins in TeamPluginSettings
    2. Plugin's global is_enabled flag in RegisteredPlugin
    3. Billing plan restrictions (enforced when enabling plugins)
    """
    if created:
        try:
            from sbomify.apps.plugins.sdk.enums import RunReason
            from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

            team = instance.component.team

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

        except (AttributeError, ImportError) as e:
            logger.error(f"Failed to trigger plugin assessments for SBOM {instance.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error triggering plugin assessments for SBOM {instance.id}: {e}", exc_info=True)


@receiver(post_save, sender=SBOM)
def trigger_vulnerability_scan(sender, instance, created, **kwargs):
    """Trigger vulnerability scanning task when a new SBOM is created.

    For teams that have the OSV plugin enabled in their plugin settings,
    the OSV scan is handled by the plugin framework (via trigger_plugin_assessments).
    This signal only triggers the old VulnerabilityScanningService flow when
    the team has NOT enabled the OSV plugin, or for Dependency Track scanning
    (which is always handled by the old flow).
    """
    if created:
        try:
            team = instance.component.team

            # Check if team has the OSV plugin enabled via the plugin framework.
            # If so, skip the old OSV flow here — it's handled by trigger_plugin_assessments.
            osv_handled_by_plugin = _team_has_osv_plugin_enabled(team)

            if osv_handled_by_plugin:
                logger.info(f"Skipping old OSV flow for SBOM {instance.id} - team {team.key} has OSV plugin enabled")
            else:
                from sbomify.apps.vulnerability_scanning.tasks import scan_sbom_for_vulnerabilities_unified

                # Determine plan type for logging
                plan_info = "community (no billing plan)"
                if team.billing_plan:
                    try:
                        plan = BillingPlan.objects.get(key=team.billing_plan)
                        plan_info = f"'{plan.key}' plan"
                    except BillingPlan.DoesNotExist:
                        plan_info = "unknown plan"

                logger.info(f"Triggering vulnerability scan for SBOM {instance.id} - team {team.key} with {plan_info}")

                # Add a 90 second delay to ensure transaction is committed
                run_on_commit(
                    lambda: scan_sbom_for_vulnerabilities_unified.send_with_options(args=[instance.id], delay=90000)
                )

        except (AttributeError, ImportError) as e:
            logger.error(f"Failed to trigger vulnerability scan for SBOM {instance.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error triggering vulnerability scan for SBOM {instance.id}: {e}", exc_info=True)


def _team_has_osv_plugin_enabled(team) -> bool:
    """Check if team has the OSV plugin enabled in their plugin settings.

    Args:
        team: Team model instance.

    Returns:
        True if the team has "osv" in their enabled plugins.
    """
    try:
        from sbomify.apps.plugins.models import TeamPluginSettings

        settings = TeamPluginSettings.objects.get(team=team)
        return "osv" in (settings.enabled_plugins or [])
    except Exception:
        return False
