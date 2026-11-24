"""Checking a TEA subscription against the server it follows.

A check claims the subscription's lease, reads everything it needs from the
server, then writes once, in one transaction, under that lease. A worker whose
lease ran out writes nothing, so two workers never both record a check.

What a check reads:

- the component, and every release the server lists for it;
- the latest collection and the lifecycle of each watched release: the newest
  release, the releases picked in the wizard, and any release with an artifact
  pinned in a product release;
- each pinned artifact revision, fetched directly, to see whether it is gone or
  changed. Pins only in archived or withdrawn product releases are read daily.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any, TypeVar

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from libtea import TeaClient
from libtea.exceptions import TeaConnectionError, TeaError, TeaNotFoundError, TeaServerError
from libtea.models import CLE, Artifact, Collection, Component, Release

from sbomify.apps.core.domain.exceptions import DomainError, ExternalServiceError
from sbomify.apps.core.models import ReleaseArtifact
from sbomify.apps.core.services.release_lifecycle import _surviving, fold_dates
from sbomify.apps.sboms.models import CLEEventType
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease, TeaSubscription, TeaSubscriptionEvent
from sbomify.apps.tea.pins import repoint_latest_pins
from sbomify.apps.tea.services.remote import RemoteServer, identifiers

log = logging.getLogger(__name__)

# Past the check task's own time limit, so a lease still standing belongs to a worker that is gone.
LEASE = timedelta(minutes=16)
HEALTHY_INTERVAL = timedelta(hours=1)
MAX_INTERVAL = timedelta(hours=24)
# The cron runs at :41. A check finishing at 12:41:05 would not be due at 13:41:00 without this.
CRON_SLACK = timedelta(minutes=10)
COLD_PIN_INTERVAL = timedelta(hours=24)
ERROR_LENGTH = 1000

_T = TypeVar("_T")
Event = TeaSubscriptionEvent.Kind
State = TeaRemoteArtifact.State
Lifecycle = TeaRemoteRelease.Lifecycle


class CheckFailed(Exception):
    """A check that stopped before writing, with the status it leaves behind."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Fetched:
    component: Component
    releases: list[Release]
    head_uuid: str | None
    collections: dict[str, Collection | None] = field(default_factory=dict)
    cles: dict[str, CLE | None] = field(default_factory=dict)
    # A pinned revision read directly; None when the server no longer has it.
    pinned: dict[tuple[str, int], Artifact | None] = field(default_factory=dict)


def backoff(failures: int) -> timedelta:
    """Hourly after one failure, doubling to a day."""
    return min(HEALTHY_INTERVAL * (1 << min(failures, 5)), MAX_INTERVAL)


def fingerprint(artifact: Artifact) -> str:
    """What a revision publishes, as one value: each format's media type, URLs and checksums. Names are left out."""
    formats = sorted(
        json.dumps(
            [
                fmt.media_type or "",
                fmt.url or "",
                fmt.signature_url or "",
                sorted((str(c.algorithm_type), c.algorithm_value.lower()) for c in fmt.checksums),
            ]
        )
        for fmt in artifact.formats
    )
    return hashlib.sha256("\n".join(formats).encode()).hexdigest()


def lifecycle(cle: CLE | None, now: datetime) -> str:
    """Where a release stands by its own lifecycle events, read as sbomify reads its own releases."""
    if cle is None:
        return Lifecycle.ACTIVE
    events = _surviving(
        [
            SimpleNamespace(
                event_type=str(event.type),
                event_id=event.id,
                withdrawn_event_id=event.event_id,
                support_id=event.support_id or "",
                effective=event.effective,
            )
            for event in sorted(cle.events, key=lambda event: event.id)
        ]
    )
    if any(e.event_type == CLEEventType.END_OF_DISTRIBUTION and e.effective <= now for e in events):
        return Lifecycle.NO_LONGER_DISTRIBUTED
    end_of_support, end_of_life = fold_dates(events)
    today = now.date()
    if end_of_life is not None and end_of_life < today:
        return Lifecycle.END_OF_LIFE
    if end_of_support is not None and end_of_support < today:
        return Lifecycle.END_OF_SUPPORT
    return Lifecycle.ACTIVE


def claim(subscription_id: str, now: datetime, *, force: bool = False) -> datetime | None:
    """Take the subscription's lease if it is due (or forced) and free. Returns the lease, the write token."""
    lease = now + LEASE
    free = Q(lease_until__isnull=True) | Q(lease_until__lt=now)
    due = Q() if force else Q(next_check_at__lte=now)
    claimed = TeaSubscription.objects.filter(free, due, pk=subscription_id).update(lease_until=lease)
    return lease if claimed else None


def check(
    subscription_id: str,
    *,
    force: bool = False,
    client_for: Callable[[TeaSubscription], TeaClient] | None = None,
) -> TeaSubscription | None:
    """Check one subscription. Returns it as the check left it, or None when another check holds it or it isn't due."""
    now = timezone.now()
    lease = claim(subscription_id, now, force=force)
    if lease is None:
        return None
    subscription = TeaSubscription.objects.select_related("component").get(pk=subscription_id)
    build = client_for or _client
    try:
        with build(subscription) as client:
            fetched = fetch(subscription, client, now)
    except CheckFailed as failed:
        _record_failure(subscription_id, lease, failed.status, str(failed), now)
    except Exception:
        log.exception("TEA subscription %s check failed unexpectedly", subscription_id)
        _record_failure(subscription_id, lease, TeaSubscription.Status.ERROR, "The check failed unexpectedly.", now)
    else:
        apply(subscription_id, lease, fetched, now)
    return TeaSubscription.objects.select_related("latest_release").filter(pk=subscription_id).first()


def _client(subscription: TeaSubscription) -> TeaClient:
    try:
        return RemoteServer(subscription.api_base_url, subscription.spec_version).client()
    except Exception as exc:
        # A refused address is our own message; a name that no longer resolves is an unreachable server.
        status = TeaSubscription.Status.ERROR
        if isinstance(exc, ExternalServiceError):
            status = TeaSubscription.Status.UNREACHABLE
        message = str(exc) if isinstance(exc, DomainError) else "The server address can't be used."
        raise CheckFailed(status, message) from exc


def _optional(call: Callable[[], _T]) -> _T | None:
    try:
        return call()
    except TeaNotFoundError:
        return None


def _newest(releases: list[Release]) -> Release | None:
    """The newest release by release date, else creation date. Pre-releases count only if nothing else is listed."""
    finals = [r for r in releases if not r.pre_release] or releases
    return max(finals, key=lambda r: (r.release_date or r.created_date, r.created_date), default=None)


def fetch(subscription: TeaSubscription, client: TeaClient, now: datetime) -> Fetched:
    """Every network read a check needs. Writes nothing."""
    uuid = subscription.remote_component_uuid
    try:
        component = client.get_component(uuid)
        releases = client.get_component_releases(uuid)
        head = _newest(releases)
        fetched = Fetched(component=component, releases=releases, head_uuid=head.uuid if head else None)

        listed = {release.uuid for release in releases}
        watched = {fetched.head_uuid} if fetched.head_uuid else set()
        watched |= set(subscription.releases.filter(tracked=True).values_list("uuid", flat=True))
        revisions: set[tuple[str, int]] = set()
        for row in _pinned_rows(subscription, now):
            watched.add(row["release__uuid"])
            revisions.add((row["uuid"], row["version"]))

        for release_uuid in sorted(watched & listed):
            fetched.collections[release_uuid] = _optional(
                partial(client.get_component_release_collection_latest, release_uuid)
            )
            fetched.cles[release_uuid] = _optional(partial(client.get_component_release_cle, release_uuid))
        for artifact_uuid, version in sorted(revisions):
            fetched.pinned[(artifact_uuid, version)] = _optional(
                partial(client.get_artifact_version, artifact_uuid, version)
            )
    except TeaNotFoundError as exc:
        raise CheckFailed(TeaSubscription.Status.NOT_FOUND, "The server no longer lists this component.") from exc
    # What a server answered stays in the logs. Shown to users, it could carry another host's
    # response back out of sbomify's network if a name resolves somewhere else at connect time.
    except (TeaConnectionError, TeaServerError) as exc:
        log.info("TEA subscription %s: server unreachable: %s", subscription.pk, exc)
        raise CheckFailed(TeaSubscription.Status.UNREACHABLE, "The server did not answer.") from exc
    except TeaError as exc:
        log.info("TEA subscription %s: answer refused: %s", subscription.pk, exc)
        raise CheckFailed(TeaSubscription.Status.ERROR, "The server's answer is not valid TEA 1.0.") from exc
    return fetched


def _pinned_rows(subscription: TeaSubscription, now: datetime) -> list[dict[str, Any]]:
    """Pinned revisions this check reads: those in an active product release, and the rest once a day."""
    active = ReleaseArtifact.objects.filter(
        remote_artifact_id=OuterRef("pk"), release__archived_at__isnull=True, release__withdrawn_at__isnull=True
    )
    stale = now - COLD_PIN_INTERVAL
    pinned = TeaRemoteArtifact.objects.filter(release__subscription=subscription, pins__isnull=False).distinct()
    due = pinned.filter(Exists(active) | Q(release__checked_at__isnull=True) | Q(release__checked_at__lt=stale))
    return [dict(row) for row in due.values("uuid", "version", "release__uuid")]


def apply(subscription_id: str, lease: datetime, fetched: Fetched, now: datetime) -> None:
    """Record one check's reads, in one transaction, if this worker still holds the lease."""
    with transaction.atomic():
        subscription = TeaSubscription.objects.select_for_update().filter(pk=subscription_id, lease_until=lease).first()
        if subscription is None:
            log.warning("TEA subscription %s lost its lease before writing; dropping this check", subscription_id)
            return
        recorder = _Recorder(subscription, quiet=subscription.status == TeaSubscription.Status.PENDING)

        subscription.remote_name = fetched.component.name
        subscription.remote_identifiers = identifiers(fetched.component.identifiers)
        releases = _apply_releases(subscription, fetched, recorder, now)
        head = releases.get(fetched.head_uuid) if fetched.head_uuid else None

        covered: set[tuple[str, int]] = set()
        for release_uuid, collection in fetched.collections.items():
            row = releases[release_uuid]
            covered |= _apply_collection(row, collection, fetched.pinned, recorder, now)
            row.lifecycle = recorder.lifecycle(row, lifecycle(fetched.cles.get(release_uuid), now))
            row.checked_at = now
            row.save(update_fields=["collection_version", "lifecycle", "checked_at"])
        _apply_direct_reads(subscription, fetched.pinned, covered, recorder, now)

        subscription.latest_release = head
        was_failing = subscription.status not in (TeaSubscription.Status.OK, TeaSubscription.Status.PENDING)
        if was_failing:
            recorder.log(Event.CHECK_RECOVERED)
        subscription.status = TeaSubscription.Status.OK
        subscription.consecutive_failures = 0
        subscription.last_error = ""
        subscription.last_checked_at = subscription.last_success_at = now
        if recorder.events:
            subscription.last_changed_at = now
        subscription.next_check_at = now + HEALTHY_INTERVAL - CRON_SLACK
        subscription.lease_until = None
        subscription.save()
        TeaSubscriptionEvent.objects.bulk_create(recorder.events)
        # A latest release moves only when its pins differ from the head's current artifacts.
        repoint_latest_pins(subscription)


class _Recorder:
    """Collects a check's events. The first check of a subscription records none: everything would be new."""

    def __init__(self, subscription: TeaSubscription, *, quiet: bool) -> None:
        self.subscription = subscription
        self.quiet = quiet
        self.events: list[TeaSubscriptionEvent] = []

    def log(
        self,
        kind: str,
        release: TeaRemoteRelease | None = None,
        artifact: TeaRemoteArtifact | None = None,
        **detail: Any,
    ) -> None:
        if self.quiet:
            return
        self.events.append(
            TeaSubscriptionEvent(
                subscription=self.subscription, kind=kind, release=release, artifact=artifact, detail=detail
            )
        )

    def lifecycle(self, row: TeaRemoteRelease, new: str) -> str:
        if new != row.lifecycle:
            self.log(Event.LIFECYCLE_CHANGED, row, version=row.version, old=row.lifecycle, new=new)
        return new


def _apply_releases(
    subscription: TeaSubscription, fetched: Fetched, recorder: _Recorder, now: datetime
) -> dict[str, TeaRemoteRelease]:
    known = {row.uuid: row for row in subscription.releases.all()}
    listed = set()
    for remote in fetched.releases:
        listed.add(remote.uuid)
        values = {
            "version": remote.version,
            "created_date": remote.created_date,
            "release_date": remote.release_date,
            "pre_release": bool(remote.pre_release),
        }
        row = known.get(remote.uuid)
        if row is None:
            row = TeaRemoteRelease.objects.create(subscription=subscription, uuid=remote.uuid, **values)
            known[remote.uuid] = row
            recorder.log(Event.RELEASE_ADDED, row, version=remote.version)
            continue
        returned = row.gone_at is not None
        if returned:
            recorder.log(Event.RELEASE_ADDED, row, version=remote.version, returned=True)
        for name, value in values.items():
            setattr(row, name, value)
        row.gone_at = None
        row.save(update_fields=[*values, "gone_at"])
    for row in known.values():
        if row.uuid not in listed and row.gone_at is None:
            row.gone_at = now
            row.save(update_fields=["gone_at"])
            recorder.log(Event.RELEASE_REMOVED, row, version=row.version)
    return known


def _snapshot(artifact: Artifact) -> dict[str, Any]:
    """The artifact as the server sent it. Defaults it left out stay out: an empty checksum list is not TEA 1.0."""
    return artifact.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)


def _apply_collection(
    row: TeaRemoteRelease,
    collection: Collection | None,
    pinned: dict[tuple[str, int], Artifact | None],
    recorder: _Recorder,
    now: datetime,
) -> set[tuple[str, int]]:
    """Record a release's latest collection. Returns the revisions whose state it settled."""
    if collection is None:
        return set()
    if row.collection_version is not None and collection.version != row.collection_version:
        recorder.log(Event.COLLECTION_UPDATED, row, old=row.collection_version, new=collection.version)
    row.collection_version = collection.version

    listed = {(a.uuid, a.version or 1): a for a in collection.artifacts}
    listed_uuids = {uuid for uuid, _ in listed}
    existing: dict[tuple[str, int], list[TeaRemoteArtifact]] = defaultdict(list)
    for artifact in row.artifacts.all():
        existing[(artifact.uuid, artifact.version)].append(artifact)

    for key, remote in listed.items():
        fp = fingerprint(remote)
        if any(a.snapshot_fingerprint == fp for a in existing[key]):
            continue
        seen_before = bool(existing[key])
        new = TeaRemoteArtifact.objects.create(
            release=row,
            uuid=remote.uuid,
            version=key[1],
            name=remote.name or "",
            artifact_type=str(remote.type),
            snapshot=_snapshot(remote),
            snapshot_fingerprint=fp,
            live_fingerprint=fp,
        )
        existing[key].append(new)
        if not seen_before:
            recorder.log(Event.ARTIFACT_ADDED, row, new, name=new.name, version=new.version)

    changed: list[TeaRemoteArtifact] = []
    for key, rows in existing.items():
        for artifact in rows:
            state, live = _state(artifact, listed.get(key), pinned.get(key, _UNREAD), key[0] in listed_uuids)
            if _set_state(artifact, state, live, recorder, now):
                changed.append(artifact)
    TeaRemoteArtifact.objects.bulk_update(changed, ["state", "live_fingerprint", "state_changed_at"])
    return set(existing)


_UNREAD = object()
_STATE_EVENTS: dict[str, str] = {
    State.CHANGED: Event.ARTIFACT_CHANGED,
    State.REPLACED: Event.ARTIFACT_REPLACED,
    State.GONE: Event.ARTIFACT_GONE,
}


def _state(artifact: TeaRemoteArtifact, listed: Artifact | None, direct: object, uuid_listed: bool) -> tuple[str, str]:
    """Where a revision stands, first match wins."""
    if listed is not None:
        fp = fingerprint(listed)
        return (State.CURRENT if fp == artifact.snapshot_fingerprint else State.CHANGED), fp
    if direct is None:
        return State.GONE, ""
    if isinstance(direct, Artifact) and fingerprint(direct) != artifact.snapshot_fingerprint:
        return State.CHANGED, fingerprint(direct)
    if uuid_listed:
        return State.REPLACED, artifact.live_fingerprint
    return State.GONE, artifact.live_fingerprint


def _set_state(artifact: TeaRemoteArtifact, state: str, live: str, recorder: _Recorder, now: datetime) -> bool:
    if state == artifact.state and live == artifact.live_fingerprint:
        return False
    if state != artifact.state:
        if state in _STATE_EVENTS:
            recorder.log(_STATE_EVENTS[state], artifact.release, artifact, name=artifact.name, version=artifact.version)
        artifact.state = state
        artifact.state_changed_at = now
    artifact.live_fingerprint = live
    return True


def _apply_direct_reads(
    subscription: TeaSubscription,
    pinned: dict[tuple[str, int], Artifact | None],
    covered: set[tuple[str, int]],
    recorder: _Recorder,
    now: datetime,
) -> None:
    """Pinned revisions in releases whose collection was not read: settle them from the direct read alone."""
    changed = []
    for (uuid, version), direct in pinned.items():
        if (uuid, version) in covered:
            continue
        for artifact in TeaRemoteArtifact.objects.filter(
            release__subscription=subscription, uuid=uuid, version=version
        ).select_related("release"):
            if direct is None:
                state, live = State.GONE, ""
            else:
                fp = fingerprint(direct)
                state = State.CURRENT if fp == artifact.snapshot_fingerprint else State.CHANGED
                live = fp
            if _set_state(artifact, state, live, recorder, now):
                changed.append(artifact)
    TeaRemoteArtifact.objects.bulk_update(changed, ["state", "live_fingerprint", "state_changed_at"])


def _record_failure(subscription_id: str, lease: datetime, status: str, message: str, now: datetime) -> None:
    with transaction.atomic():
        subscription = TeaSubscription.objects.select_for_update().filter(pk=subscription_id, lease_until=lease).first()
        if subscription is None:
            return
        subscription.consecutive_failures += 1
        if subscription.consecutive_failures == 1:
            TeaSubscriptionEvent.objects.create(
                subscription=subscription, kind=Event.CHECK_FAILED, detail={"status": status, "error": message[:200]}
            )
        subscription.status = status
        subscription.last_error = message[:ERROR_LENGTH]
        subscription.last_checked_at = now
        subscription.next_check_at = now + backoff(subscription.consecutive_failures) - CRON_SLACK
        subscription.lease_until = None
        subscription.save()
