"""The import wizard: each step is a partial posted back to one view."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.domain.exceptions import ValidationError
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.tea import sync
from sbomify.apps.tea.models import TeaSubscription
from sbomify.apps.tea.services import remote
from sbomify.apps.tea.tests.fakes import FakeServer, artifact
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db
SERVER = remote.RemoteServer("https://tea.example.com/tea/v1.0.0", "1.0.0")


@pytest.fixture
def owner(sample_team_with_owner_member, ensure_billing_plans):  # noqa: F811
    team = sample_team_with_owner_member.team
    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    return client, team


@pytest.fixture
def fake(mocker) -> FakeServer:
    server = FakeServer("remote-component")
    server.publish("r1", "1.0", days_ago=1, artifacts=[artifact("a")])
    mocker.patch.object(remote, "connect", return_value=SERVER)
    mocker.patch.object(remote.RemoteServer, "client", lambda self: server)
    mocker.patch.object(sync, "_client", lambda subscription: server)
    return server


def step(client: Client, name: str, **data: Any) -> Any:
    return client.post(reverse("core:tea_subscription_new"), {"step": name, **data}, HTTP_HX_REQUEST="true")


def test_the_wizard_opens_on_the_source_step(owner):
    client, _ = owner

    response = client.get(reverse("core:tea_subscription_new"))

    assert response.status_code == 200
    assert "sbomify library" in response.content.decode()


def test_connecting_moves_to_find(owner, fake):
    client, _ = owner

    response = step(client, "find", source="custom", custom_server="tea.example.com")

    assert "Connected to https://tea.example.com/tea/v1.0.0" in response.content.decode()


def test_a_refused_server_is_said_in_a_toast(owner, mocker):
    client, _ = owner
    mocker.patch.object(remote, "connect", side_effect=ValidationError("sbomify subscribes to TEA 1.0 servers only."))

    response = step(client, "find", source="library.sbomify.com")

    assert response["HX-Reswap"] == "none"
    assert "TEA 1.0 servers only" in response["HX-Trigger"]


def test_products_releases_and_components_are_listed(owner, fake, mocker):
    client, _ = owner
    mocker.patch.object(
        remote, "list_products", return_value=remote.Page([{"uuid": "p1", "name": "Acme lib", "identifiers": []}])
    )
    mocker.patch.object(
        remote,
        "product_releases",
        return_value=remote.Page(
            [{"uuid": "pr1", "version": "4.2", "product_name": "Acme lib", "release_date": None, "pre_release": True}]
        ),
    )
    mocker.patch.object(
        remote,
        "product_release_components",
        return_value={
            "uuid": "pr1",
            "version": "4.2",
            "product_name": "Acme lib",
            "truncated": False,
            "components": [
                {
                    "uuid": "remote-component",
                    "name": "acme-core",
                    "identifiers": [],
                    "release_uuid": "r1",
                    "artifacts": [{"uuid": "a", "name": "acme.cdx.json", "type": "BOM", "formats": ["application/json"]}],
                }
            ],
        },
    )

    products = step(client, "products", server=SERVER.base_url, id_type="PURL", id_value="pkg:pypi/acme").content.decode()
    releases = step(client, "releases", server=SERVER.base_url, product_uuid="p1").content.decode()
    components = step(client, "components", server=SERVER.base_url, product_release_uuid="pr1").content.decode()

    assert "Acme lib" in products
    assert "4.2" in releases and "Pre-release" in releases
    assert "acme-core" in components and "acme.cdx.json" in components


def test_confirming_subscribes_and_opens_the_component(owner, fake):
    client, team = owner
    product = Product.objects.create(team=team, name="product")
    pick = "remote-component|r1|acme-core"

    confirm = step(client, "confirm", server=SERVER.base_url, pick=pick)
    done = step(client, "subscribe", server=SERVER.base_url, pick=pick, name_0="acme core", product_ids=[product.id])

    assert "Name for acme-core" in confirm.content.decode()
    component = Component.objects.get(team=team, name="acme core")
    assert done["HX-Redirect"] == reverse("core:component_details", kwargs={"component_id": component.id})
    assert TeaSubscription.objects.get(component=component).status == TeaSubscription.Status.OK
    assert product.components.filter(pk=component.pk).exists()


def test_confirm_needs_a_pick(owner, fake):
    client, _ = owner

    response = step(client, "confirm", server=SERVER.base_url)

    assert "Pick at least one component" in response["HX-Trigger"]
