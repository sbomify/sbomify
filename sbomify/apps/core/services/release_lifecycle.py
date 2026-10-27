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
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.db.models.functions import Coalesce
from django.utils import timezone

from sbomify.apps.core.models import Release, ReleaseLink
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


def releases_linked_from(release_ids: Any) -> set[str]:
    """Every release reachable through links from these releases, not counting them. Links cannot form a cycle."""
    reached: set[str] = set()
    frontier = set(ReleaseLink.objects.filter(release_id__in=release_ids).values_list("linked_release_id", flat=True))
    while frontier:
        reached |= frontier
        frontier = (
            set(ReleaseLink.objects.filter(release_id__in=frontier).values_list("linked_release_id", flat=True))
            - reached
        )
    return reached


def shipping_releases(now: datetime | None = None) -> QuerySet[Release]:
    """The releases whose SBOMs sbomify tracks: the tracked releases and every release they link to.

    A linked release's SBOMs are part of the linking release's aggregate SBOM,
    so a live release keeps them tracked even when the linked release is itself
    retired. A retired release's links keep nothing alive.
    """
    tracked = tracked_releases(now=now).values("pk")
    return Release.objects.filter(Q(pk__in=tracked) | Q(pk__in=releases_linked_from(tracked)))


def replacement_candidates(product_id: str) -> list[Release]:
    """The releases a new release of the product can supersede: named, still monitored, newest first."""
    return list(tracked_releases(Release.objects.filter(product_id=product_id, is_latest=False)))


def declare_supersedes(successor: Release, items: Iterable[Any], *, actor_id: Any = None) -> ServiceResult[None]:
    """Record that ``successor`` supersedes each release ``items`` names.

    Each item has ``release_id`` or ``version`` (then name, within the successor's
    product) and ``drop_in``. The edge goes on the predecessor's CLE stream through
    the same validation as the CLE endpoint. Run it inside the transaction that
    owns the successor: a failure leaves earlier edges for the caller to roll back.
    """
    # cle.py imports this module for the edge rules.
    from sbomify.apps.core.services.cle import create_release_cle_event

    siblings = Release.objects.filter(product_id=successor.product_id)
    successor_version = successor.version or successor.name
    for item in items:
        if item.release_id:
            predecessor = Release.objects.select_related("product").filter(pk=item.release_id).first()
            if predecessor is None or predecessor.product.team_id != successor.product.team_id:
                return ServiceResult.failure(f"Release {item.release_id} not found.", status_code=400)
            if predecessor.product_id != successor.product_id:
                return ServiceResult.failure(
                    f"Release {predecessor.name} belongs to another product. "
                    "A release can only supersede releases of its own product.",
                    status_code=400,
                )
        else:
            predecessor = siblings.filter(version=item.version).first() or siblings.filter(name=item.version).first()
            if predecessor is None:
                return ServiceResult.failure(f"This product has no release {item.version}.", status_code=400)

        result = create_release_cle_event(
            predecessor,
            CLEEventType.SUPERSEDED_BY,
            successor.released_at or successor.created_at,
            version=predecessor.version,
            superseded_by_version=successor_version,
            drop_in=item.drop_in,
            actor_id=actor_id,
            queue_reconcile=False,
        )
        if not result.ok or result.value is None:
            return ServiceResult.failure(result.error or "Invalid supersession", status_code=400)
        if result.value.superseded_by_release_id != successor.pk:
            return ServiceResult.failure(
                f"{successor_version} names more than one release of this product. Give this release a version.",
                status_code=400,
            )
    if items:
        after_lifecycle_change(successor.product_id)
    return ServiceResult.success(None)


def supersession_links(release_id: str) -> dict[str, list[ReleaseCLEEvent]]:
    """The surviving edges into and out of a release: what it replaces, and what replaced it."""
    edges = surviving_supersessions().select_related("release", "superseded_by_release").order_by("event_id")
    return {
        "replaces": list(edges.filter(superseded_by_release_id=release_id)),
        "replaced_by": list(edges.filter(release_id=release_id)),
    }


def surviving_supersessions() -> QuerySet[ReleaseCLEEvent]:
    """``supersededBy`` events that no ``withdrawn`` event on the same release voids."""
    voided = ReleaseCLEEvent.objects.filter(
        release_id=OuterRef("release_id"),
        event_type=CLEEventType.WITHDRAWN,
        withdrawn_event_id=OuterRef("event_id"),
    )
    return ReleaseCLEEvent.objects.filter(event_type=CLEEventType.SUPERSEDED_BY).exclude(Exists(voided))


def identical_supersession(
    predecessor: Release, superseded_by_version: str, drop_in: bool, effective: datetime
) -> ReleaseCLEEvent | None:
    """The surviving edge a retry of the same declaration would duplicate, if any."""
    return (
        surviving_supersessions()
        .filter(release=predecessor, superseded_by_version=superseded_by_version, drop_in=drop_in, effective=effective)
        .first()
    )


def _sibling_named(product_id: str, value: str) -> Release | None:
    """The release in ``product_id`` an edge naming ``value`` points at: version first, then name."""
    siblings = Release.objects.filter(product_id=product_id)
    return siblings.filter(version=value).first() or siblings.filter(name=value).first()


def resolve_successor(predecessor: Release, superseded_by_version: str) -> ServiceResult[Release | None]:
    """Find the release ``superseded_by_version`` names in the predecessor's product, and check the edge.

    A version no release carries is a successor outside sbomify, which is
    allowed: the value is ``None``. Call under the product lock.
    """
    if predecessor.is_latest:
        return ServiceResult.failure("The latest release is never superseded.", status_code=400)

    successor = _sibling_named(predecessor.product_id, superseded_by_version)
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


def link_pending_supersessions(release: Release) -> ServiceResult[int]:
    """Point the edges declared before ``release`` existed, or before it carried its name, at it.

    Such an edge is stored with no successor, so the cycle check cannot see it
    until it is linked. Call inside the transaction that creates or renames
    ``release``; it takes the product lock. Refuses a link that would close a
    cycle, so the caller rolls the rename back. Linked edges stay linked when
    a release is renamed again: the edge resolved to that release.
    """
    if release.is_latest:
        return ServiceResult.success(0)
    product = Product.objects.select_for_update().filter(pk=release.product_id).first()
    if product is None:
        return ServiceResult.success(0)

    names = {name for name in (release.version, release.name) if name}
    pending = (
        surviving_supersessions()
        .filter(
            release__product_id=release.product_id,
            release__is_latest=False,
            superseded_by_release__isnull=True,
            superseded_by_version__in=names,
        )
        .exclude(release_id=release.pk)
        .select_related("release")
    )
    linked = 0
    for edge in pending:
        target = _sibling_named(release.product_id, edge.superseded_by_version)
        if target is None or target.pk != release.pk:
            continue
        if _leads_back(release, edge.release):
            return ServiceResult.failure(
                f"Release {edge.release.name} names {edge.superseded_by_version} as its successor, and "
                f"{release.name} already leads back to {edge.release.name}, so this would make a cycle.",
                status_code=400,
            )
        ReleaseCLEEvent.objects.filter(pk=edge.pk).update(superseded_by_release=release)
        linked += 1
    if linked:
        recompute_release_lifecycle(product)
    return ServiceResult.success(linked)


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
        after_lifecycle_change(product.pk)

    locked.refresh_from_db()
    return ServiceResult.success(locked)


def after_lifecycle_change(product_id: Any) -> None:
    """Once the write commits, bring Dependency-Track in line with where the product's releases now stand."""
    from sbomify.apps.vulnerability_scanning.tasks import reconcile_product_dt_scope

    transaction.on_commit(lambda: reconcile_product_dt_scope.send(str(product_id)))


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
