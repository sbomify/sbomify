from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from sbomify.logging import getLogger

logger = getLogger(__name__)


@receiver(post_save, sender="sboms.SBOM")
def update_latest_release_on_sbom_created(sender, instance, created, **kwargs):
    """Update the latest release when a new SBOM artifact is created."""
    if not created:
        return

    try:
        from core.models import Release

        component = instance.component
        logger.info(f"New SBOM artifact created: {instance.name} for component {component.name}")

        # Find all products that contain this component (via projects)
        products = component.projects.values_list("products", flat=True).distinct()

        for product_id in products:
            if product_id is None:
                continue

            # Import here to avoid circular imports
            from core.models import Product

            try:
                product = Product.objects.get(id=product_id)

                # Get or create the latest release for this product
                latest_release = Release.get_or_create_latest_release(product)

                # Add this artifact to the latest release
                latest_release.add_artifact_to_latest_release(instance)

                logger.info(f"Added SBOM {instance.name} to latest release for product {product.name}")

            except Product.DoesNotExist:
                logger.warning(f"Product {product_id} not found when updating latest release")
                continue

    except Exception as e:
        logger.error(f"Error updating latest release for SBOM {instance.id}: {e}")


@receiver(post_save, sender="documents.Document")
def update_latest_release_on_document_created(sender, instance, created, **kwargs):
    """Update the latest release when a new Document artifact is created."""
    if not created:
        return

    try:
        from core.models import Release

        component = instance.component
        logger.info(f"New Document artifact created: {instance.name} for component {component.name}")

        # Find all products that contain this component (via projects)
        products = component.projects.values_list("products", flat=True).distinct()

        for product_id in products:
            if product_id is None:
                continue

            # Import here to avoid circular imports
            from core.models import Product

            try:
                product = Product.objects.get(id=product_id)

                # Get or create the latest release for this product
                latest_release = Release.get_or_create_latest_release(product)

                # Add this artifact to the latest release
                latest_release.add_artifact_to_latest_release(instance)

                logger.info(f"Added Document {instance.name} to latest release for product {product.name}")

            except Product.DoesNotExist:
                logger.warning(f"Product {product_id} not found when updating latest release")
                continue

    except Exception as e:
        logger.error(f"Error updating latest release for Document {instance.id}: {e}")


def update_latest_release_on_component_project_changed(sender, instance, action, pk_set, **kwargs):
    """Update latest releases when a component is added to or removed from projects."""
    if action not in ["post_add", "post_remove"]:
        return

    try:
        from core.models import Project, Release
        from documents.models import Document
        from sboms.models import SBOM

        component = instance
        logger.info(f"Component-project relationship changed: {component.name} (action: {action})")

        if action == "post_add":
            # Component was added to project(s)
            project_ids = pk_set or []

            for project_id in project_ids:
                try:
                    project = Project.objects.get(id=project_id)

                    # Get all products that contain this project
                    products = project.products.all()

                    for product in products:
                        # Get or create the latest release for this product
                        latest_release = Release.get_or_create_latest_release(product)

                        # Add all existing SBOMs from this component to the latest release
                        sboms = SBOM.objects.filter(component=component)
                        for sbom in sboms:
                            latest_release.add_artifact_to_latest_release(sbom)
                            logger.info(f"Added existing SBOM {sbom.name} to latest release for product {product.name}")

                        # Add all existing Documents from this component to the latest release
                        documents = Document.objects.filter(component=component)
                        for document in documents:
                            latest_release.add_artifact_to_latest_release(document)
                            logger.info(
                                f"Added existing Document {document.name} to latest release for product {product.name}"
                            )

                except Project.DoesNotExist:
                    logger.warning(f"Project {project_id} not found when updating latest releases")
                    continue

        elif action == "post_remove":
            # Component was removed from project(s) - we could remove artifacts but it's safer to leave them
            # Users can manually manage release contents if needed
            logger.info(f"Component {component.name} removed from projects - latest releases unchanged")

    except Exception as e:
        logger.error(f"Error updating latest releases for component {instance.id}: {e}")


def update_latest_release_on_product_project_changed(sender, instance, action, pk_set, **kwargs):
    """Update latest releases when a project is added to or removed from products."""
    if action not in ["post_add", "post_remove"]:
        return

    try:
        from core.models import Project, Release
        from documents.models import Document
        from sboms.models import SBOM

        product = instance
        logger.info(f"Product-project relationship changed: {product.name} (action: {action})")

        if action == "post_add":
            # Project(s) were added to this product
            project_ids = pk_set or []

            # Get or create the latest release for this product
            latest_release = Release.get_or_create_latest_release(product)

            for project_id in project_ids:
                try:
                    project = Project.objects.get(id=project_id)

                    # Get all components in this project
                    components = project.components.all()

                    for component in components:
                        # Add all existing SBOMs from this component to the latest release
                        sboms = SBOM.objects.filter(component=component)
                        for sbom in sboms:
                            latest_release.add_artifact_to_latest_release(sbom)
                            logger.info(f"Added existing SBOM {sbom.name} to latest release for product {product.name}")

                        # Add all existing Documents from this component to the latest release
                        documents = Document.objects.filter(component=component)
                        for document in documents:
                            latest_release.add_artifact_to_latest_release(document)
                            logger.info(
                                f"Added existing Document {document.name} to latest release for product {product.name}"
                            )

                except Project.DoesNotExist:
                    logger.warning(f"Project {project_id} not found when updating latest releases")
                    continue

        elif action == "post_remove":
            # Project(s) were removed from product - we could remove artifacts but it's safer to leave them
            # Users can manually manage release contents if needed
            logger.info(f"Projects removed from product {product.name} - latest releases unchanged")

    except Exception as e:
        logger.error(f"Error updating latest releases for product {instance.id}: {e}")


# Connect the m2m signals using the actual through models
# This needs to be done after Django is fully loaded to avoid import issues
def connect_m2m_signals():
    """Connect m2m signals after Django apps are ready."""
    try:
        from sboms.models import Component, Product

        # Connect component-project m2m signal
        m2m_changed.connect(update_latest_release_on_component_project_changed, sender=Component.projects.through)

        # Connect product-project m2m signal
        m2m_changed.connect(update_latest_release_on_product_project_changed, sender=Product.projects.through)

        logger.info("Successfully connected m2m signals for latest release management")

    except Exception as e:
        logger.error(f"Error connecting m2m signals: {e}")


# This will be called from apps.py ready() method
