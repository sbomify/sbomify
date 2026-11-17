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
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q, QuerySet
from django.utils import timezone

from sbomify.apps.core.models import (
    LATEST_RELEASE_NAME,
    Component,
    Product,
    Release,
    ReleaseArtifact,
    ReleaseLink,
    ReleaseSupersession,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import broadcast_to_workspace
from sbomify.apps.sboms.models import SBOM, BaseCLEEvent, CLEEventType, ProductCLEEvent, ReleaseCLEEvent

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


def shipping_releases(now: datetime | None = None, team_id: Any = None) -> QuerySet[Release]:
    """The releases whose SBOMs sbomify tracks: the tracked releases and every release they link to.

    A linked release's SBOMs are part of the linking release's aggregate SBOM,
    so a live release keeps them tracked even when the linked release is itself
    retired. A retired release's links keep nothing alive. Links never cross
    workspaces, so ``team_id`` limits the walk to one without changing the answer.
    """
    releases = Release.objects.all() if team_id is None else Release.objects.filter(product__team_id=team_id)
    tracked = tracked_releases(releases, now=now).values("pk")
    return Release.objects.filter(Q(pk__in=tracked) | Q(pk__in=releases_linked_from(tracked)))


def tracked_sboms(sboms: QuerySet[SBOM] | None = None, team_id: Any = None) -> QuerySet[SBOM]:
    """The SBOMs sbomify still scans and keeps active in Dependency-Track.

    The newest of each format per component, and every one a live release ships
    (``shipping_releases``). The scheduled scans, the VEX live pass, the
    Dependency-Track reconcile and the retired-release notice all read this, so
    they cannot disagree about an SBOM. Ties on ``created_at`` go to the higher
    id. ``team_id`` limits the release walk to one workspace.
    """
    newer = SBOM.objects.filter(
        Q(created_at__gt=OuterRef("created_at")) | Q(created_at=OuterRef("created_at"), id__gt=OuterRef("id")),
        component_id=OuterRef("component_id"),
        format=OuterRef("format"),
        bom_type=SBOM.BomType.SBOM,
    )
    shipped = ReleaseArtifact.objects.filter(
        sbom_id=OuterRef("pk"),
        # Defense in depth: links never cross workspaces, and neither may this.
        release__product__team_id=OuterRef("component__team_id"),
        release__in=shipping_releases(team_id=team_id),
    )
    sboms = SBOM.objects.all() if sboms is None else sboms
    return sboms.filter(bom_type=SBOM.BomType.SBOM).filter(~Exists(newer) | Exists(shipped))


def reconcile_after_removal(release_ids: Iterable[Any]) -> None:
    """Queue, for once a delete of these releases commits, the sync of their workspace's Dependency-Track tree.

    The releases they link to lose a reason to stay tracked. Links never cross
    workspaces, so one sync covers them. Call before the delete, while the
    releases still exist.
    """
    from sbomify.apps.vulnerability_scanning.services.dt_release_tree import queue_sync

    for team_id in set(Release.objects.filter(pk__in=list(release_ids)).values_list("product__team_id", flat=True)):
        queue_sync(team_id)


def broadcast_releases_updated(product: Product, releases: Iterable[Release]) -> None:
    """Tell the workspace, once the transaction commits, that these releases moved.

    A write to one release can move others: withdrawing a successor hands its
    predecessor back, and a link shows on the pages of both its releases. Each
    page and list showing a release listens for ``release_updated`` on its ID.
    """
    workspace_key = product.team.key
    if not workspace_key:
        return
    for release in releases:
        data = {"release_id": str(release.pk), "product_id": str(product.pk), "name": release.name}
        transaction.on_commit(
            partial(broadcast_to_workspace, workspace_key=workspace_key, message_type="release_updated", data=data)
        )


def backdated_takeover(predecessor: Release, successor: Release) -> str | None:
    """Why ``successor`` cannot take over ``predecessor``'s line, or None when the dates allow it.

    A release cannot replace one that came out after it on the same line:
    a backdated entry would retire the current release the moment it was saved.
    Either date can still be the bare timestamp an edit sent, which ``save()``
    has not made aware yet, so both are read the way it will read them.
    """
    successor_date = Release._as_aware(successor.released_at)
    predecessor_date = Release._as_aware(predecessor.released_at)
    if successor_date and predecessor_date and successor_date < predecessor_date:
        return (
            f"Release {predecessor.name} was released after {successor.name}, so {successor.name} cannot "
            "replace it on the same line. Choose a new line, or check the release dates."
        )
    return None


def replacement_candidates(product_id: str) -> list[Release]:
    """The releases a new release of the product can supersede: named, still monitored, newest first."""
    return list(tracked_releases(Release.objects.filter(product_id=product_id, is_latest=False)))


def replace_choices(product_id: str, release_ids: Iterable[str]) -> dict[str, Any]:
    """What the edit dialog offers a release to replace, and the releases each of ``release_ids`` replaces now.

    The options are the ones the new-release form offers. A release this one
    already replaces on the same line is no longer monitored, so it is not
    among them; the dialog adds a release's own predecessors back.
    """
    replaces: dict[str, list[dict[str, Any]]] = defaultdict(list)
    edges = ReleaseSupersession.objects.live().select_related("from_release")
    for edge in edges.filter(to_release_id__in=list(release_ids)).order_by("pk"):
        replaces[str(edge.to_release_id)].append(
            {"id": edge.from_release_id, "name": edge.from_release.name, "drop_in": edge.drop_in}
        )
    return {
        "options": [{"id": release.pk, "name": release.name} for release in replacement_candidates(product_id)],
        "replaces": dict(replaces),
    }


def _predecessor_for(successor: Release, item: Any) -> ServiceResult[Release]:
    """The release a ``supersedes`` item names: by ID within the workspace, or by version then name."""
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
        return ServiceResult.success(predecessor)
    predecessor = _sibling_named(successor.product_id, item.version)
    if predecessor is None:
        return ServiceResult.failure(f"This product has no release {item.version}.", status_code=400)
    return ServiceResult.success(predecessor)


def undeclared_supersedes(successor: Release, items: Iterable[Any]) -> ServiceResult[list[str]]:
    """The ``supersedes`` items that ``successor`` does not already replace with a live edge on the same line.

    A create that finds the release already exists may only confirm what is
    there. It never writes edges onto a release someone else made, so a name
    typed by mistake cannot retire the release the form had preselected.
    """
    missing = []
    for item in items:
        found = _predecessor_for(successor, item)
        if not found.ok or found.value is None:
            return ServiceResult.failure(found.error or "Invalid supersession", status_code=found.status_code)
        predecessor = found.value
        if (
            not ReleaseSupersession.objects.live()
            .filter(from_release=predecessor, to_release=successor, drop_in=item.drop_in)
            .exists()
        ):
            # A live edge on the other line is a conflict, in the words declaring it would get.
            other_line = existing_supersession(predecessor, successor.version or successor.name, item.drop_in)
            if not other_line.ok:
                return ServiceResult.failure(other_line.error or "Conflicting supersession", other_line.status_code)
            missing.append(predecessor.name)
    return ServiceResult.success(missing)


_UNTRACKED_REASONS = {
    Release.LifecycleState.WITHDRAWN: "It was withdrawn",
    Release.LifecycleState.END_OF_LIFE: "It reached end of life",
    Release.LifecycleState.END_OF_SUPPORT: "Its support ended",
    Release.LifecycleState.SUPERSEDED: "A newer release replaced it",
    Release.LifecycleState.ARCHIVED: "It was archived",
}


def _shipped_sboms(release_ids: list[Any], *, public_only: bool) -> dict[Any, set[str]]:
    """The SBOMs each release's counts include: its workspace's, or the public ones for a Trust Center posture."""
    artifacts = ReleaseArtifact.objects.filter(release_id__in=release_ids, sbom__bom_type=SBOM.BomType.SBOM)
    if public_only:
        artifacts = artifacts.filter(sbom__component__visibility=Component.Visibility.PUBLIC)
    else:
        # A component transferred to another workspace leaves its artifacts behind, and the counts skip them.
        artifacts = artifacts.filter(sbom__component__team_id=F("release__product__team_id"))
    shipped: dict[Any, set[str]] = defaultdict(set)
    for release_id, sbom_id in artifacts.values_list("release_id", "sbom_id"):
        shipped[release_id].add(sbom_id)
    return shipped


def still_scanned_release_ids(release_ids: Iterable[str], team_id: Any, *, public_only: bool = False) -> set[str]:
    """Of these releases, those whose counts sbomify still keeps current, whatever their own state.

    A live release that ships or links to one keeps it scanned, and so does a
    release every SBOM of which sbomify scans anyway (``tracked_sboms``, the
    set the scheduled scans cover). One SBOM it alone ships is enough to leave
    it out, since that SBOM's counts stop moving. ``public_only`` weighs only
    the SBOMs of public components, the ones a Trust Center posture counts.
    """
    release_ids = list(release_ids)
    if not release_ids:
        return set()
    still = set(shipping_releases(team_id=team_id).filter(pk__in=release_ids).values_list("pk", flat=True))

    shipped = _shipped_sboms(release_ids, public_only=public_only)
    candidates = set().union(*shipped.values())
    if candidates:
        tracked = set(
            tracked_sboms(SBOM.objects.filter(pk__in=candidates), team_id=team_id).values_list("pk", flat=True)
        )
        still |= {release_id for release_id, sboms in shipped.items() if sboms <= tracked}
    return still


def untracked_notice(release: Release, *, public_only: bool = False) -> dict[str, Any] | None:
    """Why sbomify stopped scanning a release, with that reason's own date, or ``None`` while it still does.

    Its counts are as old as its last scan, which the page prints beside this.
    Several things can retire a release, so this names the first that
    happened: a release replaced in June whose support then ended in January
    went in June. The date belongs to the reason, never to when the scans
    stopped: a support date already past on the day it took effect would say
    the scans stopped before the last scan ran.

    When some of its SBOMs are still scanned, as another release's or as
    their component's newest, ``stopped`` and ``sboms`` say how many of them
    did stop, so the page does not call every count frozen.
    """
    if release.lifecycle_state == Release.LifecycleState.ACTIVE:
        return None
    if release.pk in still_scanned_release_ids([release.pk], release.product.team_id, public_only=public_only):
        return None

    now = timezone.now()
    today = timezone.localdate(now)
    end_of_life = release.effective_end_of_life
    end_of_support = release.effective_end_of_support

    def day(moment: datetime | None) -> date | None:
        return timezone.localdate(moment) if moment and moment <= now else None

    # Ties go to the first, the order lifecycle_state ranks them in.
    stopped = [
        (day(release.withdrawn_at), Release.LifecycleState.WITHDRAWN),
        (end_of_life if end_of_life and end_of_life < today else None, Release.LifecycleState.END_OF_LIFE),
        (end_of_support if end_of_support and end_of_support < today else None, Release.LifecycleState.END_OF_SUPPORT),
        (day(release.superseded_at), Release.LifecycleState.SUPERSEDED),
        (day(release.archived_at), Release.LifecycleState.ARCHIVED),
    ]
    passed = [(on, state) for on, state in stopped if on is not None]
    if not passed:
        return None
    on, state = min(passed, key=lambda item: item[0])
    notice: dict[str, Any] = {"on": on, "reason": _UNTRACKED_REASONS[state]}
    shipped = _shipped_sboms([release.pk], public_only=public_only)[release.pk]
    scanned = tracked_sboms(SBOM.objects.filter(pk__in=shipped), team_id=release.product.team_id).count()
    if scanned:
        notice.update(stopped=len(shipped) - scanned, sboms=len(shipped))
    return notice


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

    successor_version = successor.version or successor.name
    for item in items:
        found = _predecessor_for(successor, item)
        if not found.ok or found.value is None:
            return ServiceResult.failure(found.error or "Invalid supersession", status_code=found.status_code)
        predecessor = found.value

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
            queue_reconcile=False,
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
    if items:
        after_lifecycle_change(successor.product_id)
    return ServiceResult.success(None)


def remove_supersession(release_id: str, edge_id: str, *, actor_id: Any = None) -> ServiceResult[ReleaseSupersession]:
    """Withdraw one live edge into or out of ``release_id``, so a mistaken Replaces can be undone.

    It goes through the CLE ``withdrawn`` path, so the published lifecycle
    records the correction and the history keeps the edge. The caller checks
    that the person can manage the release.
    """
    # cle.py imports this module for the edge rules.
    from sbomify.apps.core.services.cle import create_release_cle_event

    # Read under the product lock: a release-date edit republishes the edge
    # under it, and an edge read first would withdraw its old event.
    with transaction.atomic():
        product_id = Release.objects.filter(pk=release_id).values_list("product_id", flat=True).first()
        Product.objects.select_for_update().filter(pk=product_id).first()
        edge = (
            ReleaseSupersession.objects.live()
            .select_related("from_release", "cle_event")
            .filter(Q(from_release_id=release_id) | Q(to_release_id=release_id), pk=edge_id)
            .first()
        )
        if edge is None or edge.cle_event is None:
            return ServiceResult.failure("That link no longer exists.", status_code=404)
        result = create_release_cle_event(
            edge.from_release,
            CLEEventType.WITHDRAWN,
            timezone.now(),
            withdrawn_event_id=edge.cle_event.event_id,
            actor_id=actor_id,
        )
        if not result.ok:
            return ServiceResult.failure(
                result.error or "The link could not be removed.", status_code=result.status_code
            )
        edge.refresh_from_db()
    return ServiceResult.success(edge)


def set_supersedes(successor: Release, items: Iterable[Any], *, actor_id: Any = None) -> ServiceResult[bool]:
    """Make ``items`` every release ``successor`` supersedes, and say whether any link changed.

    A live link the items leave out is withdrawn, as Remove link does, and the
    rest are declared. Withdrawing comes first, so moving a link to the other
    line is not refused as a conflict with itself. Run it inside the
    transaction that owns the edit: a failure leaves the caller to roll back.
    """
    items = list(items)
    wanted = set()
    for item in items:
        found = _predecessor_for(successor, item)
        if not found.ok or found.value is None:
            return ServiceResult.failure(found.error or "Invalid supersession", status_code=found.status_code)
        wanted.add((found.value.pk, item.drop_in))
    live = list(ReleaseSupersession.objects.live().filter(to_release=successor))
    for edge in live:
        if (edge.from_release_id, edge.drop_in) not in wanted:
            removed = remove_supersession(successor.pk, edge.pk, actor_id=actor_id)
            if not removed.ok:
                return ServiceResult.failure(removed.error or "Invalid supersession", status_code=removed.status_code)
    declared = declare_supersedes(successor, items, actor_id=actor_id)
    if not declared.ok:
        return ServiceResult.failure(declared.error or "Invalid supersession", status_code=declared.status_code)
    return ServiceResult.success({(edge.from_release_id, edge.drop_in) for edge in live} != wanted)


def supersession_links(release_id: str) -> dict[str, list[ReleaseSupersession]]:
    """The live edges into and out of a release: every release it replaces, and every successor it has."""
    edges = ReleaseSupersession.objects.live().select_related("from_release", "to_release")
    return {
        "predecessors": list(edges.filter(to_release_id=release_id)),
        "successors": list(edges.filter(from_release_id=release_id)),
    }


def recently_retired_releases(days: int, now: datetime | None = None) -> QuerySet[Release]:
    """Named releases a date retired within the last ``days`` days.

    A support date, an end of life or a supersession dated ahead retires a
    release with no write to hang a reconcile on, so the daily sweep reads
    these. A withdrawal, an archive or a new edge reconciles as it is written.
    Dates are the ``effective_*`` columns ``tracked_releases`` reads: a
    release's own, else its product's for every version. A date is the last
    supported day.
    """
    now = now or timezone.now()
    today = now.date()
    since = today - timedelta(days=days)
    # From midnight, as the dates count: a rolling cutoff would lose an edge
    # that took effect minutes after a run once the next day's run is missed.
    since_midnight = datetime.combine(since, datetime.min.time(), tzinfo=now.tzinfo)
    passed = (
        Q(effective_end_of_support__gte=since, effective_end_of_support__lt=today)
        | Q(effective_end_of_life__gte=since, effective_end_of_life__lt=today)
        | Q(superseded_at__gte=since_midnight, superseded_at__lte=now)
    )
    return Release.objects.filter(passed, is_latest=False)


def existing_supersession(
    predecessor: Release, successor_label: str, drop_in: bool
) -> ServiceResult[ReleaseSupersession | None]:
    """The live edge to ``successor_label`` a retry would repeat, or a conflict when it is on the other line.

    One live edge per successor, whether it was named by its version or by its
    name. A retry with another date is the same edge, so a pipeline re-run or a
    corrected release date never fails a build that changed nothing. Moving it
    to the other line means removing the link and declaring it again, so the
    history keeps both.
    """
    same = Q(successor_label=successor_label)
    if (target := _sibling_named(predecessor.product_id, successor_label)) is not None:
        same |= Q(to_release=target)
    edge = ReleaseSupersession.objects.live().filter(same, from_release=predecessor).first()
    if edge is None or edge.drop_in == drop_in:
        return ServiceResult.success(edge)
    line = "the same line" if edge.drop_in else "a new line"
    return ServiceResult.failure(
        f"Release {predecessor.name} already names {edge.successor_label} as {line}. "
        "Remove that link first to change it.",
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
    # Checked by name, not by lookup: the latest release is made the first time
    # it is needed, so before then "latest" would pass as a successor outside sbomify.
    if superseded_by_version == LATEST_RELEASE_NAME:
        return ServiceResult.failure("The latest release cannot supersede another release.", status_code=400)

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
    cycle, or a rename onto a successor the release names itself, so the
    caller rolls the rename back. Linked edges stay linked when a release is
    renamed again: the edge resolved to that release. A predecessor keeps one
    live edge per successor, so a second name for the same release is a 409.
    Rederives the product's lifecycle columns either way, so a new release
    takes the product's dates.
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
        .select_related("from_release")
    )
    linked = []
    for edge in pending:
        target = _sibling_named(release.product_id, edge.successor_label)
        if target is None or target.pk != release.pk:
            continue
        if edge.from_release_id == release.pk:
            return ServiceResult.failure(
                f"Release {release.name} names {edge.successor_label} as its successor, "
                "so it cannot take that name itself. A release cannot supersede itself.",
                status_code=400,
            )
        if _leads_back(release, edge.from_release):
            return ServiceResult.failure(
                f"Release {edge.from_release.name} names {edge.successor_label} as a successor, and "
                f"{release.name} already leads back to {edge.from_release.name}, so this would make a cycle.",
                status_code=400,
            )
        if edge.drop_in and (backdated := backdated_takeover(edge.from_release, release)):
            return ServiceResult.failure(backdated, status_code=400)
        if ReleaseSupersession.objects.live().filter(from_release_id=edge.from_release_id, to_release=release).exists():
            return ServiceResult.failure(
                f"Release {edge.from_release.name} already names {release.name} as a successor, so "
                f"{edge.successor_label} cannot point at it too. Remove one of the links first.",
                status_code=409,
            )
        ReleaseSupersession.objects.filter(pk=edge.pk).update(to_release=release)
        linked.append(edge.from_release)
    recompute_release_lifecycle(product)
    broadcast_releases_updated(product, linked)
    if linked:
        # Linking can revive a predecessor: its successor was a label, and is now a withdrawn release.
        after_lifecycle_change(product.pk)
    return ServiceResult.success(len(linked))


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


def product_dates(events: list[ProductCLEEvent]) -> tuple[date | None, date | None]:
    """A product's end of support and end of life: its surviving events for every version, folded by ``fold_dates``.

    The product columns and what its releases inherit both come from here, so
    the two always agree. ``events`` are one product's, in event order.
    """
    return fold_dates(event for event in _surviving(events) if covers_every_version(event.versions))


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
    - ``superseded_at``: the earliest time a live drop-in edge's line goes
      on: its successor is outside sbomify, not withdrawn, or itself replaced
      by a release that carries the line on. Past a withdrawn release the line
      moves on only once every edge on the way has taken effect. Withdrawing
      every release after one rolls the line back to it. Edges that start a
      new line never retire anything, however many a release has.

    Writes only the rows that changed, and never through ``save()``.
    """
    releases = {release.pk: release for release in Release.objects.filter(product_id=product.pk)}

    by_release: dict[str, list[ReleaseCLEEvent]] = defaultdict(list)
    for event in ReleaseCLEEvent.objects.filter(release__product_id=product.pk).order_by("release_id", "event_id"):
        by_release[event.release_id].append(event)
    own = {pk: fold_dates(_surviving(by_release[pk])) for pk in releases}

    product_support, product_life = product_dates(
        list(ProductCLEEvent.objects.filter(product_id=product.pk).order_by("event_id"))
    )

    drop_ins: dict[str, list[ReleaseSupersession]] = defaultdict(list)
    for edge in ReleaseSupersession.objects.live().filter(from_release__product_id=product.pk, drop_in=True):
        drop_ins[edge.from_release_id].append(edge)

    # When the line goes on past each withdrawn release, worked out once per
    # release: walked per path, a web of them doubled the work with every layer.
    onward_from: dict[str, datetime | None] = {}

    def withdrawn_successor(edge: ReleaseSupersession) -> Release | None:
        # No successor in sbomify, outside it or deleted, counts like a live one.
        successor = releases.get(edge.to_release_id) if edge.to_release_id else None
        return successor if successor is not None and successor.withdrawn_at is not None else None

    def moves_on(edge: ReleaseSupersession) -> datetime | None:
        """When the line through ``edge`` goes on, or None when nothing live carries it."""
        successor = withdrawn_successor(edge)
        if successor is None:
            return edge.effective
        later = onward_from.get(successor.pk)
        return max(edge.effective, later) if later is not None else None

    def work_out(start: str) -> None:
        """Fill ``onward_from`` for ``start`` and every withdrawn release past it, deepest first.

        A stack rather than recursion: a long line of withdrawn releases passed
        Python's recursion limit. A release still being worked out reads as
        None, so a cycle the edge checks let through ends there.
        """
        stack, entered = [start], set()
        while stack:
            pk = stack[-1]
            if pk in entered:
                stack.pop()
                onward = [when for after in drop_ins.get(pk, ()) if (when := moves_on(after)) is not None]
                onward_from[pk] = min(onward) if onward else None
                continue
            entered.add(pk)
            for after in drop_ins.get(pk, ()):
                successor = withdrawn_successor(after)
                if successor is not None and successor.pk not in onward_from and successor.pk not in entered:
                    stack.append(successor.pk)

    superseded: dict[str, datetime] = {}
    for source, edges in drop_ins.items():
        for edge in edges:
            if (successor := withdrawn_successor(edge)) is not None and successor.pk not in onward_from:
                work_out(successor.pk)
        moved_on = [when for edge in edges if (when := moves_on(edge)) is not None]
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
        broadcast_releases_updated(product, changed)
        broadcast_dependents([release.pk for release in changed])


def broadcast_dependents(release_ids: list[Any]) -> None:
    """Once this commits, tell the releases whose monitoring these releases decide.

    A live release keeps the releases it links on monitored, and with them the
    releases shipping their SBOMs, so moving a release in or out of its
    lifecycle moves what their pages say. The releases themselves are not
    told again.
    """

    def send() -> None:
        reached = {*release_ids, *releases_linked_from(release_ids)}
        shipped = ReleaseArtifact.objects.filter(release_id__in=reached, sbom__isnull=False).values("sbom_id")
        moved = (
            Release.objects.filter(Q(pk__in=reached) | Q(artifacts__sbom_id__in=shipped))
            .exclude(pk__in=release_ids)
            .select_related("product__team")
            .distinct()
        )
        for release in moved:
            broadcast_releases_updated(release.product, [release])

    transaction.on_commit(send, robust=True)


def _after_commit(func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Call ``func`` once the transaction commits. An error there is logged: the write already stands."""

    def call() -> None:
        func(*args, **kwargs)

    transaction.on_commit(call, robust=True)


def _same_value(stored: Any, sent: Any) -> bool:
    """Whether a value an edit sends is the one the release already has.

    A date sent without an offset is read the way ``Release.save()`` reads it.
    Dates are compared to the second, because the API answers them to the
    second: a client sending back the date it read is not moving it.
    """
    sent = Release._as_aware(sent)
    if isinstance(stored, datetime) and isinstance(sent, datetime):
        return stored.replace(microsecond=0) == sent.replace(microsecond=0)
    return bool(stored == sent)


def save_release_changes(release_id: str, changes: dict[str, Any]) -> ServiceResult[tuple[Release, bool]]:
    """Write a person's edit to a release, under the product lock and then the release lock.

    That is the order every lifecycle writer takes, so an edit cannot deadlock
    against a withdrawal or a CLE event. Only the fields that changed are
    written, from the locked row, so an edit never puts back a withdrawal or
    a derived date committed after the caller first read the release.

    Moving the release date moves the live edges that took their date from it,
    and publishes each again at the new date; clearing it leaves them where
    they are. A date that would put a drop-in successor before its predecessor
    is refused, as declaring that edge would be. A new name or version links the edges declared before it existed.
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

    changed = [field for field, value in changes.items() if not _same_value(getattr(release, field), value)]
    if not changed:
        return ServiceResult.success((release, False))

    previous_release_date = release.released_at
    for field in changed:
        setattr(release, field, changes[field])
    if "released_at" in changed:
        drop_ins = ReleaseSupersession.objects.live().filter(drop_in=True).select_related("from_release", "to_release")
        for edge in drop_ins.filter(Q(to_release=release) | Q(from_release=release, to_release__isnull=False)):
            predecessor = release if edge.from_release_id == release.pk else edge.from_release
            successor = release if edge.to_release_id == release.pk else edge.to_release
            if successor is not None and (backdated := backdated_takeover(predecessor, successor)):
                return ServiceResult.failure(backdated, status_code=400)
    release.save(update_fields=changed)

    if "released_at" in changed and previous_release_date is not None and release.released_at is not None:
        from sbomify.apps.core.services.cle import republish_supersession

        moved = list(
            ReleaseSupersession.objects.live()
            .filter(to_release=release, effective=previous_release_date)
            .select_related("cle_event", "from_release")
        )
        for edge in moved:
            edge.effective = release.released_at
            edge.save(update_fields=["effective"])
            republished = republish_supersession(edge)
            if not republished.ok:
                return ServiceResult.failure(republished.error or "Invalid supersession", republished.status_code)
        if moved:
            recompute_release_lifecycle(product)
            after_lifecycle_change(product.pk)
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
        after_lifecycle_change(product.pk)

    locked.refresh_from_db()
    return ServiceResult.success(locked)


def after_lifecycle_change(product_id: Any) -> None:
    """Once the write commits, bring Dependency-Track in line with where the product's releases now stand.

    A broker error after the commit is logged, not raised: the write stands,
    and the daily ``dt_tracked_scope`` sweep, which syncs every workspace's
    tree, repairs what the lost message would have done.
    """
    from sbomify.apps.vulnerability_scanning.services.dt_release_tree import queue_sync

    queue_sync(Product.objects.filter(pk=product_id).values_list("team_id", flat=True).first())


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
