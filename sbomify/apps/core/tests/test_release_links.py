"""A release links the release of another product it ships with."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact, ReleaseLink
from sbomify.apps.core.services.release_links import aggregate_sbom_artifacts, linked_release_ids
from sbomify.apps.core.tests.shared_fixtures import get_api_headers, setup_authenticated_client_session
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import compute_release_aggregate_fingerprint
from sbomify.apps.teams.models import Workspace

pytestmark = pytest.mark.django_db


def _release(team: Workspace, name: str, *, is_public: bool = True, version: str = "") -> Release:
    product = Product.objects.create(name=name, team=team, is_public=is_public)
    return Release.objects.create(product=product, name=version or "v1", version=version or "v1")


def _sbom(release: Release, name: str, *, visibility: str = Component.Visibility.PUBLIC) -> SBOM:
    component = Component.objects.create(name=name, team=release.product.team, visibility=visibility)
    release.product.components.add(component)
    sbom = SBOM.objects.create(name=name, component=component, format="cyclonedx", format_version="1.6")
    ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return sbom


@pytest.fixture
def app(team_with_business_plan) -> Release:
    return _release(team_with_business_plan, "Application", version="v2.0.0")


@pytest.fixture
def toolchain(team_with_business_plan) -> Release:
    return _release(team_with_business_plan, "Toolchain", version="tools-1.0.0")


def _post(client: Client, token: Any, release: Release, body: dict[str, str]):
    return client.post(
        f"/api/v1/releases/{release.id}/links",
        data=json.dumps(body),
        content_type="application/json",
        **get_api_headers(token),
    )


class TestLinkingApi:
    def test_link_by_product_and_version(self, authenticated_api_client, app, toolchain):
        client, token = authenticated_api_client
        response = _post(client, token, app, {"product_id": toolchain.product_id, "version": "tools-1.0.0"})

        assert response.status_code == 201, response.content
        body = response.json()
        assert (body["id"], body["product_name"], body["version"]) == (toolchain.id, "Toolchain", "tools-1.0.0")
        assert ReleaseLink.objects.filter(release=app, linked_release=toolchain).exists()

    def test_link_by_release_id_and_list_it(self, authenticated_api_client, app, toolchain):
        client, token = authenticated_api_client
        assert _post(client, token, app, {"release_id": toolchain.id}).status_code == 201

        listed = client.get(f"/api/v1/releases/{app.id}/links", **get_api_headers(token))
        assert listed.status_code == 200
        assert [link["id"] for link in listed.json()] == [toolchain.id]

    def test_v2_serves_the_same_links(self, authenticated_api_client, app, toolchain):
        client, token = authenticated_api_client
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        listed = client.get(f"/api/v2/releases/{app.id}/links", **get_api_headers(token))
        assert [link["id"] for link in listed.json()] == [toolchain.id]

    def test_linking_twice_conflicts(self, authenticated_api_client, app, toolchain):
        client, token = authenticated_api_client
        assert _post(client, token, app, {"release_id": toolchain.id}).status_code == 201
        again = _post(client, token, app, {"release_id": toolchain.id})
        assert again.status_code == 409
        assert again.json()["error_code"] == "CONFLICT"

    @pytest.mark.parametrize(
        "body",
        [{}, {"product_id": "p"}, {"release_id": "r", "product_id": "p", "version": "v"}],
    )
    def test_the_target_is_named_one_way(self, authenticated_api_client, app, body):
        client, token = authenticated_api_client
        assert _post(client, token, app, body).status_code == 422

    def test_an_unknown_target_is_not_found(self, authenticated_api_client, app):
        client, token = authenticated_api_client
        assert _post(client, token, app, {"release_id": "missing"}).status_code == 404

    def test_a_release_of_another_workspace_is_not_found(self, authenticated_api_client, app):
        other = _release(Workspace.objects.create(name="Elsewhere"), "Theirs")
        client, token = authenticated_api_client
        assert _post(client, token, app, {"release_id": other.id}).status_code == 404

    def test_a_release_of_the_same_product_is_refused(self, authenticated_api_client, app):
        sibling = Release.objects.create(product=app.product, name="v1.9.0", version="v1.9.0")
        client, token = authenticated_api_client
        assert _post(client, token, app, {"release_id": sibling.id}).status_code == 400

    def test_a_cycle_is_refused(self, authenticated_api_client, app, toolchain):
        third = _release(app.product.team, "Runtime")
        ReleaseLink.objects.create(release=toolchain, linked_release=third)
        ReleaseLink.objects.create(release=third, linked_release=app)
        client, token = authenticated_api_client
        response = _post(client, token, app, {"release_id": toolchain.id})
        assert response.status_code == 400
        assert not ReleaseLink.objects.filter(release=app).exists()

    def test_the_latest_release_takes_no_links(self, authenticated_api_client, app, toolchain):
        latest = Release.objects.create(product=app.product, name="latest", is_latest=True)
        client, token = authenticated_api_client
        assert _post(client, token, latest, {"release_id": toolchain.id}).status_code == 400

    def test_unlink(self, authenticated_api_client, app, toolchain):
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        client, token = authenticated_api_client
        url = f"/api/v1/releases/{app.id}/links/{toolchain.id}"
        assert client.delete(url, **get_api_headers(token)).status_code == 204
        assert client.delete(url, **get_api_headers(token)).status_code == 404

    def test_a_guest_cannot_link(self, guest_api_client, app, toolchain):
        client, token = guest_api_client
        assert _post(client, token, app, {"release_id": toolchain.id}).status_code == 403

    def test_the_public_sees_only_links_to_public_products(self, app, toolchain):
        hidden = _release(app.product.team, "Internal", is_public=False)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        ReleaseLink.objects.create(release=app, linked_release=hidden)

        listed = Client().get(f"/api/v1/releases/{app.id}/links")
        assert [link["id"] for link in listed.json()] == [toolchain.id]


class TestTheAggregate:
    def test_linked_members_join_the_aggregate_once(self, app, toolchain):
        own = _sbom(app, "app")
        bundle = _sbom(toolchain, "bundle")
        ReleaseArtifact.objects.create(release=toolchain, sbom=own)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)

        members = aggregate_sbom_artifacts(app, include_non_public=False)
        assert sorted(m.sbom_id for m in members) == sorted([own.id, bundle.id])

    def test_links_are_followed_through(self, app, toolchain):
        runtime = _release(app.product.team, "Runtime")
        deep = _sbom(runtime, "deep")
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        ReleaseLink.objects.create(release=toolchain, linked_release=runtime)

        assert linked_release_ids(app) == [toolchain.id, runtime.id]
        assert deep.id in [m.sbom_id for m in aggregate_sbom_artifacts(app, include_non_public=False)]

    def test_the_public_aggregate_leaves_out_what_the_linked_release_hides(self, app):
        private_product = _release(app.product.team, "Internal", is_public=False)
        hidden_product = _sbom(private_product, "internal")
        ReleaseLink.objects.create(release=app, linked_release=private_product)

        assert aggregate_sbom_artifacts(app, include_non_public=False) == []
        full = aggregate_sbom_artifacts(app, include_non_public=True)
        assert [m.sbom_id for m in full] == [hidden_product.id]

    def test_a_reader_confined_to_some_products_gets_the_others_public_view(self, app, toolchain):
        open_bundle = _sbom(toolchain, "open")
        _sbom(toolchain, "closed", visibility=Component.Visibility.PRIVATE)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)

        confined = aggregate_sbom_artifacts(app, include_non_public=True, readable_product_ids=set())
        assert [m.sbom_id for m in confined] == [open_bundle.id]
        trusted = aggregate_sbom_artifacts(app, include_non_public=True, readable_product_ids={toolchain.product_id})
        assert len(trusted) == 2

    def test_linking_changes_the_public_aggregate_key(self, app, toolchain):
        _sbom(app, "app")
        _sbom(toolchain, "bundle")
        before = compute_release_aggregate_fingerprint(app)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        assert compute_release_aggregate_fingerprint(app) != before


class TestTheReleasePages:
    def test_the_app_page_lists_what_the_release_ships_with(self, client, sample_user, app, toolchain):
        setup_authenticated_client_session(client, app.product.team, sample_user)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)

        page = client.get(reverse("core:release_details", args=[app.product_id, app.id]))
        assert page.status_code == 200
        html = page.content.decode()
        assert "Ships with" in html
        assert reverse("core:release_details", args=[toolchain.product_id, toolchain.id]) in html

    def test_a_release_without_links_shows_no_section(self, client, sample_user, app):
        setup_authenticated_client_session(client, app.product.team, sample_user)
        page = client.get(reverse("core:release_details", args=[app.product_id, app.id]))
        assert "Ships with" not in page.content.decode()

    def test_the_trust_center_lists_only_public_products(self, app, toolchain):
        hidden = _release(app.product.team, "Internal", is_public=False)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        ReleaseLink.objects.create(release=app, linked_release=hidden)

        page = Client().get(reverse("core:release_details_public", args=[app.product_id, app.id]))
        assert page.status_code == 200
        html = page.content.decode()
        assert f"/public/product/{toolchain.product_id}/release/{toolchain.id}/" in html
        assert "Internal" not in html
