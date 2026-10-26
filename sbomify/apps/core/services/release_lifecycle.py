"""Where a product's releases stand: supersession, support dates, withdrawn and archived.

The supersession edge is the predecessor's ``supersededBy`` CLE event, so the
append-only event stream is the history and the ``Release`` lifecycle columns
are derived from it. Withdrawn and archived have no CLE event and are set by a
person through ``set_release_state``.

Every write locks the product row before anything else. Supersession is a
graph over the whole product, and a lock on one release would let two edges on
different releases each pass their own cycle check.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.db.models.functions import Coalesce
from django.utils import timezone

from sbomify.apps.core.models import Release
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import CLEEventType, Product, ReleaseCLEEvent

audit_log = logging.getLogger("sbomify.audit.release")

# A release may name at most this many successors. Fan-out is how ECMA-428
# models a line splitting; more than a handful is a mistake, not a product.
MAX_SUCCESSORS = 8

_STATE_ACTIONS = ("withdraw", "archive", "reactivate")


def tracked_releases(releases: QuerySet[Release] | None = None, now: datetime | None = None) -> QuerySet[Release]:
    """The releases sbomify still monitors.

    ``latest`` always: it holds each component's newest SBOMs. A named release
    until it is withdrawn, archived, superseded by a drop-in successor, or past
    its end of support or end of life. A release's own date wins over its
    product's, so a release with extended support outlives the product default;
    with none of its own it inherits the product's. A date is the last
    supported day.

    ``Release.lifecycle_state`` applies the same rules to one instance.
    """
    now = now or timezone.now()
    today = now.date()
    live = (
        Q(withdrawn_at__isnull=True, archived_at__isnull=True)
        & (Q(superseded_at__isnull=True) | Q(superseded_at__gt=now))
        & (Q(lifecycle_eos__isnull=True) | Q(lifecycle_eos__gte=today))
        & (Q(lifecycle_eol__isnull=True) | Q(lifecycle_eol__gte=today))
    )
    return (
        (Release.objects.all() if releases is None else releases)
        .alias(
            lifecycle_eos=Coalesce("end_of_support", "product__end_of_support"),
            lifecycle_eol=Coalesce("end_of_life", "product__end_of_life"),
        )
        .filter(Q(is_latest=True) | live)
    )


def surviving_supersessions() -> QuerySet[ReleaseCLEEvent]:
    """``supersededBy`` events that no ``withdrawn`` event on the same release voids."""
    voided = ReleaseCLEEvent.objects.filter(
        release_id=OuterRef("release_id"),
        event_type=CLEEventType.WITHDRAWN,
        withdrawn_event_id=OuterRef("event_id"),
    )
    return ReleaseCLEEvent.objects.filter(event_type=CLEEventType.SUPERSEDED_BY).exclude(Exists(voided))


def identical_supersession(predecessor: Release, superseded_by_version: str, drop_in: bool) -> ReleaseCLEEvent | None:
    """The surviving edge a retry of the same declaration would duplicate, if any."""
    return (
        surviving_supersessions()
        .filter(release=predecessor, superseded_by_version=superseded_by_version, drop_in=drop_in)
        .first()
    )


def resolve_successor(predecessor: Release, superseded_by_version: str) -> ServiceResult[Release | None]:
    """Find the release ``superseded_by_version`` names in the predecessor's product, and check the edge.

    A version no release carries is a successor outside sbomify, which is
    allowed: the value is ``None``. Call under the product lock.
    """
    if predecessor.is_latest:
        return ServiceResult.failure("The latest release is never superseded.", status_code=400)

    siblings = Release.objects.filter(product_id=predecessor.product_id)
    successor = (
        siblings.filter(version=superseded_by_version).first() or siblings.filter(name=superseded_by_version).first()
    )
    if successor is not None:
        if successor.pk == predecessor.pk:
            return ServiceResult.failure("A release cannot supersede itself.", status_code=400)
        if successor.is_latest:
            return ServiceResult.failure("The latest release cannot supersede another release.", status_code=400)
        if _leads_back(successor, predecessor):
            return ServiceResult.failure(
                f"Release {successor.name} already leads back to {predecessor.name}, so this would make a cycle. "
                "To roll a release back, withdraw it instead.",
                status_code=400,
            )

    if surviving_supersessions().filter(release=predecessor).count() >= MAX_SUCCESSORS:
        return ServiceResult.failure(
            f"Release {predecessor.name} already names {MAX_SUCCESSORS} successors, the most it can have.",
            status_code=400,
        )
    return ServiceResult.success(successor)


def _leads_back(successor: Release, predecessor: Release) -> bool:
    """Whether surviving edges already run from ``successor`` to ``predecessor``."""
    edges: dict[str, list[str]] = defaultdict(list)
    for source, target in (
        surviving_supersessions()
        .filter(release__product_id=predecessor.product_id, superseded_by_release__isnull=False)
        .values_list("release_id", "superseded_by_release_id")
    ):
        edges[source].append(target)

    stack, seen = [successor.pk], set()
    while stack:
        node = stack.pop()
        if node == predecessor.pk:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(edges[node])
    return False


def recompute_release_lifecycle(product: Product) -> None:
    """Derive every release's lifecycle columns in ``product`` from its CLE events.

    Product-wide, because withdrawing a successor changes its predecessors.

    - ``end_of_support``: per support policy, the latest surviving
      ``endOfSupport`` event; the column is the latest across policies.
    - ``end_of_life``: the latest surviving ``endOfLife`` event.
    - ``superseded_at``: the earliest surviving drop-in ``supersededBy`` event
      whose successor is outside sbomify or not withdrawn. A withdrawn
      successor hands its predecessors their liveness back.

    Writes only the rows that changed, and never through ``save()``.
    """
    releases = {release.pk: release for release in Release.objects.filter(product_id=product.pk)}
    events = list(ReleaseCLEEvent.objects.filter(release__product_id=product.pk).order_by("release_id", "event_id"))
    voided = {
        (event.release_id, event.withdrawn_event_id)
        for event in events
        if event.event_type == CLEEventType.WITHDRAWN and event.withdrawn_event_id is not None
    }

    support_ends: dict[str, dict[str, date]] = defaultdict(dict)
    life_ends: dict[str, date] = {}
    superseded: dict[str, datetime] = {}
    for event in events:
        if (event.release_id, event.event_id) in voided:
            continue
        if event.event_type == CLEEventType.END_OF_SUPPORT:
            support_ends[event.release_id][event.support_id] = event.effective.date()
        elif event.event_type == CLEEventType.END_OF_LIFE:
            life_ends[event.release_id] = event.effective.date()
        elif event.event_type == CLEEventType.SUPERSEDED_BY and event.drop_in:
            # No resolved successor: outside sbomify, or deleted. It still counts.
            successor = releases.get(event.superseded_by_release_id) if event.superseded_by_release_id else None
            if successor is None or successor.withdrawn_at is None:
                earliest = superseded.get(event.release_id)
                superseded[event.release_id] = min(earliest, event.effective) if earliest else event.effective

    fields = ("superseded_at", "end_of_support", "end_of_life")
    changed = []
    for pk, release in releases.items():
        derived = (superseded.get(pk), max(support_ends[pk].values(), default=None), life_ends.get(pk))
        if tuple(getattr(release, field) for field in fields) != derived:
            release.superseded_at, release.end_of_support, release.end_of_life = derived
            changed.append(release)
    if changed:
        Release.objects.bulk_update(changed, fields)


def set_release_state(
    release: Release, action: str, *, reason: str = "", actor_id: Any = None
) -> ServiceResult[Release]:
    """Withdraw, archive or reactivate a release.

    ``reactivate`` clears withdrawn and archived only. A supersession or a
    support date is undone by withdrawing its CLE event.
    """
    if action not in _STATE_ACTIONS:
        return ServiceResult.failure(f"Unknown action: {action}", status_code=400)
    if action == "withdraw" and reason not in Release.WithdrawnReason.values:
        return ServiceResult.failure(
            f"Choose why the release is withdrawn: {', '.join(Release.WithdrawnReason.values)}.", status_code=400
        )

    with transaction.atomic():
        product = Product.objects.select_for_update().filter(pk=release.product_id).first()
        locked = Release.objects.select_for_update().filter(pk=release.pk).first()
        if product is None or locked is None:
            return ServiceResult.failure("Release no longer exists", status_code=404)
        if locked.is_latest:
            return ServiceResult.failure(
                "The latest release cannot be withdrawn or archived. It always holds the newest artifacts.",
                status_code=400,
            )

        now = timezone.now()
        if action == "withdraw":
            updates: dict[str, Any] = {"withdrawn_at": locked.withdrawn_at or now, "withdrawn_reason": reason}
        elif action == "archive":
            updates = {"archived_at": locked.archived_at or now}
        else:
            updates = {"withdrawn_at": None, "withdrawn_reason": "", "archived_at": None}
        Release.objects.filter(pk=locked.pk).update(**updates)
        recompute_release_lifecycle(product)
        audit(action, locked, actor_id, reason=reason)

    locked.refresh_from_db()
    return ServiceResult.success(locked)


def audit(action: str, release: Release, actor_id: Any, **detail: Any) -> None:
    """One structured line per lifecycle decision a person or a pipeline makes."""
    extra = {
        "action": action,
        "release_id": release.pk,
        "product_id": release.product_id,
        "actor_id": actor_id,
        **detail,
    }
    audit_log.info("release_lifecycle %s", json.dumps(extra, default=str), extra=extra)
