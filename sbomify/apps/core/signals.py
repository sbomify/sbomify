from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
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

    # Track every artifact upload for retention analytics. VEX/CBOM/HBOM rows
    # live in the same table; each ships under its own event so a VEX import or
    # an in-app triage save never reads as an SBOM upload in funnels.
    from sbomify.apps.core.analytics import events
    from sbomify.apps.core.posthog_service import capture

    event = {
        "vex": events.VEX_UPLOADED,
        "cbom": events.CBOM_UPLOADED,
        "hbom": events.HBOM_UPLOADED,
    }.get(instance.bom_type, events.SBOM_UPLOADED)
    team = getattr(instance.component, "team", None) if instance.component else None
    team_key = team.key if team else ""
    component_id = getattr(instance.component, "id", "")
    sbom_id = instance.id
    source = instance.source or ""
    groups = {"workspace": team_key} if team_key else None
    distinct_id = team_key or "system"
    transaction.on_commit(
        lambda: capture(
            distinct_id,
            event,
            {"component_id": component_id, "sbom_id": sbom_id, "source": source},
            groups=groups,
        )
    )


def _update_latest_release_for_sbom(sbom_instance: Any) -> Any:
    """Internal function to update latest release for SBOM with proper error handling."""
    # Import here to avoid circular imports
    from sbomify.apps.core.models import Component, Release

    # In-app triage VEX is a component-level overlay, never a release artifact:
    # pinning it would evict the imported (DT/manual) VEX from the release slot.
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    if sbom_instance.bom_type == SBOM.BomType.VEX.value and sbom_instance.source == TRIAGE_SOURCE:
        return

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


# Attribute used on a Component instance to carry the snapshot of affected
# product IDs from ``pre_clear`` to ``post_clear`` for ``component.products.clear()``.
# Stored on the instance itself (not a module dict) so it's per-operation and
# auto-cleaned with the instance — no concurrency races between workers/threads
# clearing different Component instances, and no leak if ``post_clear`` never fires.
_PENDING_CLEAR_ATTR = "_sbomify_pending_clear_product_ids"


@receiver(
    m2m_changed,
    sender="sboms.ProductComponent",
    dispatch_uid="sbomify.core.signals.update_latest_release_on_product_components_changed",
)
def update_latest_release_on_product_components_changed(
    sender: Any, instance: Any, action: Any, pk_set: Any, reverse: Any, **kwargs: Any
) -> Any:
    """Refresh latest release artifacts when components are added/removed on a
    product directly via the new ``ProductComponent`` M2M.

    The M2M is declared on Component as ``products = ManyToManyField(Product,
    related_name="components")``. Django reports:

    - ``reverse=False`` when the change originates on the forward side
      (``component.products.add/remove/clear(...)``): ``instance`` is the
      Component and ``pk_set`` holds the Product PKs (None for ``post_clear``).
    - ``reverse=True`` when the change originates on the reverse side
      (``product.components.add/remove/clear(...)``): ``instance`` is the
      Product and ``pk_set`` holds the Component PKs.

    For ``post_clear`` on the forward side, ``pk_set`` is None and the M2M is
    already empty, so we snapshot the affected product IDs on ``pre_clear``
    (where the rows still exist) and consume the snapshot here. Without this,
    callers like ``component.products.clear()`` (used by ComponentScopeView and
    the transfer-component flow) would leave their old products with stale
    ``latest`` releases.
    """
    if action not in ("pre_clear", "post_add", "post_remove", "post_clear"):
        return
    from sbomify.apps.core.models import Product, Release

    if action == "pre_clear":
        if not reverse:
            # Forward-side pre_clear: snapshot products this component is about
            # to be detached from. Stored on the instance so it's per-operation.
            setattr(instance, _PENDING_CLEAR_ATTR, list(instance.products.values_list("id", flat=True)))
        # Reverse-side pre_clear has nothing to snapshot — instance is the
        # Product whose own ID we already know.
        return

    if reverse:
        product_ids: list[Any] = [instance.id]
    elif action == "post_clear":
        product_ids = getattr(instance, _PENDING_CLEAR_ATTR, []) or []
        # Drop the snapshot once consumed so a subsequent reload of the same
        # instance doesn't see stale data.
        if hasattr(instance, _PENDING_CLEAR_ATTR):
            delattr(instance, _PENDING_CLEAR_ATTR)
    else:
        product_ids = list(pk_set or ())

    if not product_ids:
        return

    # Single query for all affected products instead of one .get() per id —
    # bulk add/remove can pass dozens of PKs in pk_set.
    products_by_id = Product.objects.in_bulk(product_ids)
    for prod_id in product_ids:
        product = products_by_id.get(prod_id)
        if product is None:
            continue
        try:
            latest_release = Release.get_or_create_latest_release(product)
            latest_release.refresh_latest_artifacts()
            logger.info(
                "Refreshed latest release %s for product %s after component changes",
                latest_release.id,
                product.id,
            )
        except Exception:
            logger.error("Error refreshing latest release for product %s", prod_id, exc_info=True)


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


@receiver(post_save, sender="core.ReleaseArtifact")
def pin_latest_vex_on_sbom_artifact_added(sender: Any, instance: Any, created: Any, **kwargs: Any) -> Any:
    """When a component's SBOM is pinned to a release, pin its newest VEX too.

    Covers every path that attaches SBOM artifacts (the Add Artifact dialog,
    the GitHub action's release tagging, latest-release maintenance) so a
    release carries the component's exploitability statements without a manual
    pin. A *manually* pinned VEX is a deliberate snapshot: it evicts any auto
    pin for the same component and is never replaced automatically. Acts only
    on bom_type='sbom' and manual bom_type='vex' rows — the auto pin this
    creates matches neither branch, so it can't recurse.
    """
    if not created or not instance.sbom_id:
        return

    from sbomify.apps.core.models import _suppress_collection_signals

    # Bulk operations (refresh_latest_artifacts, add_artifact_to_latest_release)
    # manage every artifact slot themselves, VEX included; auto-pinning here
    # mid-bulk would race their own VEX create into a (release, sbom) unique
    # violation and abort the surrounding transaction.
    if _suppress_collection_signals.get(False):
        return

    try:
        from sbomify.apps.core.services.vex_pins import ensure_latest_vex_pinned
        from sbomify.apps.sboms.models import SBOM

        sbom = SBOM.objects.select_related("component").filter(id=instance.sbom_id).first()
        if sbom is None:
            return
        if sbom.bom_type == SBOM.BomType.SBOM.value:
            ensure_latest_vex_pinned(instance.release, sbom.component)
        elif sbom.bom_type == SBOM.BomType.VEX.value and not instance.auto_pinned:
            # A hand-pinned VEX supersedes whatever sbomify auto-pinned for
            # this component on this release.
            instance.release.artifacts.filter(
                sbom__component=sbom.component,
                sbom__bom_type=SBOM.BomType.VEX.value,
                auto_pinned=True,
            ).exclude(pk=instance.pk).delete()
    except Exception:
        logger.error("Error auto-pinning VEX for release %s", instance.release_id, exc_info=True)


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


@receiver(
    m2m_changed,
    sender="sboms.ProductComponent",
    dispatch_uid="sbomify.core.signals.reject_cross_tenant_product_component_links",
)
def reject_cross_tenant_product_component_links(
    sender: Any, instance: Any, action: Any, pk_set: Any, reverse: Any, **kwargs: Any
) -> Any:
    """Block any ``ProductComponent`` row that would link a Product and a
    Component owned by different teams.

    The M2M is declared on Component as
    ``products = ManyToManyField(Product, related_name="components")``.
    Django reports:

    - ``reverse=False`` for the forward call site
      ``component.products.add(...)`` — ``instance`` is the Component and
      ``pk_set`` holds the Product PKs being attached.
    - ``reverse=True`` for the reverse call site
      ``product.components.add(...)`` — ``instance`` is the Product and
      ``pk_set`` holds the Component PKs being attached.

    NB: ``ProductComponent.objects.create(product=..., component=...)``
    bypasses ``m2m_changed`` entirely, so the through-model itself also
    enforces the tenancy invariant via ``ProductComponent.clean()`` /
    ``full_clean()`` (see ``sboms/models.py``). This receiver is the M2M
    boundary; ``clean()`` is the through-model boundary.
    """
    if action != "pre_add" or not pk_set:
        return

    # Imported lazily to avoid circular imports during Django app loading.
    # core/apps.py loads this module from ``ready()``, after every app has
    # registered, so this is safe; but core/signals -> sboms/models is a
    # cycle we keep deferred to make module-level testing/import order
    # robust under reload (Gunicorn prefork, Dramatiq worker init).
    from sbomify.apps.sboms.models import Component, Product

    pk_list = list(pk_set)

    if reverse:
        # Reverse call site: product.components.add(*component_pks).
        product_team_id = instance.team_id
        team_ids_by_component = dict(Component.objects.filter(pk__in=pk_list).values_list("id", "team_id"))
        for component_id in pk_list:
            component_team_id = team_ids_by_component.get(component_id)
            if component_team_id is not None and component_team_id != product_team_id:
                raise ValidationError(
                    f"Cross-tenant ProductComponent rejected: product team={product_team_id}, "
                    f"component team={component_team_id}"
                )
    else:
        # Forward call site: component.products.add(*product_pks).
        component_team_id = instance.team_id
        team_ids_by_product = dict(Product.objects.filter(pk__in=pk_list).values_list("id", "team_id"))
        for product_id in pk_list:
            product_team_id = team_ids_by_product.get(product_id)
            if product_team_id is not None and product_team_id != component_team_id:
                raise ValidationError(
                    f"Cross-tenant ProductComponent rejected: component team={component_team_id}, "
                    f"product team={product_team_id}"
                )
