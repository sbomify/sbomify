from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.billing.models import BillingPlan
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


# License processing task has been removed - functionality moved to native model fields
# License processing is now handled directly during SBOM upload via ComponentLicense model


@receiver(post_save, sender=SBOM)
def trigger_ntia_compliance_check(sender, instance, created, **kwargs):
    """Trigger NTIA compliance checking via plugin framework when a new SBOM is created.

    Uses the NTIA Minimum Elements 2021 plugin for compliance checking.
    Only triggers for business/enterprise plans that include NTIA compliance.
    """
    if created:
        try:
            # Check if the team's billing plan includes NTIA compliance
            team = instance.component.team

            # If no billing plan, skip NTIA check (community default)
            if not team.billing_plan:
                logger.info(f"Skipping NTIA compliance check for SBOM {instance.id} - no billing plan (community)")
                return

            try:
                plan = BillingPlan.objects.get(key=team.billing_plan)
                if not plan.has_ntia_compliance:
                    logger.info(
                        f"Skipping NTIA compliance check for SBOM {instance.id} - "
                        f"plan '{plan.key}' does not include NTIA compliance"
                    )
                    return
            except BillingPlan.DoesNotExist:
                logger.warning(f"Billing plan not found for team {team.key}, skipping NTIA compliance check")
                return

            # Proceed with NTIA compliance check for business/enterprise plans
            from sbomify.apps.plugins.sdk.enums import RunReason
            from sbomify.apps.plugins.tasks import enqueue_assessment

            logger.info(
                f"Triggering NTIA compliance check for SBOM {instance.id} - plan '{plan.key}' includes NTIA compliance"
            )
            enqueue_assessment(
                sbom_id=instance.id,
                plugin_name="ntia-minimum-elements-2021",
                run_reason=RunReason.ON_UPLOAD,
            )

        except (AttributeError, ImportError) as e:
            logger.error(f"Failed to trigger NTIA compliance check for SBOM {instance.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(
                f"Unexpected error triggering NTIA compliance check for SBOM {instance.id}: {e}", exc_info=True
            )


@receiver(post_save, sender=SBOM)
def trigger_vulnerability_scan(sender, instance, created, **kwargs):
    """Trigger vulnerability scanning task when a new SBOM is created."""
    if created:
        try:
            team = instance.component.team

            # OSV vulnerability scanning is available for ALL teams (community, business, enterprise)
            # The VulnerabilityScanningService will handle provider selection:
            # - Community teams: OSV only
            # - Business/Enterprise teams: OSV or Dependency Track based on team settings

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

            # Add a 90 second delay to ensure transaction is committed and to stagger after NTIA compliance
            scan_sbom_for_vulnerabilities_unified.send_with_options(args=[instance.id], delay=90000)

        except (AttributeError, ImportError) as e:
            logger.error(f"Failed to trigger vulnerability scan for SBOM {instance.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error triggering vulnerability scan for SBOM {instance.id}: {e}", exc_info=True)
