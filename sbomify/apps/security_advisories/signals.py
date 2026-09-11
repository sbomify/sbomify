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

Bulk writes bypass model signals. The community-downgrade visibility update
explicitly uses ``track_component_changes``; M2M manager operations use
``m2m_changed``. New bulk write paths must use the same invalidation helpers.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator

from django.db import transaction
from django.db.models import DateTimeField, F, Q
from django.db.models.functions import Coalesce, Greatest, Now
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save

from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    SecurityAdvisory,
)

# Only the current WHITE set. A transition out is captured before saving;
# made_public_at must not make later private edits externally observable.
_IN_PUBLIC_DISTRIBUTION = Q(
    status__in=(SecurityAdvisory.Status.PUBLISHED, SecurityAdvisory.Status.WITHDRAWN),
    visibility=SecurityAdvisory.Visibility.PUBLIC,
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
    if advisory.visibility != SecurityAdvisory.Visibility.PUBLIC:
        return False
    # The timeline is filtered to the public event types, so an internal comment
    # or a field-change row changes nothing a reader can fetch.
    if isinstance(instance, AdvisoryEvent) and instance.event_type not in AdvisoryEvent.PUBLIC_EVENT_TYPES:
        return False
    return True


def _before_advisory_save(sender: Any, instance: SecurityAdvisory, **kwargs: Any) -> None:
    instance.__dict__["_csaf_previous_public_team"] = (
        SecurityAdvisory.objects.filter(_IN_PUBLIC_DISTRIBUTION, pk=instance.pk)
        .values_list("team_id", flat=True)
        .first()
    )


def _on_advisory_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    if kwargs.get("raw"):
        return
    team_ids = {instance.__dict__.pop("_csaf_previous_public_team", None)}
    resolve = _TO_ADVISORY.get(type(instance))
    if resolve is None:
        return
    advisory = resolve(instance)
    if advisory is None:
        return
    # Related instances can cache an advisory from before it was re-embargoed.
    # Reload the visibility gate rather than trusting that cached relation.
    advisory = SecurityAdvisory.objects.filter(pk=advisory.pk).first()
    if advisory is not None and _renders_in_public_document(advisory, instance):
        team_ids.add(advisory.team_id)
    _schedule(team_ids - {None})


def _product_signature(link_ids: list[Any]) -> dict[Any, dict[Any, tuple[Any, str]]]:
    """Only the product identities/names visible in the anonymous projection.

    Read scalar product links, not the full vulnerability graph. Keeping hidden
    links out of the signature prevents their names and unrelated component
    fields from leaking activity through the public timestamp.
    """
    from sbomify.apps.security_advisories.services.trust_center import anonymous_viewer_scope
    from sbomify.apps.teams.models import Team

    links = list(
        AdvisoryProduct.objects.filter(
            pk__in=link_ids,
            advisory__status__in=(SecurityAdvisory.Status.PUBLISHED, SecurityAdvisory.Status.WITHDRAWN),
            advisory__visibility=SecurityAdvisory.Visibility.PUBLIC,
        ).select_related("product", "advisory__team")
    )
    teams: dict[Any, Team] = {link.advisory.team_id: link.advisory.team for link in links}
    scopes = {pk: anonymous_viewer_scope(team) for pk, team in teams.items()}
    signature: dict[Any, dict[Any, tuple[Any, str]]] = {}
    for link in links:
        if link.product_id is not None and str(link.product_id) not in scopes[link.advisory.team_id].product_ids:
            continue
        signature.setdefault(link.advisory.team_id, {})[link.pk] = (
            link.product_id,
            link.product.name if link.product is not None else link.product_name,
        )
    return signature


def _capture_products(product_ids: Iterable[Any]) -> tuple[list[Any], dict[Any, dict[Any, tuple[Any, str]]]]:
    link_ids = list(
        AdvisoryProduct.objects.filter(product_id__in=[p for p in product_ids if p is not None]).values_list(
            "pk", flat=True
        )
    )
    return link_ids, _product_signature(link_ids)


def _schedule_products(snapshot: Any) -> None:
    if snapshot is None:
        return
    link_ids, before = snapshot
    if not link_ids:
        return

    def compare() -> None:
        after = _product_signature(link_ids)
        _bump(team_id for team_id in before.keys() | after.keys() if before.get(team_id) != after.get(team_id))

    transaction.on_commit(compare)


def _component_products(component_ids: Iterable[Any]) -> list[Any]:
    from sbomify.apps.sboms.models import ProductComponent

    return list(ProductComponent.objects.filter(component_id__in=component_ids).values_list("product_id", flat=True))


@contextmanager
def track_component_changes(component_ids: Iterable[Any]) -> Iterator[None]:
    """Track public projection changes around a bulk component write."""
    snapshot = _capture_products(_component_products(component_ids))
    yield
    _schedule_products(snapshot)


def _before_product_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    instance._csaf_product_snapshot = None if kwargs.get("raw") else _capture_products([instance.pk])


def _before_component_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    instance._csaf_product_snapshot = (
        None if kwargs.get("raw") else _capture_products(_component_products([instance.pk]))
    )


def _after_product_write(sender: Any, instance: Any, **kwargs: Any) -> None:
    _schedule_products(instance.__dict__.pop("_csaf_product_snapshot", None))


def _before_product_delete(sender: Any, instance: Any, **kwargs: Any) -> None:
    _before_product_write(sender, instance, **kwargs)
    _after_product_write(sender, instance, **kwargs)


def _before_component_delete(sender: Any, instance: Any, **kwargs: Any) -> None:
    _before_component_write(sender, instance, **kwargs)
    _after_product_write(sender, instance, **kwargs)


def _on_product_components_changed(
    sender: Any, instance: Any, action: str, pk_set: Any, reverse: bool, **kw: Any
) -> None:
    if action in ("pre_add", "pre_remove", "pre_clear"):
        if reverse:
            # Component declares the M2M, so reverse=True means Product.
            product_ids = [instance.pk]
        elif action == "pre_clear":
            product_ids = list(instance.products.values_list("pk", flat=True))
        else:
            product_ids = list(pk_set or [])
        instance._csaf_m2m_snapshot = _capture_products(product_ids)
    elif action in ("post_add", "post_remove", "post_clear"):
        _schedule_products(instance.__dict__.pop("_csaf_m2m_snapshot", None))


def _before_link_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    old_product = sender.objects.filter(pk=instance.pk).values_list("product_id", flat=True).first()
    instance._csaf_product_snapshot = _capture_products([old_product, instance.product_id])


def _before_link_delete(sender: Any, instance: Any, **kwargs: Any) -> None:
    _schedule_products(_capture_products([instance.product_id]))


def _before_team_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    instance._csaf_previous_publisher = None
    fields = kwargs.get("update_fields")
    if kwargs.get("raw") or (fields is not None and "name" not in fields):
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    instance._csaf_previous_publisher = previous.display_name if previous else None


def _on_team_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    previous = instance.__dict__.pop("_csaf_previous_publisher", None)
    if not kwargs.get("raw") and previous is not None and previous != instance.display_name:
        _schedule([instance.pk])


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
    from sbomify.apps.teams.models import Team

    pre_save.connect(_before_advisory_save, sender=SecurityAdvisory, dispatch_uid="csaf_marker_advisory_before")
    pre_save.connect(_before_team_save, sender=Team, dispatch_uid="csaf_marker_team_before")
    post_save.connect(_on_team_save, sender=Team, dispatch_uid="csaf_marker_team_save")

    for model in _TO_ADVISORY:
        post_save.connect(_on_advisory_write, sender=model, dispatch_uid=f"csaf_marker_save_{model.__name__}")
        pre_delete.connect(_on_advisory_write, sender=model, dispatch_uid=f"csaf_marker_delete_{model.__name__}")

    for model in (Product, CoreProduct):
        pre_save.connect(_before_product_write, sender=model, dispatch_uid=f"csaf_marker_product_before_{id(model)}")
        post_save.connect(_after_product_write, sender=model, dispatch_uid=f"csaf_marker_product_save_{id(model)}")
        pre_delete.connect(_before_product_delete, sender=model, dispatch_uid=f"csaf_marker_product_delete_{id(model)}")

    for model in (Component, CoreComponent):
        pre_save.connect(
            _before_component_write, sender=model, dispatch_uid=f"csaf_marker_component_before_{id(model)}"
        )
        post_save.connect(_after_product_write, sender=model, dispatch_uid=f"csaf_marker_component_save_{id(model)}")
        pre_delete.connect(
            _before_component_delete, sender=model, dispatch_uid=f"csaf_marker_component_delete_{id(model)}"
        )

    # Direct through-model writes do not emit m2m_changed.
    pre_save.connect(_before_link_save, sender=ProductComponent, dispatch_uid="csaf_marker_link_before")
    post_save.connect(_after_product_write, sender=ProductComponent, dispatch_uid="csaf_marker_link_save")
    pre_delete.connect(_before_link_delete, sender=ProductComponent, dispatch_uid="csaf_marker_link_delete")

    m2m_changed.connect(
        _on_product_components_changed,
        sender=ProductComponent,
        dispatch_uid="csaf_marker_product_components",
    )
