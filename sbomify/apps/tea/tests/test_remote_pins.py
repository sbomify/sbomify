"""Pinning remote artifacts into product releases, and serving them from sbomify's own TEA API."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from sbomify.apps.core.domain.exceptions import ConflictError, PermissionDeniedError, ValidationError
from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.tea import pins
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaRemoteRelease
from sbomify.apps.teams.models import Workspace

pytestmark = pytest.mark.django_db
BASE = f"/tea/v{TEA_API_VERSION}"


def _snapshot(uuid: str, version: int, url: str | None = "https://cdn.example.com/lib.json") -> dict[str, Any]:
    fmt: dict[str, Any] = {"mediaType": "application/vnd.cyclonedx+json"}
    if url:
        fmt |= {"url": url, "checksums": [{"algType": "SHA-256", "algValue": "a" * 64}]}
    return {
        "uuid": uuid,
        "name": "lib.cdx.json",
        "type": "BOM",
        "version": version,
        "createdDate": "2025-01-01T00:00:00Z",
        "formats": [fmt],
    }


@pytest.fixture
def remote(tea_conformance_data, make_subscription):
    """A public subscription in the TEA-enabled workspace, attached to its public product, with two revisions."""
    team, product = tea_conformance_data[:2]
    subscription = make_subscription(team)
    product.components.add(subscription.component)
    remote_release = TeaRemoteRelease.objects.create(subscription=subscription, uuid="r-1", version="1.0")

    def revision(version: int, **snapshot: Any) -> TeaRemoteArtifact:
        return TeaRemoteArtifact.objects.create(
            release=remote_release,
            uuid="remote-artifact",
            version=version,
            name="lib.cdx.json",
            snapshot=_snapshot("remote-artifact", version, **snapshot),
            snapshot_fingerprint=f"fp{version}",
        )

    return team, product, subscription, revision


def get(path: str, team: Workspace, **params: Any) -> Any:
    return Client().get(path, {"workspace_key": team.key, **params})


class TestPinning:
    def test_a_revision_is_pinned_once(self, remote):
        team, product, _, revision = remote
        release = Release.objects.create(product=product, name="2.0")
        first = revision(1)

        pin = pins.pin(release, first)

        assert pins.pin(release, first) == pin

    def test_another_revision_of_the_same_artifact_replaces_or_is_refused(self, remote):
        team, product, _, revision = remote
        release = Release.objects.create(product=product, name="2.0")
        pins.pin(release, revision(1))
        second = revision(2)

        with pytest.raises(ConflictError):
            pins.pin(release, second)
        pins.pin(release, second, allow_replacement=True)

        assert list(release.artifacts.values_list("remote_artifact__version", flat=True)) == [2]

    def test_the_latest_release_and_other_workspaces_are_refused(self, remote):
        team, product, _, revision = remote
        latest = Release.get_or_create_latest_release(product)
        other_team = Workspace.objects.create(name="other workspace")
        elsewhere = Release.objects.create(product=Product.objects.create(team=other_team, name="x"), name="1")

        with pytest.raises(ValidationError):
            pins.pin(latest, revision(1))
        with pytest.raises(PermissionDeniedError):
            pins.pin(elsewhere, revision(2))

    def test_unpinning_removes_only_that_pin(self, remote):
        team, product, _, revision = remote
        release = Release.objects.create(product=product, name="2.0")
        pin = pins.pin(release, revision(1))

        pins.unpin(release, pin.pk)

        assert not release.artifacts.filter(remote_artifact__isnull=False).exists()


class TestTeaExport:
    @pytest.fixture
    def pinned(self, remote):
        team, product, subscription, revision = remote
        release = Release.objects.create(product=product, name="2.0")
        pins.pin(release, revision(3))
        return team, release, subscription

    def test_the_collection_lists_the_remote_artifact_with_its_remote_url(self, pinned):
        team, release, _ = pinned

        body = get(f"{BASE}/productRelease/{release.uuid}/collection/latest", team).json()

        (artifact,) = [a for a in body["artifacts"] if a["uuid"] == "remote-artifact"]
        assert artifact["version"] == 3
        assert artifact["formats"][0]["url"] == "https://cdn.example.com/lib.json"

    def test_a_private_subscription_is_left_out(self, pinned):
        team, release, subscription = pinned
        Component.objects.filter(pk=subscription.component_id).update(visibility=Component.Visibility.PRIVATE)

        body = get(f"{BASE}/productRelease/{release.uuid}/collection/latest", team).json()

        assert all(a["uuid"] != "remote-artifact" for a in body["artifacts"])

    def test_the_artifact_routes_serve_the_pinned_revision(self, pinned):
        team = pinned[0]

        latest = get(f"{BASE}/artifact/remote-artifact/latest", team)
        exact = get(f"{BASE}/artifact/remote-artifact/3", team)
        unpinned = get(f"{BASE}/artifact/remote-artifact/1", team)

        assert latest.json() == exact.json()
        assert latest.json()["version"] == 3
        assert unpinned.status_code == 404

    def test_a_download_redirects_to_the_remote_server(self, pinned):
        team = pinned[0]

        found = get(f"{BASE}/artifact/remote-artifact/3/download", team)
        wrong = get(f"{BASE}/artifact/remote-artifact/3/download", team, mediaType="text/plain")
        signature = get(f"{BASE}/artifact/remote-artifact/latest/signature/download", team)

        assert (found.status_code, found["Location"]) == (302, "https://cdn.example.com/lib.json")
        assert wrong.status_code == 406
        assert signature.status_code == 302
        assert signature["Location"] == "https://tea.example.com/tea/v1.0.0/artifact/remote-artifact/3/signature/download?mediaType=application%2Fvnd.cyclonedx%2Bjson"

    def test_the_subscription_component_is_not_published_as_ours(self, pinned):
        team, release, subscription = pinned

        components = get(f"{BASE}/components", team).json()
        single = get(f"{BASE}/component/{subscription.component.uuid}", team)
        product_release = get(f"{BASE}/productRelease/{release.uuid}", team).json()

        assert str(subscription.component.uuid) not in [c["uuid"] for c in components["results"]]
        assert single.status_code == 404
        assert str(subscription.component.uuid) not in [c["uuid"] for c in product_release["components"]]
