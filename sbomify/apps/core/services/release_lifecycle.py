"""Where a product's releases stand: supersession, support dates, withdrawn and archived.

Supersession is a graph over a product's releases, one ``ReleaseSupersession``
row per edge. A release can have many successors and many predecessors: 1.2.1
replaced by 1.2.2 on its own line while 2.0 starts a new one. Each edge is
published as the predecessor's ``supersededBy`` CLE event, and the support
dates come from the CLE stream, so the ``Release`` lifecycle columns are
derived from both. Withdrawn and archived have no CLE event and are set by a
person through ``set_release_state``.

A release with no support date of its own takes the product's, but only from a
product event that covers every version. sbomify has no version parser, by
design, so it cannot tell which releases a range such as ``vers:semver/<2.0.0``
covers; a date like that belongs on the releases themselves.

Every write locks the product row before anything else, then the release. A
lock on one release would let two edges on different releases each pass their
own cycle check, and taking the two in the other order would deadlock against
the writers here.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from sbomify.apps.core.models import Release, ReleaseSupersession
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import BaseCLEEvent, CLEEventType, Product, ProductCLEEvent, ReleaseCLEEvent

audit_log = logging.getLogger("sbomify.audit.release")

# A release may name at most this many live successors. A line splitting is
# routine; more than a handful at once is a mistake, not a product.
MAX_SUCCESSORS = 8

_STATE_ACTIONS = ("withdraw", "archive", "reactivate")


def tracked_releases(releases: QuerySet[Release] | None = None, now: datetime | None = None) -> QuerySet[Release]:
    """The releases sbomify still monitors.

    ``latest`` always: it holds each component's newest SBOMs. A named release
    until it is withdrawn, archived, superseded by a drop-in successor, or past
    its end of support or end of life. The dates are the ``effective_*``
    columns: a release's own date wins over its product's, so a release with
    extended support outlives the product default; with none of its own it
    inherits the product's date for every version. A date is the last
    supported day.

    ``Release.lifecycle_state`` applies the same rules to one instance.
    """
    now = now or timezone.now()
    today = now.date()
    live = (
        Q(withdrawn_at__isnull=True, archived_at__isnull=True)
        & (Q(superseded_at__isnull=True) | Q(superseded_at__gt=now))
        & (Q(effective_end_of_support__isnull=True) | Q(effective_end_of_support__gte=today))
        & (Q(effective_end_of_life__isnull=True) | Q(effective_end_of_life__gte=today))
    )
    return (Release.objects.all() if releases is None else releases).filter(Q(is_latest=True) | live)


def replacement_candidates(product_id: str) -> list[Release]:
    """The releases a new release of the product can supersede: named, still monitored, newest first."""
    return list(tracked_releases(Release.objects.filter(product_id=product_id, is_latest=False)))


def declare_supersedes(successor: Release, items: Iterable[Any], *, actor_id: Any = None) -> ServiceResult[None]:
    """Record that ``successor`` supersedes each release ``items`` names.

    Each item has ``release_id`` or ``version`` (then name, within the successor's
    product) and ``drop_in``. Each is one edge, written through the same service
    and validation as the CLE endpoint, so a release can replace several at once.
    Run it inside the transaction that owns the successor: a failure leaves
    earlier edges for the caller to roll back.
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

        # An edge declared before this release existed was linked to it on create. Its
        # date is when the caller said the successor takes over, so only drop_in must agree.
        if (
            ReleaseSupersession.objects.live()
            .filter(from_release=predecessor, to_release=successor, drop_in=item.drop_in)
            .exists()
        ):
            continue
        result = create_release_cle_event(
            predecessor,
            CLEEventType.SUPERSEDED_BY,
            successor.released_at or successor.created_at,
            version=predecessor.version,
            superseded_by_version=successor_version,
            drop_in=item.drop_in,
            actor_id=actor_id,
        )
        if not result.ok or result.value is None:
            status = 409 if result.status_code == 409 else 400
            return ServiceResult.failure(result.error or "Invalid supersession", status_code=status)
        edge = ReleaseSupersession.objects.filter(cle_event=result.value).first()
        if edge is None or edge.to_release_id != successor.pk:
            return ServiceResult.failure(
                f"{successor_version} names more than one release of this product. Give this release a version.",
                status_code=400,
            )
    return ServiceResult.success(None)


def supersession_links(release_id: str) -> dict[str, list[ReleaseSupersession]]:
    """The live edges into and out of a release: every release it replaces, and every successor it has."""
    edges = ReleaseSupersession.objects.live().select_related("from_release", "to_release")
    return {
        "predecessors": list(edges.filter(to_release_id=release_id)),
        "successors": list(edges.filter(from_release_id=release_id)),
    }


def existing_supersession(
    predecessor: Release, successor_label: str, drop_in: bool
) -> ServiceResult[ReleaseSupersession | None]:
    """The live edge to ``successor_label`` a retry would repeat, or a conflict when it is on the other line.

    One live edge per successor. A retry with another date is the same edge, so
    a pipeline re-run or a corrected release date never fails a build that
    changed nothing. Moving it to the other line means removing the link and
    declaring it again, so the history keeps both.
    """
    edge = ReleaseSupersession.objects.live().filter(from_release=predecessor, successor_label=successor_label).first()
    if edge is None or edge.drop_in == drop_in:
        return ServiceResult.success(edge)
    line = "the same line" if edge.drop_in else "a new line"
    return ServiceResult.failure(
        f"Release {predecessor.name} already names {successor_label} as {line}. Remove that link first to change it.",
        status_code=409,
    )


def _sibling_named(product_id: str, value: str) -> Release | None:
    """The release in ``product_id`` an edge naming ``value`` points at: version first, then name."""
    siblings = Release.objects.filter(product_id=product_id)
    return siblings.filter(version=value).first() or siblings.filter(name=value).first()


def resolve_successor(predecessor: Release, superseded_by_version: str) -> ServiceResult[Release | None]:
    """Find the release ``superseded_by_version`` names in the predecessor's product, and check the edge.

    A version no release carries is a successor outside sbomify, which is
    allowed: the value is ``None``. A release may name several successors, up
    to ``MAX_SUCCESSORS`` live ones. Call under the product lock.
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

    if ReleaseSupersession.objects.live().filter(from_release=predecessor).count() >= MAX_SUCCESSORS:
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
        ReleaseSupersession.objects.live()
        .filter(
            from_release__product_id=release.product_id,
            from_release__is_latest=False,
            to_release__isnull=True,
            successor_label__in=names,
        )
        .exclude(from_release_id=release.pk)
        .select_related("from_release")
    )
    linked = 0
    for edge in pending:
        target = _sibling_named(release.product_id, edge.successor_label)
        if target is None or target.pk != release.pk:
            continue
        if _leads_back(release, edge.from_release):
            return ServiceResult.failure(
                f"Release {edge.from_release.name} names {edge.successor_label} as a successor, and "
                f"{release.name} already leads back to {edge.from_release.name}, so this would make a cycle.",
                status_code=400,
            )
        ReleaseSupersession.objects.filter(pk=edge.pk).update(to_release=release)
        linked += 1
    if linked:
        recompute_release_lifecycle(product)
    return ServiceResult.success(linked)


def _leads_back(successor: Release, predecessor: Release) -> bool:
    """Whether live edges already run from ``successor`` to ``predecessor``.

    The graph can re-converge (two lines merging into one release), so the walk
    keeps a visited set even though no cycle can be stored.
    """
    edges: dict[str, list[str]] = defaultdict(list)
    for source, target in (
        ReleaseSupersession.objects.live()
        .filter(from_release__product_id=predecessor.product_id, to_release__isnull=False)
        .values_list("from_release_id", "to_release_id")
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


def covers_every_version(versions: list[dict[str, Any]]) -> bool:
    """Whether a lifecycle event's ``versions`` scope is every version, such as ``vers:generic/*``."""
    if not versions:
        return True
    return any(str(entry.get("range", "")).strip().endswith("/*") for entry in versions if isinstance(entry, dict))


def fold_dates(events: Iterable[BaseCLEEvent]) -> tuple[date | None, date | None]:
    """End of support and end of life from one entity's surviving events, read in event order.

    Per support policy the latest ``endOfSupport`` event wins, so a correction
    replaces the earlier date even when it moves it earlier; the result is the
    latest across policies, so a later event under one policy never cuts
    another short. End of life is the latest ``endOfLife`` event.
    """
    support_ends: dict[str, date] = {}
    end_of_life: date | None = None
    for event in events:
        if event.event_type == CLEEventType.END_OF_SUPPORT:
            support_ends[event.support_id] = event.effective.date()
        elif event.event_type == CLEEventType.END_OF_LIFE:
            end_of_life = event.effective.date()
    return max(support_ends.values(), default=None), end_of_life


def _surviving(events: list[Any]) -> list[Any]:
    """Drop the events a ``withdrawn`` event names. ``events`` belong to one entity."""
    voided = {
        event.withdrawn_event_id
        for event in events
        if event.event_type == CLEEventType.WITHDRAWN and event.withdrawn_event_id is not None
    }
    return [event for event in events if event.event_id not in voided]


def recompute_release_lifecycle(product: Product) -> None:
    """Derive every release's lifecycle columns in ``product`` from its edges and CLE events.

    Product-wide, because withdrawing a successor changes its predecessors and
    a product date applies to every release without one of its own.

    - ``end_of_support`` and ``end_of_life``: the release's own events, folded
      by ``fold_dates``.
    - ``effective_end_of_support`` and ``effective_end_of_life``: the
      release's own date, else the product's from events that cover every
      version. Read from events, never from the product columns, so the order
      events were posted in, or a column written another way, cannot change
      what is monitored.
    - ``superseded_at``: the earliest live drop-in edge whose line still goes
      on: its successor is outside sbomify, not withdrawn, or itself replaced
      by a release that carries the line on. Withdrawing every release after
      one rolls the line back to it. Edges that start a new line never retire
      anything, however many a release has.

    Writes only the rows that changed, and never through ``save()``.
    """
    releases = {release.pk: release for release in Release.objects.filter(product_id=product.pk)}

    by_release: dict[str, list[ReleaseCLEEvent]] = defaultdict(list)
    for event in ReleaseCLEEvent.objects.filter(release__product_id=product.pk).order_by("release_id", "event_id"):
        by_release[event.release_id].append(event)
    own = {pk: fold_dates(_surviving(by_release[pk])) for pk in releases}

    product_events = _surviving(list(ProductCLEEvent.objects.filter(product_id=product.pk).order_by("event_id")))
    product_support, product_life = fold_dates(
        event for event in product_events if covers_every_version(event.versions)
    )

    drop_ins: dict[str, list[ReleaseSupersession]] = defaultdict(list)
    for edge in ReleaseSupersession.objects.live().filter(from_release__product_id=product.pk, drop_in=True):
        drop_ins[edge.from_release_id].append(edge)

    def carries_on(release_id: str | None, seen: set[str]) -> bool:
        successor = releases.get(release_id) if release_id else None
        # No successor in sbomify: outside it, or deleted. It still counts.
        if successor is None or successor.withdrawn_at is None:
            return True
        if successor.pk in seen:
            return False
        seen.add(successor.pk)
        return any(carries_on(edge.to_release_id, seen) for edge in drop_ins.get(successor.pk, ()))

    superseded: dict[str, datetime] = {}
    for source, edges in drop_ins.items():
        moved_on = [edge.effective for edge in edges if carries_on(edge.to_release_id, set())]
        if moved_on:
            superseded[source] = min(moved_on)

    fields = ("superseded_at", "end_of_support", "end_of_life", "effective_end_of_support", "effective_end_of_life")
    changed = []
    for pk, release in releases.items():
        end_of_support, end_of_life = own[pk]
        derived = (
            superseded.get(pk),
            end_of_support,
            end_of_life,
            end_of_support or product_support,
            end_of_life or product_life,
        )
        if tuple(getattr(release, field) for field in fields) != derived:
            for field, value in zip(fields, derived, strict=True):
                setattr(release, field, value)
            changed.append(release)
    if changed:
        Release.objects.bulk_update(changed, fields)


def save_release_changes(release_id: str, changes: dict[str, Any]) -> ServiceResult[tuple[Release, bool]]:
    """Write a person's edit to a release, under the product lock and then the release lock.

    That is the order every lifecycle writer takes, so an edit cannot deadlock
    against a withdrawal or a CLE event. Only the fields that changed are
    written, from the locked row, so an edit never puts back a withdrawal or
    a derived date committed after the caller first read the release.

    Moving the release date moves the live edges that took their date from it,
    and a new name or version links the edges declared before it existed.
    Call inside a transaction; a duplicate name or version raises
    ``IntegrityError``. The value is the saved release and whether anything
    changed.
    """
    product_id = Release.objects.filter(pk=release_id).values_list("product_id", flat=True).first()
    product = Product.objects.select_for_update().filter(pk=product_id).first() if product_id else None
    release = (
        Release.objects.select_for_update(of=("self",)).select_related("product").filter(pk=release_id).first()
        if product
        else None
    )
    if product is None or release is None:
        return ServiceResult.failure("Release not found", status_code=404)

    changed = [field for field, value in changes.items() if getattr(release, field) != value]
    if not changed:
        return ServiceResult.success((release, False))

    previous_release_date = release.released_at
    for field in changed:
        setattr(release, field, changes[field])
    release.save(update_fields=changed)

    if "released_at" in changed and previous_release_date is not None:
        moved = (
            ReleaseSupersession.objects.live()
            .filter(to_release=release, effective=previous_release_date)
            .update(effective=release.released_at)
        )
        if moved:
            recompute_release_lifecycle(product)
    if {"name", "version"} & set(changed):
        linked = link_pending_supersessions(release)
        if not linked.ok:
            return ServiceResult.failure(linked.error or "Invalid supersession", status_code=linked.status_code)
    return ServiceResult.success((release, True))


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
    """One structured line per lifecycle decision a person or a pipeline makes, once it commits.

    A decision that rolls back leaves no line, so the trail never records what
    did not happen.
    """
    extra = {
        "action": action,
        "release_id": release.pk,
        "product_id": release.product_id,
        "actor_id": actor_id,
        **detail,
    }
    transaction.on_commit(lambda: audit_log.info("release_lifecycle %s", json.dumps(extra, default=str), extra=extra))
