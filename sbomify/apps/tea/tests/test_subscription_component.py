"""A TEA subscription is a component type of its own, made only by subscribing."""

from __future__ import annotations

import json

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner_client(sample_team_with_owner_member, ensure_billing_plans):  # noqa: F811
    team = sample_team_with_owner_member.team
    team.billing_plan = "business"
    team.save(update_fields=["billing_plan"])
    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    return client, team


def _send(client, method, url, payload):
    return getattr(client, method)(url, data=json.dumps(payload), content_type="application/json")


def test_a_plain_create_cannot_make_a_subscription(owner_client):
    client, team = owner_client

    response = _send(client, "post", "/api/v1/components", {"name": "x", "component_type": "tea_subscription"})

    assert response.status_code == 400
    assert "Subscribe to a component on a TEA server" in response.json()["detail"]
    assert not Component.objects.filter(team=team, name="x").exists()


@pytest.mark.parametrize("method", ["patch", "put"])
def test_a_subscription_keeps_its_type(owner_client, make_subscription, method):
    client, team = owner_client
    component = make_subscription(team).component

    payload = {"name": "y", "component_type": "bom", "is_global": False}

    response = _send(client, method, f"/api/v1/components/{component.id}", payload)

    assert response.status_code == 400
    component.refresh_from_db()
    assert component.component_type == Component.ComponentType.TEA_SUBSCRIPTION


def test_a_component_cannot_become_a_subscription(owner_client):
    client, team = owner_client
    component = Component.objects.create(team=team, name="plain")

    response = _send(client, "patch", f"/api/v1/components/{component.id}", {"component_type": "tea_subscription"})

    assert response.status_code == 400
    component.refresh_from_db()
    assert component.component_type == Component.ComponentType.BOM


def test_a_subscription_cannot_be_workspace_wide(sample_team, make_subscription):
    component = make_subscription(sample_team).component
    component.is_global = True

    with pytest.raises(ValidationError):
        component.clean()


class TestRemotePins:
    @pytest.fixture
    def pinned(self, sample_team, make_subscription):
        subscription = make_subscription(sample_team)
        remote_release = TeaRemoteRelease.objects.create(subscription=subscription, uuid="r-1", version="1.0")
        remote_artifact = TeaRemoteArtifact.objects.create(
            release=remote_release, uuid="a-1", version=1, name="lib.cdx.json", snapshot={}, snapshot_fingerprint="f"
        )
        product = Product.objects.create(team=sample_team, name="product")
        release = Release.objects.create(product=product, name="2.0")
        return release, remote_artifact, subscription

    def test_a_release_pins_a_remote_artifact_revision(self, pinned):
        release, remote_artifact, subscription = pinned

        pin = ReleaseArtifact.objects.create(release=release, remote_artifact=remote_artifact)

        assert pin.artifact_type == "remote"
        assert pin.artifact_name == "lib.cdx.json"
        assert pin.component == subscription.component

    def test_a_pin_names_exactly_one_artifact(self, pinned, sample_sbom):
        release, remote_artifact, _ = pinned

        with pytest.raises(ValidationError):
            ReleaseArtifact.objects.create(release=release)
        with pytest.raises(ValidationError):
            ReleaseArtifact.objects.create(release=release, remote_artifact=remote_artifact, sbom=sample_sbom)
