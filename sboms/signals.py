from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import SBOM


@receiver(post_save, sender=SBOM)
def trigger_license_processing(sender, instance, created, **kwargs):
    """Trigger license processing task when a new SBOM is created."""
    if created:
        from sbomify.tasks import process_sbom_licenses

        process_sbom_licenses.send(instance.id)
