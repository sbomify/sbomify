"""The TEA subscriptions API, with the remote server faked."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from libtea.exceptions import TeaConnectionError

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.tea import sync
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaSubscription
from sbomify.apps.tea.services import remote
from sbomify.apps.tea.tests.fakes import FakeServer, artifact
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db
BASE = "/api/v1/tea-subscriptions"
SERVER = remote.RemoteServer("https://tea.example.com/tea/v1.0.0", "1.0.0")


@pytest.fixture
def server(mocker) -> FakeServer:
    """The one remote server every request reaches, with no network or DNS involved."""
    fake = FakeServer("remote-component")
    fake.publish("r1", "1.0", days_ago=30, artifacts=[artifact("a")])
    fake.publish("r2", "2.0", days_ago=1, artifacts=[artifact("b")])
    mocker.patch.object(remote, "connect", return_value=SERVER)
    mocker.patch.object(remote.RemoteServer, "client", lambda self: fake)
    mocker.patch.object(sync, "_client", lambda subscription: fake)
    return fake


def _client_for(member) -> tuple[Client, Any]:
    team = member.team
    team.billing_plan = "business"
    team.save(update_fields=["billing_plan"])
    client = Client()
    setup_authenticated_client_session(client, team, member.user)
    return client, team


@pytest.fixture
def owner(sample_team_with_owner_member, ensure_billing_plans):  # noqa: F811
    return _client_for(sample_team_with_owner_member)


def post(client: Client, path: str, payload: dict[str, Any]) -> Any:
    return client.post(path, data=json.dumps(payload), content_type="application/json")


def subscribe(client: Client, **payload: Any) -> Any:
    return post(client, f"{BASE}/", {"server": "tea.example.com", "component_uuid": "remote-component", **payload})


class TestSubscribing:
    def test_a_subscription_is_created_checked_attached_and_pinned(self, owner, server):
        client, team = owner
        product = Product.objects.create(team=team, name="product")
        cut = Release.objects.create(product=product, name="1.0")

        response = subscribe(client, release_uuids=["r1"], product_ids=[product.id], pin_release_ids=[cut.id])

        assert response.status_code == 201, response.content
        body = response.json()
        component = Component.objects.get(pk=body["component_id"])
        assert component.component_type == Component.ComponentType.TEA_SUBSCRIPTION
        assert component.name == "remote lib"
        assert body["status"] == TeaSubscription.Status.OK
        assert body["latest_release"]["version"] == "2.0"
        assert [r["version"] for r in body["releases"]] == ["2.0", "1.0"]
        assert product.components.filter(pk=component.pk).exists()
        latest = Release.objects.get(product=product, is_latest=True)
        assert list(latest.artifacts.values_list("remote_artifact__uuid", flat=True)) == ["b"]
        assert list(cut.artifacts.values_list("remote_artifact__uuid", flat=True)) == ["a"]

    def test_the_same_component_twice_is_refused(self, owner, server):
        client, _ = owner
        subscribe(client)

        assert subscribe(client, name="again").status_code == 409

    def test_a_first_check_that_fails_keeps_nothing(self, owner, server):
        client, team = owner
        server.failure = TeaConnectionError("down")

        response = subscribe(client)

        assert response.status_code == 502
        assert response.json()["detail"].startswith("The server did not answer.")
        assert not Component.objects.filter(team=team).exists()

    def test_products_and_releases_from_another_workspace_are_refused_by_name(self, owner, server):
        from sbomify.apps.teams.models import Workspace

        client, team = owner
        elsewhere = Workspace.objects.create(name="elsewhere")
        their_product = Product.objects.create(team=elsewhere, name="their product")
        their_release = Release.objects.create(product=their_product, name="their secret release")

        for payload in ({"product_ids": [their_product.id]}, {"pin_release_ids": [their_release.id]}):
            response = subscribe(client, **payload)

            assert response.status_code == 400
            assert "their" not in response.json()["detail"]
        assert not Component.objects.filter(team=team).exists()

    def test_a_0_4_0_server_is_refused(self, owner, mocker):
        client, _ = owner
        mocker.patch.object(remote, "check_address")

        response = post(client, f"{BASE}/connect", {"server": "https://tea.example.com/tea/v0.4.0"})

        assert response.status_code == 400
        assert "sbomify subscribes to TEA 1.0 servers only" in response.json()["detail"]

    def test_a_guest_cannot_subscribe(self, sample_team_with_owner_member, guest_user, ensure_billing_plans, server):  # noqa: F811
        from sbomify.apps.teams.models import Member

        member = Member.objects.create(team=sample_team_with_owner_member.team, user=guest_user, role="guest")
        client, _ = _client_for(member)

        assert subscribe(client).status_code == 403


class TestReadingAndChecking:
    @pytest.fixture
    def subscribed(self, owner, server):
        client, team = owner
        component_id = subscribe(client).json()["component_id"]
        return client, component_id

    def test_status_and_events_read_back(self, subscribed, server):
        client, component_id = subscribed
        server.publish("r3", "3.0", days_ago=0, artifacts=[artifact("c")])
        sync.check(TeaSubscription.objects.get(component_id=component_id).pk, force=True)

        status = client.get(f"{BASE}/{component_id}").json()
        events = client.get(f"{BASE}/{component_id}/events").json()

        assert status["latest_release"]["version"] == "3.0"
        assert [e["kind"] for e in events] == ["artifact_added", "release_added"]

    def test_v2_serves_the_same_routes(self, subscribed):
        client, component_id = subscribed

        assert client.get(f"/api/v2/tea-subscriptions/{component_id}").json()["component_id"] == component_id

    def test_check_now_queues_a_forced_check(self, subscribed, mocker):
        client, component_id = subscribed
        send = mocker.patch("sbomify.apps.tea.subscriptions_api.check_tea_subscription.send")

        response = client.post(f"{BASE}/{component_id}/check")

        assert response.status_code == 202
        send.assert_called_once_with(TeaSubscription.objects.get(component_id=component_id).pk, force=True)

    def test_another_workspace_cannot_read_it(self, subscribed, guest_user):
        from sbomify.apps.teams.models import Member, Workspace

        _, component_id = subscribed
        elsewhere = Workspace.objects.create(name="elsewhere")
        stranger, _ = _client_for(Member.objects.create(team=elsewhere, user=guest_user, role="owner"))

        assert stranger.get(f"{BASE}/{component_id}").status_code == 404


class TestPins:
    @pytest.fixture
    def release(self, owner, server):
        client, team = owner
        subscribe(client, release_uuids=["r1"])
        product = Product.objects.create(team=team, name="product")
        return client, Release.objects.create(product=product, name="1.0")

    def test_pin_list_and_unpin(self, release):
        client, cut = release
        older = TeaRemoteArtifact.objects.get(uuid="a")

        added = post(client, f"{BASE}/releases/{cut.id}/pins", {"remote_artifact_id": older.id})
        listed = client.get(f"{BASE}/releases/{cut.id}/pins").json()
        removed = client.delete(f"{BASE}/releases/{cut.id}/pins/{added.json()['id']}")

        assert added.status_code == 201
        assert [(p["uuid"], p["findings"]) for p in listed] == [("a", ["newer_release"])]
        (pin,) = listed
        assert pin["finding_details"] == [
            {"key": "newer_release", "label": "Newer upstream release exists", "tone": "info"}
        ]
        assert (pin["component_name"], pin["remote_release"]) == ("remote lib", "1.0")
        assert removed.status_code == 204
        assert not cut.artifacts.exists()

    def test_pinnable_lists_what_the_product_may_pin_and_not_what_is_pinned(self, release):
        client, cut = release
        subscription = TeaSubscription.objects.get()
        cut.product.components.add(subscription.component)

        before = client.get(f"{BASE}/releases/{cut.id}/pinnable").json()
        post(client, f"{BASE}/releases/{cut.id}/pins", {"remote_artifact_id": before[0]["id"]})
        after = client.get(f"{BASE}/releases/{cut.id}/pinnable").json()

        assert sorted(a["name"] for a in before) == ["a.cdx.json", "b.cdx.json"]
        assert all(a["artifact_type"] == "remote" for a in before)
        assert len(after) == len(before) - 1

    def test_the_latest_release_refuses_manual_pins(self, release):
        client, cut = release
        latest = Release.get_or_create_latest_release(cut.product)

        payload = {"remote_artifact_id": TeaRemoteArtifact.objects.get(uuid="a").id}

        response = post(client, f"{BASE}/releases/{latest.id}/pins", payload)

        assert response.status_code == 400
