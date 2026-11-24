"""Checking a subscription against a TEA server, with the server faked.

Each test arranges what the remote server publishes, runs a check, and reads
back what sbomify recorded: releases, artifact snapshots and states, events,
the schedule, and the pins of the product releases.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from libtea.exceptions import TeaConnectionError

from sbomify.apps.core.models import Product, ReleaseArtifact
from sbomify.apps.core.models import Release as ProductRelease
from sbomify.apps.tea import pins, sync
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease, TeaSubscription, TeaSubscriptionEvent
from sbomify.apps.tea.tests.fakes import FakeServer, artifact

pytestmark = pytest.mark.django_db

Event = TeaSubscriptionEvent.Kind
State = TeaRemoteArtifact.State


@pytest.fixture
def subscription(sample_team, make_subscription) -> TeaSubscription:
    return make_subscription(sample_team)


@pytest.fixture
def server(subscription) -> FakeServer:
    server = FakeServer(subscription.remote_component_uuid)
    server.publish("r1", "1.0", days_ago=30, artifacts=[artifact("a")])
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


def test_a_snapshot_reads_back_as_the_server_sent_it(subscription, server):
    from libtea.models import Artifact

    bare = {**artifact("n"), "formats": [{"mediaType": "application/spdx+json", "description": "SPDX SBOM"}]}
    server.publish("r1", "1.0", days_ago=30, artifacts=[bare])

    run(subscription, server)

    snapshot = TeaRemoteArtifact.objects.get(uuid="n").snapshot
    assert snapshot["formats"] == bare["formats"]
    Artifact.model_validate(snapshot)


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
        server.publish("r2", "2.0", days_ago=1, artifacts=[artifact("b")])

        checked = run(subscription, server)

        assert checked.latest_release.uuid == "r2"
        assert events(subscription) == [Event.RELEASE_ADDED, Event.ARTIFACT_ADDED]
        assert self.latest_pins(product) == [("b", 1)]
        assert list(cut.artifacts.values_list("remote_artifact_id", flat=True)) == [old.pk]
        (pin,) = pins.pins_of(cut)
        assert pins.findings(pin.remote_artifact) == [pins.NEWER_RELEASE]

    def test_a_removed_release_is_marked_gone(self, subscription, server, product):
        server.publish("r2", "2.0", days_ago=1, artifacts=[artifact("b")])
        run(subscription, server)
        del server.releases["r1"]

        run(subscription, server)

        assert TeaRemoteRelease.objects.get(uuid="r1").gone_at is not None
        assert Event.RELEASE_REMOVED in events(subscription)

    def test_a_revision_rewritten_in_place_keeps_the_pinned_snapshot(self, subscription, server, product):
        pinned = TeaRemoteArtifact.objects.get(uuid="a")
        cut = ProductRelease.objects.create(product=product, name="1.0")
        ReleaseArtifact.objects.create(release=cut, remote_artifact=pinned)
        server.publish("r1", "1.0", days_ago=30, artifacts=[artifact("a", sha="b")])

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
        server.publish("r1", "1.0", days_ago=30, artifacts=[artifact("a", version=2)])

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
