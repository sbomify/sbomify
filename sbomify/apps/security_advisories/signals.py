"""Keeps a workspace's CSAF distribution marker moving forward.

``provider-metadata.json`` and the ROLIE feed both carry a "last updated"
marker, and a poller uses it to decide whether to fetch again. Deriving that
marker from the advisories currently in the feed gets removals wrong: when a
public advisory is deleted, or stops being public, the maximum over what is left
can be *older* than the value the poller already holds, so it never looks again
and keeps serving a document we have withdrawn.

So the marker is stored on the workspace, and four things keep it honest.

**It is bumped from every write the document is rendered from.** A CSAF document
comes out of ``anonymous_projection``, and that reads more than the advisory
row: vulnerabilities, product statuses, version ranges, references, public
events, and, through ``anonymous_viewer_scope``, the products and components
that decide which product names the document may print. All of them are watched,
so a CVSS edit, a posted update or a renamed product moves the marker.

**It only ever moves forward, in the database.** ``Greatest`` against the stored
value rather than a plain assignment: two signals racing in Python can commit
out of order, and the later writer must not be able to install an earlier
timestamp.

**It is written after commit.** ``publish_advisory`` locks the workspace row and
then the advisory; the other services lock the advisory first. Taking the
workspace row from inside ``post_save`` would complete that cycle and deadlock,
so the update runs in its own transaction once the advisory lock is gone. A
rolled-back write correctly bumps nothing.

**It moves only for what the world can already see.** A draft is excluded even
when its ``visibility`` is PUBLIC, because ``is_externally_visible`` says a draft
is not visible whatever visibility claims, and an internal ``COMMENT`` or a
``field_change`` is excluded because the projection only renders
``PUBLIC_EVENT_TYPES``. A marker anyone may poll must not move for work nobody
may see, or it leaks the timing of an embargo through a cacheable endpoint.

**Known limit:** these are model signals, so a bulk ``queryset.update()`` or
``bulk_create`` does not reach them. The advisory services all save instances,
so the supported paths are covered; a future bulk path has to bump the marker
itself.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from django.db import transaction
from django.db.models import DateTimeField, F, Q
from django.db.models.functions import Coalesce, Greatest, Now
from django.db.models.signals import m2m_changed, post_delete, post_save

from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)

# An advisory the world can see now, or could see once. The draft exclusion
# mirrors SecurityAdvisory.is_externally_visible: visibility alone is not enough,
# because a draft may carry visibility=PUBLIC and still be internal.
_IN_PUBLIC_DISTRIBUTION = ~Q(status=SecurityAdvisory.Status.DRAFT) & (
    Q(visibility=SecurityAdvisory.Visibility.PUBLIC) | Q(made_public_at__isnull=False)
)

# How to get from a row the projection reads back to the advisory it belongs to.
# AdvisoryComponent is absent on purpose: the public projection never reads it.
_TO_ADVISORY: dict[type, Callable[[Any], SecurityAdvisory | None]] = {
    SecurityAdvisory: lambda row: row,
    AdvisoryVulnerability: lambda row: row.advisory,
    AdvisoryReference: lambda row: row.advisory,
    AdvisoryProduct: lambda row: row.advisory,
    AdvisoryEvent: lambda row: row.advisory,
    AdvisoryProductStatus: lambda row: row.vulnerability.advisory,
    AdvisoryVersionRange: lambda row: row.product_status.vulnerability.advisory,
}


def _bump(team_ids: Iterable[Any]) -> None:
    from sbomify.apps.teams.models import Team

    team_ids = [t for t in team_ids if t is not None]
    if not team_ids:
        return
    # Greatest against the stored value, so an out-of-order commit cannot install
    # an older timestamp. Coalesce because GREATEST propagates NULL on some
    # backends and the column starts NULL.
    Team.objects.filter(pk__in=team_ids).update(
        csaf_feed_updated_at=Greatest(
            Coalesce(F("csaf_feed_updated_at"), Now(), output_field=DateTimeField()),
            Now(),
            output_field=DateTimeField(),
        )
    )


def _schedule(team_ids: Iterable[Any]) -> None:
    ids = list(team_ids)
    if not ids:
        return
    # After commit, so the workspace row is never taken while an advisory row is
    # held: that ordering is what would deadlock against publish_advisory.
    transaction.on_commit(lambda: _bump(ids))


def _renders_in_public_document(advisory: SecurityAdvisory, instance: Any) -> bool:
    if advisory.status == SecurityAdvisory.Status.DRAFT:
        return False
    if advisory.visibility != SecurityAdvisory.Visibility.PUBLIC and advisory.made_public_at is None:
        return False
    # The timeline is filtered to the public event types, so an internal comment
    # or a field-change row changes nothing a reader can fetch.
    if isinstance(instance, AdvisoryEvent) and instance.event_type not in AdvisoryEvent.PUBLIC_EVENT_TYPES:
        return False
    return True


def _on_advisory_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    resolve = _TO_ADVISORY.get(type(instance))
    if resolve is None:
        return
    try:
        advisory = resolve(instance)
    except (SecurityAdvisory.DoesNotExist, AttributeError):
        # A cascade delete can tear the parent away before the child's signal
        # runs. The advisory's own signal covers that case.
        return
    if advisory is None or not _renders_in_public_document(advisory, instance):
        return
    _schedule([advisory.team_id])


def _teams_for_products(product_ids: Iterable[Any]) -> list[Any]:
    ids = [p for p in product_ids if p is not None]
    if not ids:
        return []
    return list(
        SecurityAdvisory.objects.filter(_IN_PUBLIC_DISTRIBUTION, products__product_id__in=ids)
        .values_list("team_id", flat=True)
        .distinct()
    )


def _teams_for_components(component_ids: Iterable[Any]) -> list[Any]:
    ids = [c for c in component_ids if c is not None]
    if not ids:
        return []
    return list(
        SecurityAdvisory.objects.filter(_IN_PUBLIC_DISTRIBUTION, products__product__components__id__in=ids)
        .values_list("team_id", flat=True)
        .distinct()
    )


def _on_product_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    """A product's name and public flag both reach the rendered document."""
    _schedule(_teams_for_products([instance.pk]))


def _on_component_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    """A component's visibility decides whether its products are listed at all."""
    _schedule(_teams_for_components([instance.pk]))


def _on_product_components_changed(
    sender: Any, instance: Any, action: str, pk_set: Any, reverse: bool, **kw: Any
) -> None:
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    ids = list(pk_set or [])
    if reverse:
        # instance is the Component, pk_set holds Product ids.
        _schedule(_teams_for_products(ids or []) + _teams_for_components([instance.pk]))
    else:
        _schedule(_teams_for_products([instance.pk]))


def connect() -> None:
    """Bind receivers per sender.

    Per sender rather than a global receiver: an unfiltered ``post_save`` fires
    for every write anywhere in the project, and this only cares about a handful
    of models. ``Product`` and ``Component`` are connected through both their
    concrete class and the ``core`` proxy, because Django sends the signal with
    whichever class performed the save.
    """
    from sbomify.apps.core.models import Component as CoreComponent
    from sbomify.apps.core.models import Product as CoreProduct
    from sbomify.apps.sboms.models import Component, Product, ProductComponent

    for model in _TO_ADVISORY:
        post_save.connect(_on_advisory_write, sender=model, dispatch_uid=f"csaf_marker_save_{model.__name__}")
        post_delete.connect(_on_advisory_write, sender=model, dispatch_uid=f"csaf_marker_delete_{model.__name__}")

    for model in (Product, CoreProduct):
        post_save.connect(_on_product_write, sender=model, dispatch_uid=f"csaf_marker_product_save_{id(model)}")
        post_delete.connect(_on_product_write, sender=model, dispatch_uid=f"csaf_marker_product_delete_{id(model)}")

    for model in (Component, CoreComponent):
        post_save.connect(_on_component_write, sender=model, dispatch_uid=f"csaf_marker_component_save_{id(model)}")
        post_delete.connect(_on_component_write, sender=model, dispatch_uid=f"csaf_marker_component_delete_{id(model)}")

    m2m_changed.connect(
        _on_product_components_changed,
        sender=ProductComponent,
        dispatch_uid="csaf_marker_product_components",
    )
