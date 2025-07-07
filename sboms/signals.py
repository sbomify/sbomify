from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import SBOM


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
        from sbomify.tasks import check_sbom_ntia_compliance

        # Add a 60 second delay to ensure transaction is committed and to stagger after license processing
        check_sbom_ntia_compliance.send_with_options(args=[instance.id], delay=60000)
