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

    def test_linking_and_unlinking_tell_the_linked_releases_too(
        self, authenticated_api_client, app, toolchain, mocker, django_capture_on_commit_callbacks
    ):
        """Whether a linked release is still monitored depends on the releases linking to it,
        so its open page, and those of the releases it links on, repaint too."""
        runtime = _release(app.product.team, "Runtime")
        ReleaseLink.objects.create(release=toolchain, linked_release=runtime)
        # The endpoint tells the release it changed, and a removed link tells the rest itself.
        sent = mocker.patch("sbomify.apps.core.apis.broadcast_to_workspace")
        mocker.patch(BROADCAST, sent)
        client, token = authenticated_api_client

        with django_capture_on_commit_callbacks(execute=True):
            assert _post(client, token, app, {"release_id": toolchain.id}).status_code == 201
            assert (
                client.delete(f"/api/v1/releases/{app.id}/links/{toolchain.id}", **get_api_headers(token)).status_code
                == 204
            )

        told = [
            c.kwargs["data"]["release_id"] for c in sent.call_args_list if c.kwargs["message_type"] == "release_updated"
        ]
        assert told.count(str(app.id)) == 2
        assert told.count(str(toolchain.id)) == 2
        assert told.count(str(runtime.id)) == 2

    def test_unlinking_tells_the_releases_that_ship_the_linked_sboms(
        self, authenticated_api_client, app, toolchain, mocker, django_capture_on_commit_callbacks
    ):
        """A retired release sharing the linked release's SBOM can stop being monitored with it. Each hears once."""
        bundle = _sbom(toolchain, "bundle")
        sibling = _release(app.product.team, "Sibling")
        ReleaseArtifact.objects.create(release=sibling, sbom=bundle)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        sent = mocker.patch("sbomify.apps.core.apis.broadcast_to_workspace")
        mocker.patch(BROADCAST, sent)
        client, token = authenticated_api_client

        with django_capture_on_commit_callbacks(execute=True):
            response = client.delete(f"/api/v1/releases/{app.id}/links/{toolchain.id}", **get_api_headers(token))

        assert response.status_code == 204
        told = [
            c.kwargs["data"]["release_id"] for c in sent.call_args_list if c.kwargs["message_type"] == "release_updated"
        ]
        assert {str(app.id), str(toolchain.id), str(sibling.id)} <= set(told)
        assert len(told) == len(set(told))

    @pytest.mark.parametrize("action", ["withdraw", "archive"])
    def test_retiring_a_release_tells_the_releases_it_links_to(
        self, authenticated_api_client, app, toolchain, mocker, action
    ):
        """The linked release may have been monitored only because this one linked to it."""
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        sent = mocker.patch("sbomify.apps.core.apis.schedule_broadcast")
        client, token = authenticated_api_client
        body = {"action": action, "reason": "defective"} if action == "withdraw" else {"action": action}

        response = client.post(
            f"/api/v1/releases/{app.id}/lifecycle",
            data=json.dumps(body),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        told = {c.args[2]["release_id"] for c in sent.call_args_list if c.args[1] == "release_updated"}
        assert str(toolchain.id) in told

    @pytest.mark.parametrize("action", ["withdraw", "archive"])
    def test_retiring_a_release_tells_the_releases_that_share_its_sboms(
        self, authenticated_api_client, app, toolchain, mocker, action
    ):
        """With no link at all, a retired release shipping the same SBOM may have been monitored only through it."""
        ReleaseArtifact.objects.create(release=toolchain, sbom=_sbom(app, "shared"))
        sent = mocker.patch("sbomify.apps.core.apis.schedule_broadcast")
        client, token = authenticated_api_client
        body = {"action": action, "reason": "defective"} if action == "withdraw" else {"action": action}

        response = client.post(
            f"/api/v1/releases/{app.id}/lifecycle",
            data=json.dumps(body),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        told = {c.args[2]["release_id"] for c in sent.call_args_list if c.args[1] == "release_updated"}
        assert str(toolchain.id) in told

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

    def test_a_release_without_links_offers_a_manager_the_add_control(self, client, sample_user, app):
        setup_authenticated_client_session(client, app.product.team, sample_user)
        page = client.get(reverse("core:release_details", args=[app.product_id, app.id]))
        html = page.content.decode()
        assert "Ships with no other release" in html
        assert "Add release" in html

    def test_the_trust_center_lists_only_public_products(self, app, toolchain):
        hidden = _release(app.product.team, "Internal", is_public=False)
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        ReleaseLink.objects.create(release=app, linked_release=hidden)

        page = Client().get(reverse("core:release_details_public", args=[app.product_id, app.id]))
        assert page.status_code == 200
        html = page.content.decode()
        assert f"/public/product/{toolchain.product_id}/release/{toolchain.id}/" in html
        assert "Internal" not in html


BROADCAST = "sbomify.apps.core.services.release_lifecycle.broadcast_to_workspace"


class TestReleasesSharingAnSbomHearWhenItsTrackingMoves:
    """A retired release's panel says whether its SBOMs are still scanned, and other releases decide that."""

    def _told(self, sent) -> set[str]:
        return {
            c.kwargs["data"]["release_id"] for c in sent.call_args_list if c.kwargs["message_type"] == "release_updated"
        }

    def test_removing_the_sbom_from_another_release(self, app, toolchain, mocker, django_capture_on_commit_callbacks):
        pin = ReleaseArtifact.objects.create(release=toolchain, sbom=_sbom(app, "shared"))
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            pin.delete()

        assert str(app.id) in self._told(sent)

    def test_deleting_another_release_that_shipped_it(self, app, toolchain, mocker, django_capture_on_commit_callbacks):
        ReleaseArtifact.objects.create(release=toolchain, sbom=_sbom(app, "shared"))
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            toolchain.delete()

        assert str(app.id) in self._told(sent)

    def test_adding_the_sbom_to_another_release(self, app, toolchain, mocker, django_capture_on_commit_callbacks):
        shared = _sbom(app, "shared")
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            ReleaseArtifact.objects.create(release=toolchain, sbom=shared)

        assert str(app.id) in self._told(sent)

    def test_deleting_a_release_that_linked_to_it(self, app, toolchain, mocker, django_capture_on_commit_callbacks):
        # The linking release ships no SBOM of its own, so no artifact goes with it.
        _sbom(app, "historical")
        ReleaseLink.objects.create(release=toolchain, linked_release=app)
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            toolchain.delete()

        assert str(app.id) in self._told(sent)

    def test_withdrawing_a_successor_tells_what_its_predecessor_links_to(
        self, app, toolchain, mocker, django_capture_on_commit_callbacks
    ):
        # Withdrawing the successor makes the predecessor live again, and a live
        # release keeps the releases it links on monitored.
        from sbomify.apps.core.schemas import SupersedesItem
        from sbomify.apps.core.services.release_lifecycle import declare_supersedes, set_release_state

        successor = Release.objects.create(product=app.product, name="v3", version="v3.0.0")
        with django_capture_on_commit_callbacks(execute=True):
            assert declare_supersedes(successor, [SupersedesItem(release_id=app.pk, drop_in=True)]).ok
        ReleaseLink.objects.create(release=app, linked_release=toolchain)
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            assert set_release_state(successor, "withdraw", reason="defective").ok

        assert str(toolchain.id) in self._told(sent)

    def test_deleting_the_newest_sbom_tells_the_releases_shipping_the_one_before(
        self, app, mocker, django_capture_on_commit_callbacks
    ):
        shipped = _sbom(app, "kernel")
        newer = SBOM.objects.create(
            name="kernel", version="2", component=shipped.component, format="cyclonedx", format_version="1.6"
        )
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            newer.delete()

        assert str(app.id) in self._told(sent)

    def test_deleting_an_sbom_tells_the_release_that_shipped_it(self, app, mocker, django_capture_on_commit_callbacks):
        # Its last untracked SBOM gone, the rest of a retired release may be fully monitored again.
        shipped = _sbom(app, "historical")
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            shipped.delete()

        assert str(app.id) in self._told(sent)

    def test_a_bulk_delete_tells_each_release_once(self, app, toolchain, mocker, django_capture_on_commit_callbacks):
        # One delete taking many shared SBOMs with it would otherwise query and
        # broadcast once per artifact.
        for name in ("a", "b", "c"):
            ReleaseArtifact.objects.create(release=toolchain, sbom=_sbom(app, name))
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            toolchain.delete()

        told = [
            c.kwargs["data"]["release_id"] for c in sent.call_args_list if c.kwargs["message_type"] == "release_updated"
        ]
        assert told.count(str(app.id)) == 1
        assert sum(type(callback).__name__ == "_ReleasesToTell" for callback in callbacks) == 1

    def test_refreshing_a_latest_release_tells_each_release_once(self, app, mocker, django_capture_on_commit_callbacks):
        # A refresh deletes every pin and creates each one again, and a create
        # has no delete to share a notice with.
        for name in ("a", "b", "c"):
            _sbom(app, name)
        latest = Release.get_or_create_latest_release(app.product)
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            latest.refresh_latest_artifacts()

        told = [
            c.kwargs["data"]["release_id"] for c in sent.call_args_list if c.kwargs["message_type"] == "release_updated"
        ]
        assert told.count(str(app.id)) == 1
        assert told.count(str(latest.id)) == 1
        assert sum(type(callback).__name__ == "_ReleasesToTell" for callback in callbacks) == 1

    def test_a_refresh_that_rolls_back_tells_nobody(self, app, django_capture_on_commit_callbacks):
        from django.db import transaction

        _sbom(app, "a")
        latest = Release.get_or_create_latest_release(app.product)

        with django_capture_on_commit_callbacks() as callbacks:
            with pytest.raises(RuntimeError), transaction.atomic():
                latest.refresh_latest_artifacts()
                raise RuntimeError

        assert not any(type(callback).__name__ == "_ReleasesToTell" for callback in callbacks)

    def test_a_newer_sbom_replacing_the_newest(self, app, mocker, django_capture_on_commit_callbacks):
        shipped = _sbom(app, "kernel")
        sent = mocker.patch(BROADCAST)

        with django_capture_on_commit_callbacks(execute=True):
            SBOM.objects.create(
                name="kernel", version="2", component=shipped.component, format="cyclonedx", format_version="1.6"
            )

        assert str(app.id) in self._told(sent)
