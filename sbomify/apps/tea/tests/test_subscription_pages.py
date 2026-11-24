"""The pages a subscription shows on: its own component page, the release page, and the release list."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.tea import pins, sync
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaSubscription
from sbomify.apps.tea.tests.fakes import FakeServer, artifact
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(sample_team_with_owner_member, ensure_billing_plans, make_subscription):  # noqa: F811
    """An owner's workspace with a checked subscription attached to a product."""
    team = sample_team_with_owner_member.team
    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    subscription = make_subscription(team, name="acme-core")
    server = FakeServer(subscription.remote_component_uuid)
    server.publish("r1", "1.0", days_ago=10, artifacts=[artifact("a")])
    sync.check(subscription.pk, force=True, client_for=lambda _: server)
    product = Product.objects.create(team=team, name="product")
    product.components.add(subscription.component)
    return client, subscription, server, product


def test_the_component_page_shows_upstream_releases_and_history(setup):
    client, subscription, server, _ = setup
    server.publish("r2", "2.0", days_ago=1, artifacts=[artifact("b")])
    server.publish("r0", "0.9", days_ago=100, artifacts=[artifact("z")])
    sync.check(subscription.pk, force=True, client_for=lambda _: server)

    body = client.get(reverse("core:component_details", args=[subscription.component_id])).content.decode()

    assert "Upstream" in body and "https://tea.example.com/tea/v1.0.0" in body
    assert "a.cdx.json" in body and "b.cdx.json" in body
    assert "New upstream release" in body and "Release 2.0" in body
    assert "Upload document" not in body
    assert "Upstream releases" in body
    assert "0.9" in body and "Not read" in body and "z.cdx.json" not in body


def test_check_now_queues_a_forced_check(setup, mocker):
    client, subscription, _, _ = setup
    send = mocker.patch("sbomify.apps.tea.views.check_tea_subscription.send")

    response = client.post(reverse("core:tea_subscription_check", args=[subscription.component_id]))

    assert response.status_code == 200
    send.assert_called_once_with(subscription.pk, force=True)


def test_the_release_page_pins_lists_and_unpins(setup):
    client, subscription, server, product = setup
    cut = Release.objects.create(product=product, name="1.0")
    remote = TeaRemoteArtifact.objects.get(uuid="a")
    pins_url = reverse("core:tea_release_pins", args=[cut.id])
    page_url = reverse("core:release_details", args=[product.id, cut.id])

    client.post(pins_url, {"action": "pin", "remote_artifact_id": remote.id})
    server.publish("r2", "2.0", days_ago=1, artifacts=[artifact("b")])
    sync.check(subscription.pk, force=True, client_for=lambda _: server)
    page = client.get(page_url).content.decode()
    pin = cut.artifacts.get(remote_artifact=remote)
    client.post(pins_url, {"action": "unpin", "pin_id": pin.id})

    assert "Remote artifacts" in page and "Newer upstream release exists" in page
    assert not cut.artifacts.exists()


def test_the_release_list_marks_a_release_whose_upstream_changed(setup):
    client, subscription, server, product = setup
    cut = Release.objects.create(product=product, name="1.0")
    pins.pin(cut, TeaRemoteArtifact.objects.get(uuid="a"))
    server.publish("r1", "1.0", days_ago=10, artifacts=[artifact("a", sha="b")])
    sync.check(subscription.pk, force=True, client_for=lambda _: server)

    body = client.get(reverse("core:releases_dashboard")).content.decode()

    assert TeaSubscription.objects.get(pk=subscription.pk).status == TeaSubscription.Status.OK
    assert "Upstream changed" in body


def test_the_remote_pins_card_is_empty_for_someone_who_cannot_read_the_release(setup, guest_user):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    _, subscription, _, product = setup
    cut = Release.objects.create(product=product, name="1.0")
    pins.pin(cut, TeaRemoteArtifact.objects.get(uuid="a"))
    request = RequestFactory().get("/")
    request.user = guest_user

    card = pins.release_card(request, cut)
    request.user = AnonymousUser()

    assert card["remote_pins"] == [] and card["remote_pin_choices"] == []
    assert pins.release_card(request, cut)["remote_pins"] == []
