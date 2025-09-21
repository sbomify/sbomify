from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from sbomify.logging import getLogger

logger = getLogger(__name__)


@receiver(post_save, sender="sboms.SBOM")
def update_latest_release_on_sbom_created(sender, instance, created, **kwargs):
    """Update the latest release when a new SBOM artifact is created."""
    if not created:
        return

    _update_latest_release_for_sbom(instance)


def _update_latest_release_for_sbom(sbom_instance):
    """Internal function to update latest release for SBOM with proper error handling."""
    # Import here to avoid circular imports
    from sbomify.apps.core.models import Component, Release

    try:
        # Get all products that contain this SBOM's component
        # Cast to core.Component proxy model to access get_products method
        component = Component.objects.get(id=sbom_instance.component.id)
        products = component.get_products()

        for product in products:
            # Get or create latest release for this product
            latest_release = Release.get_or_create_latest_release(product)

            # Add the SBOM to the latest release using the proper method that handles duplicates
            latest_release.add_artifact_to_latest_release(sbom_instance)

            logger.info(f"Added SBOM {sbom_instance.id} to latest release {latest_release.id} for product {product.id}")
    except Exception as e:
        logger.error(f"Error updating latest release for SBOM {sbom_instance.id}: {e}")


@receiver(post_save, sender="documents.Document")
def update_latest_release_on_document_created(sender, instance, created, **kwargs):
    """Update the latest release when a new Document artifact is created."""
    if not created:
        return

    _update_latest_release_for_document(instance)


def _update_latest_release_for_document(document_instance):
    """Internal function to update latest release for Document with proper error handling."""
    # Import here to avoid circular imports
    from sbomify.apps.core.models import Component, Release

    try:
        # Get all products that contain this document's component
        # Cast to core.Component proxy model to access get_products method
        component = Component.objects.get(id=document_instance.component.id)
        products = component.get_products()

        for product in products:
            # Get or create latest release for this product
            latest_release = Release.get_or_create_latest_release(product)

            # Add the document to the latest release using the proper method that handles duplicates
            latest_release.add_artifact_to_latest_release(document_instance)

            logger.info(
                f"Added Document {document_instance.id} to latest release {latest_release.id} for product {product.id}"
            )
    except Exception as e:
        logger.error(f"Error updating latest release for Document {document_instance.id}: {e}")


@receiver(m2m_changed, sender="sboms.ProductProject")
def update_latest_release_on_product_projects_changed(sender, instance, action, pk_set, **kwargs):
    """Update the latest release when projects are added to a product."""
    if action not in ("post_add", "post_remove"):
        return

    # Import here to avoid circular imports
    from sbomify.apps.core.models import Release

    try:
        # Get or create latest release for this product
        latest_release = Release.get_or_create_latest_release(instance)

        # Refresh the artifacts in the latest release
        latest_release.refresh_latest_artifacts()

        logger.info(f"Refreshed latest release {latest_release.id} for product {instance.id} after project changes")
    except Exception as e:
        logger.error(f"Error updating latest release for product {instance.id}: {e}")
