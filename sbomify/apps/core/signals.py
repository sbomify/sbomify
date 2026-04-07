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


@receiver(post_save, sender="core.ReleaseArtifact")
def trigger_release_dependent_assessments(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """Enqueue release-dependent plugin assessments when an SBOM is linked to a release.

    Plugins marked ``requires_release=True`` (currently only dependency-track)
    are excluded from the SBOM upload signal and instead triggered from this
    handler. This eliminates a race condition where the SBOM upload signal
    fires before the action's separate POST /sboms/{id}/releases call has
    created the ReleaseArtifact row, causing dependency-track to fail with
    "no release found" because the link doesn't exist yet.

    Only fires for newly-created ReleaseArtifact rows that link an SBOM
    (not documents). Re-saves and document artifacts are ignored.

    See spec: docs/superpowers/specs/2026-04-07-release-dependent-plugin-trigger-design.md
    """
    if not created:
        return
    if instance.sbom_id is None:
        return

    try:
        team_id = str(instance.release.product.team_id)
    except AttributeError:
        logger.debug(
            "ReleaseArtifact %s missing release/product/team chain, skipping plugin assessments",
            instance.pk,
        )
        return

    from sbomify.apps.core.services.transactions import run_on_commit
    from sbomify.apps.plugins.sdk.enums import RunReason
    from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

    sbom_id = instance.sbom_id
    artifact_id = instance.pk

    def _enqueue() -> None:
        try:
            enqueued = enqueue_assessments_for_sbom(
                sbom_id=sbom_id,
                team_id=team_id,
                run_reason=RunReason.ON_RELEASE_ASSOCIATION,
                release_dependent_only=True,
            )
            if enqueued:
                logger.info(
                    "Enqueued %d release-dependent plugin assessments for SBOM %s (via ReleaseArtifact %s): %s",
                    len(enqueued),
                    sbom_id,
                    artifact_id,
                    enqueued,
                )
        except Exception:
            logger.warning(
                "Failed to enqueue release-dependent plugin assessments for "
                "SBOM %s (message broker may be unavailable)",
                sbom_id,
                exc_info=True,
            )

    run_on_commit(_enqueue)


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
