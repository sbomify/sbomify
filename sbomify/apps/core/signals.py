from __future__ import annotations

from typing import Any

from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from sbomify.logging import getLogger

logger = getLogger(__name__)


@receiver(post_save, sender="sboms.SBOM")
def update_latest_release_on_sbom_created(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """Update the latest release when a new SBOM artifact is created."""
    if not created:
        return

    _update_latest_release_for_sbom(instance)

    # Track every SBOM upload for retention analytics
    from django.db import transaction

    from sbomify.apps.core.posthog_service import capture

    team = getattr(instance.component, "team", None) if instance.component else None
    team_key = team.key if team else ""
    component_id = getattr(instance.component, "id", "")
    sbom_id = instance.id
    groups = {"workspace": team_key} if team_key else None
    distinct_id = team_key or "system"
    transaction.on_commit(
        lambda: capture(distinct_id, "sbom:uploaded", {"component_id": component_id, "sbom_id": sbom_id}, groups=groups)
    )


def _update_latest_release_for_sbom(sbom_instance: Any) -> Any:
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
def update_latest_release_on_document_created(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """Update the latest release when a new Document artifact is created."""
    if not created:
        return

    _update_latest_release_for_document(instance)

    from django.db import transaction

    from sbomify.apps.core.posthog_service import capture

    team = getattr(instance.component, "team", None) if instance.component else None
    team_key = team.key if team else ""
    component_id = getattr(instance.component, "id", "")
    document_id = instance.id
    groups = {"workspace": team_key} if team_key else None
    distinct_id = team_key or "system"
    transaction.on_commit(
        lambda: capture(
            distinct_id, "document:uploaded", {"component_id": component_id, "document_id": document_id}, groups=groups
        )
    )


def _update_latest_release_for_document(document_instance: Any) -> Any:
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
def update_latest_release_on_product_projects_changed(
    sender: Any, instance: Any, action: Any, pk_set: Any, **kwargs: Any
) -> Any:
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


# --- Transition bridge: keep ProductComponent in sync with the legacy ---
# Product → Project → Component chain while both M2Ms exist. Removed once
# Project/ProductProject/ProjectComponent are dropped in the destructive
# migration (Phase 6 of the Project-removal refactor).
#
# Both `post_save` (for direct `Through.objects.create`) and `m2m_changed`
# (for `relation.add(...) / .set(...)`) are wired because Django doesn't
# fire post_save on bulk M2M operations.


def _sync_product_component_pairs(product_ids: list[Any], component_ids: list[Any]) -> None:
    from sbomify.apps.sboms.models import ProductComponent

    for prod_id in product_ids:
        for comp_id in component_ids:
            ProductComponent.objects.get_or_create(product_id=prod_id, component_id=comp_id)


@receiver(post_save, sender="sboms.ProjectComponent")
@receiver(post_save, sender="core.ProjectComponent")
def sync_product_component_on_project_component_save(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """When a Component is added to a Project via direct ORM create, link it
    to every Product that contains that Project. Receives on both the real
    sboms.ProjectComponent and its core.ProjectComponent proxy because Django
    fires post_save with the actual saved model class as sender."""
    if not created:
        return
    from sbomify.apps.sboms.models import ProductProject

    product_ids = list(
        ProductProject.objects.filter(project_id=instance.project_id).values_list("product_id", flat=True)
    )
    _sync_product_component_pairs(product_ids, [instance.component_id])


@receiver(post_save, sender="sboms.ProductProject")
@receiver(post_save, sender="core.ProductProject")
def sync_product_component_on_product_project_save(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """When a Project is added to a Product via direct ORM create, link every
    Component in that Project to the Product. See sibling for proxy rationale."""
    if not created:
        return
    from sbomify.apps.sboms.models import ProjectComponent

    component_ids = list(
        ProjectComponent.objects.filter(project_id=instance.project_id).values_list("component_id", flat=True)
    )
    _sync_product_component_pairs([instance.product_id], component_ids)


@receiver(m2m_changed, sender="sboms.ProjectComponent")
def sync_product_component_on_project_components_changed(
    sender: Any, instance: Any, action: Any, pk_set: Any, reverse: Any, **kwargs: Any
) -> Any:
    """Mirror `project.components.add(...)` (and reverse `component.projects.add(...)`)
    into the new direct ``ProductComponent`` M2M."""
    if action != "post_add" or not pk_set:
        return
    from sbomify.apps.sboms.models import ProductProject

    if reverse:
        component_ids = [instance.pk]
        project_ids = list(pk_set)
    else:
        component_ids = list(pk_set)
        project_ids = [instance.pk]

    product_ids = list(ProductProject.objects.filter(project_id__in=project_ids).values_list("product_id", flat=True))
    _sync_product_component_pairs(product_ids, component_ids)


@receiver(m2m_changed, sender="sboms.ProductProject")
def sync_product_component_on_product_projects_changed(
    sender: Any, instance: Any, action: Any, pk_set: Any, reverse: Any, **kwargs: Any
) -> Any:
    """Mirror `product.projects.add(...)` (and reverse `project.products.add(...)`)
    into the new direct ``ProductComponent`` M2M."""
    if action != "post_add" or not pk_set:
        return
    from sbomify.apps.sboms.models import ProjectComponent

    if reverse:
        project_ids = [instance.pk]
        product_ids = list(pk_set)
    else:
        project_ids = list(pk_set)
        product_ids = [instance.pk]

    component_ids = list(
        ProjectComponent.objects.filter(project_id__in=project_ids).values_list("component_id", flat=True)
    )
    _sync_product_component_pairs(product_ids, component_ids)


@receiver(post_save, sender="core.ReleaseArtifact")
def bump_collection_version_on_artifact_added(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
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
def bump_collection_version_on_artifact_removed(sender: Any, instance: Any, **kwargs: Any) -> Any:
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


@receiver(post_save, sender="sboms.SBOM")
def auto_create_component_release_on_sbom_save(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """Auto-create a ComponentRelease and link the SBOM when a new SBOM is created.

    Intentionally create-only: SBOM identity fields (component, version, qualifiers)
    are immutable after creation per ADR-004, so update handling is not needed.
    """
    if not created:
        return

    from django.db import IntegrityError, transaction

    from sbomify.apps.core.models import ComponentRelease, ComponentReleaseArtifact
    from sbomify.apps.core.purl import canonicalize_qualifiers

    # Canonicalize qualifiers before lookup to match what save() stores
    qualifiers = canonicalize_qualifiers(instance.qualifiers) if instance.qualifiers else {}

    try:
        with transaction.atomic():
            cr, cr_created = ComponentRelease.objects.get_or_create(
                component=instance.component,
                version=instance.version,
                qualifiers=qualifiers,
            )
            _artifact, artifact_created = ComponentReleaseArtifact.objects.get_or_create(
                component_release=cr,
                sbom=instance,
            )
            # Bump collection version if the ComponentRelease already existed and a new artifact was linked
            if not cr_created and artifact_created:
                cr.bump_collection_version(ComponentRelease.CollectionUpdateReason.ARTIFACT_ADDED)
    except IntegrityError:
        # Concurrent SBOM create for the same (component, version, qualifiers) can hit the
        # unique constraint. Retry by fetching the existing ComponentRelease and linking.
        logger.info(
            "IntegrityError for SBOM %s — retrying with existing ComponentRelease",
            instance.id,
        )
        try:
            cr = ComponentRelease.objects.get(
                component=instance.component,
                version=instance.version,
                qualifiers=qualifiers,
            )
            _artifact, artifact_created = ComponentReleaseArtifact.objects.get_or_create(
                component_release=cr,
                sbom=instance,
            )
            if artifact_created:
                cr.bump_collection_version(ComponentRelease.CollectionUpdateReason.ARTIFACT_ADDED)
        except Exception:
            logger.error("Retry failed for SBOM %s", instance.id, exc_info=True)
    except Exception:
        logger.error("Error auto-creating ComponentRelease for SBOM %s", instance.id, exc_info=True)


@receiver(post_delete, sender="sboms.SBOM")
def cleanup_component_release_on_sbom_delete(sender: Any, instance: Any, **kwargs: Any) -> Any:
    """Clean up ComponentRelease when an SBOM is deleted.

    Note: By the time post_delete fires, Django's CASCADE has already removed
    the ComponentReleaseArtifact row linking this SBOM, so artifacts.exists()
    correctly reflects remaining artifacts from other SBOMs.
    """
    from sbomify.apps.core.models import ComponentRelease
    from sbomify.apps.core.purl import canonicalize_qualifiers

    # Canonicalize qualifiers before lookup to match what save() stores
    qualifiers = canonicalize_qualifiers(instance.qualifiers) if instance.qualifiers else {}

    try:
        cr = ComponentRelease.objects.get(
            component=instance.component,
            version=instance.version,
            qualifiers=qualifiers,
        )
        if cr.artifacts.exists():
            cr.bump_collection_version(ComponentRelease.CollectionUpdateReason.ARTIFACT_REMOVED)
        else:
            cr.delete()
    except ComponentRelease.DoesNotExist:
        pass
    except Exception:
        logger.error("Error cleaning up ComponentRelease for SBOM %s", instance.id, exc_info=True)
