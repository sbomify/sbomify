from django.db.models.signals import m2m_changed, post_delete, post_save
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

            logger.info(
                "Added SBOM %s to latest release %s for product %s",
                sbom_instance.id,
                latest_release.id,
                product.id,
            )
    except Exception:
        logger.error("Error updating latest release for SBOM %s", sbom_instance.id, exc_info=True)


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
                "Added Document %s to latest release %s for product %s",
                document_instance.id,
                latest_release.id,
                product.id,
            )
    except Exception:
        logger.error("Error updating latest release for Document %s", document_instance.id, exc_info=True)


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

        logger.info(
            "Refreshed latest release %s for product %s after project changes",
            latest_release.id,
            instance.id,
        )
    except Exception:
        logger.error("Error updating latest release for product %s", instance.id, exc_info=True)


@receiver(post_save, sender="core.ReleaseArtifact")
def bump_collection_version_on_artifact_added(sender, instance, created, **kwargs):
    """Bump the collection version when a new artifact is added to a release."""
    if not created:
        return

    from sbomify.apps.core.models import Release, _suppress_collection_signals

    if _suppress_collection_signals.get(False):
        return

    try:
        release = Release.objects.get(pk=instance.release_id)
        # Only bump if the release already has other artifacts (not the first one).
        # Note: count() includes the just-saved artifact, so > 1 means "had existing artifacts".
        if release.artifacts.count() > 1:
            release.bump_collection_version(Release.CollectionUpdateReason.ARTIFACT_ADDED)
    except Release.DoesNotExist:
        pass
    except Exception:
        logger.error("Error bumping collection version for release %s", instance.release_id, exc_info=True)


@receiver(post_delete, sender="core.ReleaseArtifact")
def bump_collection_version_on_artifact_removed(sender, instance, **kwargs):
    """Bump the collection version when an artifact is removed from a release."""
    from sbomify.apps.core.models import Release, _suppress_collection_signals

    if _suppress_collection_signals.get(False):
        return

    try:
        release = Release.objects.get(pk=instance.release_id)
        release.bump_collection_version(Release.CollectionUpdateReason.ARTIFACT_REMOVED)
    except Release.DoesNotExist:
        pass
    except Exception:
        logger.error("Error bumping collection version for release %s", instance.release_id, exc_info=True)
