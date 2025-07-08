from django.db.models.signals import post_save
from django.dispatch import receiver

from billing.models import BillingPlan
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


@receiver(post_save, sender=SBOM)
def trigger_license_processing(sender, instance, created, **kwargs):
    """Trigger license processing task when a new SBOM is created."""
    if created:
        from sbomify.tasks import process_sbom_licenses

        # Add a 30 second delay to ensure transaction is committed
        process_sbom_licenses.send_with_options(args=[instance.id], delay=30000)


@receiver(post_save, sender=SBOM)
def trigger_ntia_compliance_check(sender, instance, created, **kwargs):
    """Trigger NTIA compliance checking task when a new SBOM is created."""
    if created:
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
            logger.warning(
                f"Billing plan '{team.billing_plan}' not found for team {team.key}, skipping NTIA compliance check"
            )
            return

        # Proceed with NTIA compliance check for business/enterprise plans
        from sbomify.tasks import check_sbom_ntia_compliance

        logger.info(
            f"Triggering NTIA compliance check for SBOM {instance.id} - plan '{plan.key}' includes NTIA compliance"
        )
        # Add a 60 second delay to ensure transaction is committed and to stagger after license processing
        check_sbom_ntia_compliance.send_with_options(args=[instance.id], delay=60000)


@receiver(post_save, sender=SBOM)
def trigger_vulnerability_scan(sender, instance, created, **kwargs):
    """Trigger vulnerability scanning task when a new SBOM is created."""
    if created:
        # Check if the team's billing plan includes vulnerability scanning
        team = instance.component.team

        # If no billing plan, skip vulnerability scan (community default)
        if not team.billing_plan:
            logger.info(f"Skipping vulnerability scan for SBOM {instance.id} - no billing plan (community)")
            return

        try:
            plan = BillingPlan.objects.get(key=team.billing_plan)
            if not plan.has_vulnerability_scanning:
                logger.info(
                    f"Skipping vulnerability scan for SBOM {instance.id} - "
                    f"plan '{plan.key}' does not include vulnerability scanning"
                )
                return
        except BillingPlan.DoesNotExist:
            logger.warning(
                f"Billing plan '{team.billing_plan}' not found for team {team.key}, skipping vulnerability scan"
            )
            return

        # Proceed with vulnerability scan for business/enterprise plans
        from sbomify.tasks import scan_sbom_for_vulnerabilities

        logger.info(
            f"Triggering vulnerability scan for SBOM {instance.id} - plan '{plan.key}' includes vulnerability scanning"
        )
        # Add a 90 second delay to ensure transaction is committed and to stagger after NTIA compliance
        scan_sbom_for_vulnerabilities.send_with_options(args=[instance.id], delay=90000)
