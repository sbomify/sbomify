"""Checking a subscription against a TEA server, with the server faked.

Each test arranges what the remote server publishes, runs a check, and reads
back what sbomify recorded: releases, artifact snapshots and states, events,
the schedule, and the pins of the product releases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone
from libtea.exceptions import TeaConnectionError, TeaNotFoundError
from libtea.models import CLE, Artifact, Collection, Component, Release

from sbomify.apps.core.models import Product, ReleaseArtifact
from sbomify.apps.core.models import Release as ProductRelease
from sbomify.apps.tea import pins, sync
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease, TeaSubscription, TeaSubscriptionEvent

pytestmark = pytest.mark.django_db

Event = TeaSubscriptionEvent.Kind
State = TeaRemoteArtifact.State


def _artifact(uuid: str, version: int = 1, sha: str = "a") -> dict[str, Any]:
    return {
        "uuid": uuid,
        "name": f"{uuid}.cdx.json",
        "type": "BOM",
        "version": version,
        "createdDate": "2025-01-01T00:00:00Z",
        "formats": [
            {
                "mediaType": "application/vnd.cyclonedx+json",
                "url": f"https://cdn.example.com/{uuid}/{version}",
                "checksums": [{"algType": "SHA-256", "algValue": sha * 64}],
            }
        ],
    }


class FakeServer:
    """What one remote TEA server publishes for one component, mutable between checks."""

    def __init__(self, component_uuid: str) -> None:
        self.component_uuid = component_uuid
        self.releases: dict[str, dict[str, Any]] = {}
        self.collections: dict[str, list[dict[str, Any]]] = {}
        self.collection_versions: dict[str, int] = {}
        self.cles: dict[str, list[dict[str, Any]]] = {}
        self.gone: set[tuple[str, int]] = set()
        self.failure: Exception | None = None

    def publish(self, release_uuid: str, version: str, days_ago: int, artifacts: list[dict[str, Any]]) -> None:
        when = (datetime(2026, 1, 1, tzinfo=UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
        self.releases[release_uuid] = {
            "uuid": release_uuid,
            "component": self.component_uuid,
            "version": version,
            "createdDate": when,
            "releaseDate": when,
        }
        self.collections[release_uuid] = artifacts
        self.collection_versions[release_uuid] = self.collection_versions.get(release_uuid, 0) + 1

    # The TeaClient calls a check makes.
    def __enter__(self) -> FakeServer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _maybe_fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    def get_component(self, uuid: str) -> Component:
        self._maybe_fail()
        if uuid != self.component_uuid:
            raise TeaNotFoundError("no such component")
        return Component.model_validate({"uuid": uuid, "name": "remote lib", "identifiers": []})

    def get_component_releases(self, uuid: str) -> list[Release]:
        return [Release.model_validate(r) for r in self.releases.values()]

    def get_component_release_collection_latest(self, uuid: str) -> Collection:
        if uuid not in self.collections:
            raise TeaNotFoundError("no collection")
        return Collection.model_validate(
            {
                "uuid": uuid,
                "version": self.collection_versions[uuid],
                "createdDate": "2025-01-01T00:00:00Z",
                "belongsTo": "COMPONENT_RELEASE",
                "updateReason": {"type": "ARTIFACT_UPDATED"},
                "artifacts": self.collections[uuid],
            }
        )

    def get_component_release_cle(self, uuid: str) -> CLE:
        if uuid not in self.cles:
            raise TeaNotFoundError("no lifecycle")
        return CLE.model_validate({"events": self.cles[uuid]})

    def get_artifact_version(self, uuid: str, version: int) -> Artifact:
        if (uuid, version) in self.gone:
            raise TeaNotFoundError("gone")
        for artifacts in self.collections.values():
            for artifact in artifacts:
                if artifact["uuid"] == uuid and artifact["version"] == version:
                    return Artifact.model_validate(artifact)
        return Artifact.model_validate(_artifact(uuid, version))


@pytest.fixture
def subscription(sample_team, make_subscription) -> TeaSubscription:
    return make_subscription(sample_team)


@pytest.fixture
def server(subscription) -> FakeServer:
    server = FakeServer(subscription.remote_component_uuid)
    server.publish("r1", "1.0", days_ago=30, artifacts=[_artifact("a")])
    return server


def run(subscription: TeaSubscription, server: FakeServer, *, force: bool = True) -> TeaSubscription | None:
    return sync.check(subscription.pk, force=force, client_for=lambda _: server)


def events(subscription: TeaSubscription) -> list[str]:
    return list(subscription.events.order_by("id").values_list("kind", flat=True))


def test_the_first_check_records_everything_and_logs_nothing(subscription, server):
    checked = run(subscription, server)

    assert checked.status == TeaSubscription.Status.OK
    assert checked.latest_release.uuid == "r1"
    assert checked.remote_name == "remote lib"
    (artifact,) = TeaRemoteArtifact.objects.filter(release__subscription=subscription)
    assert (artifact.uuid, artifact.version, artifact.state) == ("a", 1, State.CURRENT)
    assert artifact.snapshot["formats"][0]["url"] == "https://cdn.example.com/a/1"
    assert events(subscription) == []
    assert checked.lease_until is None
    assert timedelta(minutes=45) < checked.next_check_at - timezone.now() <= timedelta(minutes=50)


def test_a_check_that_is_not_due_does_nothing(subscription, server):
    run(subscription, server)

    assert run(subscription, server, force=False) is None


def test_a_held_lease_stops_a_second_check(subscription, server):
    TeaSubscription.objects.filter(pk=subscription.pk).update(lease_until=timezone.now() + timedelta(minutes=5))

    assert run(subscription, server) is None
    assert not TeaRemoteRelease.objects.filter(subscription=subscription).exists()


def test_a_check_that_lost_its_lease_writes_nothing(subscription, server):
    now = timezone.now()
    lease = sync.claim(subscription.pk, now, force=True)
    fetched = sync.fetch(subscription, server, now)
    TeaSubscription.objects.filter(pk=subscription.pk).update(lease_until=now + timedelta(hours=1))

    sync.apply(subscription.pk, lease, fetched, now)

    assert not TeaRemoteRelease.objects.filter(subscription=subscription).exists()


class TestChanges:
    @pytest.fixture
    def product(self, subscription, server):
        run(subscription, server)
        product = Product.objects.create(team=subscription.component.team, name="product")
        product.components.add(subscription.component)
        return product

    def latest_pins(self, product) -> list[tuple[str, int]]:
        latest = ProductRelease.objects.get(product=product, is_latest=True)
        return sorted(
            latest.artifacts.filter(remote_artifact__isnull=False).values_list(
                "remote_artifact__uuid", "remote_artifact__version"
            )
        )

    def test_attaching_to_a_product_pins_the_newest_release(self, product):
        assert self.latest_pins(product) == [("a", 1)]

    def test_a_new_release_moves_the_latest_release_and_leaves_manual_pins(self, subscription, server, product):
        old = TeaRemoteArtifact.objects.get(uuid="a")
        cut = ProductRelease.objects.create(product=product, name="1.0")
        ReleaseArtifact.objects.create(release=cut, remote_artifact=old)
        server.publish("r2", "2.0", days_ago=1, artifacts=[_artifact("b")])

        checked = run(subscription, server)

        assert checked.latest_release.uuid == "r2"
        assert events(subscription) == [Event.RELEASE_ADDED, Event.ARTIFACT_ADDED]
        assert self.latest_pins(product) == [("b", 1)]
        assert list(cut.artifacts.values_list("remote_artifact_id", flat=True)) == [old.pk]
        (pin,) = pins.pins_of(cut)
        assert pins.findings(pin.remote_artifact) == [pins.NEWER_RELEASE]

    def test_a_removed_release_is_marked_gone(self, subscription, server, product):
        server.publish("r2", "2.0", days_ago=1, artifacts=[_artifact("b")])
        run(subscription, server)
        del server.releases["r1"]

        run(subscription, server)

        assert TeaRemoteRelease.objects.get(uuid="r1").gone_at is not None
        assert Event.RELEASE_REMOVED in events(subscription)

    def test_a_revision_rewritten_in_place_keeps_the_pinned_snapshot(self, subscription, server, product):
        pinned = TeaRemoteArtifact.objects.get(uuid="a")
        cut = ProductRelease.objects.create(product=product, name="1.0")
        ReleaseArtifact.objects.create(release=cut, remote_artifact=pinned)
        server.publish("r1", "1.0", days_ago=30, artifacts=[_artifact("a", sha="b")])

        run(subscription, server)

        pinned.refresh_from_db()
        assert pinned.state == State.CHANGED
        assert pinned.snapshot["formats"][0]["checksums"][0]["algValue"] == "a" * 64
        assert TeaRemoteArtifact.objects.filter(uuid="a", state=State.CURRENT).count() == 1
        assert events(subscription) == [Event.COLLECTION_UPDATED, Event.ARTIFACT_CHANGED]
        assert pins.findings(pinned) == [pins.CHANGED]
        assert self.latest_pins(product) == [("a", 1)]
        assert ProductRelease.objects.filter(pk=cut.pk).annotate(marked=pins.upstream_changed()).get().marked

    def test_a_newer_revision_replaces_the_old_one(self, subscription, server, product):
        server.publish("r1", "1.0", days_ago=30, artifacts=[_artifact("a", version=2)])

        run(subscription, server)

        assert TeaRemoteArtifact.objects.get(uuid="a", version=1).state == State.REPLACED
        assert self.latest_pins(product) == [("a", 2)]
        assert Event.ARTIFACT_REPLACED in events(subscription)

    def test_a_pinned_revision_the_server_no_longer_has_is_gone(self, subscription, server, product):
        pinned = TeaRemoteArtifact.objects.get(uuid="a")
        cut = ProductRelease.objects.create(product=product, name="1.0")
        ReleaseArtifact.objects.create(release=cut, remote_artifact=pinned)
        server.gone.add(("a", 1))
        server.publish("r1", "1.0", days_ago=30, artifacts=[])

        run(subscription, server)

        pinned.refresh_from_db()
        assert pinned.state == State.GONE
        assert pins.findings(pinned)[0] == pins.GONE_UPSTREAM

    @pytest.mark.parametrize(
        "event,expected",
        [
            ({"type": "endOfLife"}, TeaRemoteRelease.Lifecycle.END_OF_LIFE),
            ({"type": "endOfSupport", "supportId": "std"}, TeaRemoteRelease.Lifecycle.END_OF_SUPPORT),
            ({"type": "endOfDistribution"}, TeaRemoteRelease.Lifecycle.NO_LONGER_DISTRIBUTED),
        ],
    )
    def test_lifecycle_comes_from_the_release_cle(self, subscription, server, product, event, expected):
        server.cles["r1"] = [
            {"id": 1, "effective": "2025-01-01T00:00:00Z", "published": "2025-01-01T00:00:00Z", **event}
        ]

        run(subscription, server)

        assert TeaRemoteRelease.objects.get(uuid="r1").lifecycle == expected
        assert Event.LIFECYCLE_CHANGED in events(subscription)

    def test_a_withdrawn_lifecycle_event_does_not_count(self, subscription, server, product):
        when = {"effective": "2025-01-01T00:00:00Z", "published": "2025-01-01T00:00:00Z"}
        server.cles["r1"] = [{"id": 1, "type": "endOfLife", **when}, {"id": 2, "type": "withdrawn", "eventId": 1, **when}]

        run(subscription, server)

        assert TeaRemoteRelease.objects.get(uuid="r1").lifecycle == TeaRemoteRelease.Lifecycle.ACTIVE


class TestFailures:
    def test_failures_back_off_and_recovery_is_logged(self, subscription, server):
        run(subscription, server)
        server.failure = TeaConnectionError("down")

        first = run(subscription, server)
        second = run(subscription, server)

        assert (first.status, first.consecutive_failures) == (TeaSubscription.Status.UNREACHABLE, 1)
        assert second.consecutive_failures == 2
        assert timedelta(hours=3) < second.next_check_at - timezone.now() <= timedelta(hours=4)
        assert events(subscription) == [Event.CHECK_FAILED]

        server.failure = None
        recovered = run(subscription, server)

        assert (recovered.status, recovered.consecutive_failures) == (TeaSubscription.Status.OK, 0)
        assert events(subscription) == [Event.CHECK_FAILED, Event.CHECK_RECOVERED]

    def test_a_component_the_server_no_longer_lists_is_not_found(self, subscription, server):
        server.component_uuid = "someone-else"

        checked = run(subscription, server)

        assert checked.status == TeaSubscription.Status.NOT_FOUND

    def test_an_unexpected_error_backs_off_too(self, subscription, server):
        server.failure = RuntimeError("bug")

        checked = run(subscription, server)

        assert (checked.status, checked.consecutive_failures) == (TeaSubscription.Status.ERROR, 1)
        assert checked.lease_until is None

    def test_backoff_doubles_to_a_day(self):
        assert [sync.backoff(n).total_seconds() / 3600 for n in (1, 2, 3, 4, 5, 9)] == [2, 4, 8, 16, 24, 24]


class TestScheduling:
    def test_the_cron_queues_only_due_and_free_subscriptions(self, sample_team, make_subscription, mocker):
        from sbomify.apps.tea import tasks

        due = make_subscription(sample_team, name="due")
        make_subscription(sample_team, name="later", next_check_at=timezone.now() + timedelta(hours=1))
        make_subscription(sample_team, name="held", lease_until=timezone.now() + timedelta(minutes=5))
        sent = mocker.patch.object(tasks.check_tea_subscription, "send")

        tasks.queue_due_tea_checks.fn()

        sent.assert_called_once_with(due.pk)

    def test_a_check_that_ran_queues_its_next_run(self, subscription, server, mocker):
        from sbomify.apps.tea import tasks

        mocker.patch.object(tasks, "check", lambda pk, force: run(subscription, server, force=force))
        later = mocker.patch.object(tasks.check_tea_subscription, "send_with_options")

        tasks.check_tea_subscription.fn(subscription.pk, force=True)

        (call,) = later.call_args_list
        assert call.kwargs["args"] == (subscription.pk,)
        assert 45 * 60_000 < call.kwargs["delay"] <= 50 * 60_000

    def test_a_check_that_did_not_run_queues_nothing(self, subscription, mocker):
        from sbomify.apps.tea import tasks

        mocker.patch.object(tasks, "check", return_value=None)
        later = mocker.patch.object(tasks.check_tea_subscription, "send_with_options")

        tasks.check_tea_subscription.fn(subscription.pk)

        later.assert_not_called()
