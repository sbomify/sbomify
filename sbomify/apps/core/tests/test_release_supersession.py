"""Declaring what a release supersedes, withdrawing and archiving it, and showing where it stands."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.models import Release, ReleaseSupersession
from sbomify.apps.core.schemas import ReleaseResponseSchema
from sbomify.apps.core.services.cle import create_cle_event, create_release_cle_event
from sbomify.apps.core.services.release_lifecycle import set_release_state
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import Product
from sbomify.apps.teams.models import Member, Workspace

pytestmark = pytest.mark.django_db

PAST = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)


def _release(product: Product, name: str, **fields: Any) -> Release:
    return Release.objects.create(product=product, name=name, version=name, **fields)


def _on(day: datetime) -> dict[str, datetime]:
    return {"created_at": day, "released_at": day}


def _state(release: Release) -> str:
    return Release.objects.select_related("product").get(pk=release.pk).lifecycle_state


def _edges(predecessor: Release) -> list[ReleaseSupersession]:
    return list(ReleaseSupersession.objects.live().filter(from_release=predecessor))


def _supersede(predecessor: Release, successor: Release) -> None:
    result = create_release_cle_event(
        predecessor, "supersededBy", PAST, superseded_by_version=successor.version, drop_in=True
    )
    assert result.ok, result.error


class TestCreateWithSupersedes:
    def _create(self, api: tuple[Client, AccessToken], product: Product, prefix: str = "v1", **body: Any) -> Any:
        client, token = api
        return client.post(
            f"/api/{prefix}/releases",
            data={"product_id": product.pk, **body},
            content_type="application/json",
            **get_api_headers(token),
        )

    def test_by_release_id_defaults_to_drop_in(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.0.0")
        response = self._create(
            authenticated_api_client,
            sample_product,
            name="1.0.1",
            version="1.0.1",
            supersedes=[{"release_id": old.pk}],
        )
        assert response.status_code == 201, response.content
        new = Release.objects.get(pk=response.json()["id"])

        (edge,) = _edges(old)
        assert edge.to_release == new
        assert edge.drop_in is True
        assert _state(old) == Release.LifecycleState.SUPERSEDED
        assert response.json()["lifecycle_state"] == "active"
        assert response.json()["is_tracked"] is True

    def test_by_version_as_an_upgrade_path_keeps_the_old_release_monitored(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.0.0")
        response = self._create(
            authenticated_api_client,
            sample_product,
            name="2.0.0",
            version="2.0.0",
            supersedes=[{"version": "1.0.0", "drop_in": False}],
        )
        assert response.status_code == 201, response.content
        (edge,) = _edges(old)
        assert edge.drop_in is False
        assert _state(old) == Release.LifecycleState.ACTIVE

    def test_v2_takes_the_same_field(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.0.0")
        response = self._create(
            authenticated_api_client, sample_product, "v2", name="1.0.1", version="1.0.1", supersedes=[{"version": "1.0.0"}]
        )
        assert response.status_code == 201, response.content
        assert _state(old) == Release.LifecycleState.SUPERSEDED

    @pytest.mark.parametrize(
        "item",
        [
            {"version": "0.9.9"},
            {"release_id": "missing00000"},
        ],
    )
    def test_an_unknown_predecessor_fails_the_whole_create(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product, item: dict[str, str]
    ) -> None:
        response = self._create(authenticated_api_client, sample_product, name="1.0.1", supersedes=[item])
        assert response.status_code == 400, response.content
        assert not Release.objects.filter(product=sample_product, name="1.0.1").exists()

    def test_a_release_from_another_product_is_refused(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        elsewhere = Product.objects.create(team_id=sample_product.team_id, name="another product")
        foreign = _release(elsewhere, "1.0.0")
        response = self._create(
            authenticated_api_client, sample_product, name="1.0.1", supersedes=[{"release_id": foreign.pk}]
        )
        assert response.status_code == 400, response.content
        assert "another product" in response.json()["detail"]
        assert not Release.objects.filter(product=sample_product, name="1.0.1").exists()
        assert _edges(foreign) == []

    def test_latest_cannot_be_superseded(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        response = self._create(
            authenticated_api_client, sample_product, name="1.0.1", supersedes=[{"release_id": latest.pk}]
        )
        assert response.status_code == 400, response.content
        assert not Release.objects.filter(product=sample_product, name="1.0.1").exists()

    @pytest.mark.parametrize("item", [{}, {"release_id": "abc", "version": "1.0.0"}])
    def test_an_item_names_exactly_one_predecessor(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product, item: dict[str, str]
    ) -> None:
        response = self._create(authenticated_api_client, sample_product, name="1.0.1", supersedes=[item])
        assert response.status_code == 422, response.content

    def test_a_retried_create_adds_no_second_edge(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.0.0")
        body = {"name": "1.0.1", "version": "1.0.1", "supersedes": [{"version": "1.0.0"}]}
        assert self._create(authenticated_api_client, sample_product, **body).status_code == 201
        assert self._create(authenticated_api_client, sample_product, **body).status_code == 200
        assert len(_edges(old)) == 1


    def test_a_release_lists_every_previous_and_next_release(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        maintained = _release(sample_product, "1.2.1")
        assert self._create(
            authenticated_api_client,
            sample_product,
            name="2.0",
            version="2.0",
            supersedes=[{"version": "1.2.1", "drop_in": False}],
        ).status_code == 201
        assert self._create(
            authenticated_api_client, sample_product, name="1.2.2", version="1.2.2", supersedes=[{"version": "1.2.1"}]
        ).status_code == 201

        old = client.get(f"/api/v1/releases/{maintained.pk}", **get_api_headers(token)).json()
        major = client.get(
            f"/api/v1/releases/{Release.objects.get(product=sample_product, name='2.0').pk}", **get_api_headers(token)
        ).json()

        assert old["predecessors"] == []
        assert {(edge["name"], edge["drop_in"]) for edge in old["successors"]} == {("2.0", False), ("1.2.2", True)}
        assert [(edge["release_id"], edge["drop_in"]) for edge in major["predecessors"]] == [(maintained.pk, False)]
        assert old["lifecycle_state"] == "superseded"
        assert major["lifecycle_state"] == "active"

    def test_an_edge_declared_before_the_release_existed_is_linked_not_refused(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.2.3")
        # CI named the successor before it existed, so the edge was stored unlinked.
        early = create_release_cle_event(old, "supersededBy", PAST, superseded_by_version="1.2.4", drop_in=True)
        assert early.ok
        assert [edge.to_release_id for edge in _edges(old)] == [None]

        response = self._create(
            authenticated_api_client,
            sample_product,
            name="1.2.4",
            version="1.2.4",
            created_at=PAST.isoformat(),
            released_at=PAST.isoformat(),
            supersedes=[{"version": "1.2.3"}],
        )

        assert response.status_code == 201, response.content
        new = response.json()["id"]
        assert [edge.to_release_id for edge in _edges(old)] == [new]
        assert _state(old) == Release.LifecycleState.SUPERSEDED

    def test_restating_an_earlier_edge_differently_is_refused_with_a_way_out(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.2.3")
        assert create_release_cle_event(old, "supersededBy", PAST, superseded_by_version="1.2.4").ok

        response = self._create(
            authenticated_api_client, sample_product, name="1.2.4", version="1.2.4", supersedes=[{"version": "1.2.3"}]
        )

        assert response.status_code == 409, response.content
        assert response.json()["error_code"] == "CONFLICT"
        assert "Remove that link first" in response.json()["detail"]
        assert not Release.objects.filter(product=sample_product, name="1.2.4").exists()
        assert [edge.drop_in for edge in _edges(old)] == [False]

    def test_a_conflict_is_a_409_through_create_and_through_cle(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        old = _release(sample_product, "1.2.3", **_on(datetime(2024, 12, 1, tzinfo=dt_timezone.utc)))
        new = _release(sample_product, "1.2.4", **_on(PAST))
        assert create_release_cle_event(old, "supersededBy", PAST, superseded_by_version="1.2.4", drop_in=True).ok

        through_cle = client.post(
            f"/api/v1/releases/{old.pk}/cle/events",
            data={"event_type": "supersededBy", "effective": PAST.isoformat(), "superseded_by_version": "1.2.4"},
            content_type="application/json",
            **get_api_headers(token),
        )
        # The retry path: the release exists, so create returns it and declares the edge.
        through_create = self._create(
            authenticated_api_client,
            sample_product,
            name=new.name,
            version=new.version,
            supersedes=[{"version": "1.2.3", "drop_in": False}],
        )

        assert through_cle.status_code == 409, through_cle.content
        assert through_create.status_code == 409, through_create.content
        assert through_create.json()["error_code"] == "CONFLICT"
        assert [edge.drop_in for edge in _edges(old)] == [True]

    def test_an_edge_declared_early_with_another_date_is_the_same_edge(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old = _release(sample_product, "1.2.3")
        # CI named the successor before it existed, on a date the release does not carry.
        assert create_release_cle_event(old, "supersededBy", PAST, superseded_by_version="1.2.4", drop_in=True).ok

        response = self._create(
            authenticated_api_client, sample_product, name="1.2.4", version="1.2.4", supersedes=[{"version": "1.2.3"}]
        )

        assert response.status_code == 201, response.content
        assert [edge.to_release_id for edge in _edges(old)] == [response.json()["id"]]
        assert ReleaseSupersession.objects.filter(from_release=old).count() == 1
        assert old.cle_events.filter(event_type="supersededBy").count() == 1
        assert _state(old) == Release.LifecycleState.SUPERSEDED

    def test_a_publish_scoped_token_cannot_retire_releases(self, sample_product: Product, sample_user: Any) -> None:
        old = _release(sample_product, "1.0.0")
        encoded = create_personal_access_token(sample_user)
        AccessToken.objects.create(
            user=sample_user,
            encoded_token=encoded,
            description="publish",
            team_id=sample_product.team_id,
            scopes=SCOPE_PRESETS["publish"],
        )
        Member.objects.get_or_create(team_id=sample_product.team_id, user=sample_user, defaults={"role": "owner"})
        client = Client(HTTP_AUTHORIZATION=f"Bearer {encoded}")

        def create(**body: Any) -> Any:
            return client.post(
                "/api/v1/releases",
                data={"product_id": sample_product.pk, "name": "1.0.1", "version": "1.0.1", **body},
                content_type="application/json",
            )

        refused = create(supersedes=[{"version": "1.0.0"}])
        assert refused.status_code == 403, refused.content
        assert "manage releases" in refused.json()["detail"]
        assert not Release.objects.filter(product=sample_product, name="1.0.1").exists()

        assert create().status_code == 201
        # The same caller cannot add edges by retrying against the release it just made.
        assert create(supersedes=[{"version": "1.0.0"}]).status_code == 403
        assert _edges(old) == []


class TestLifecycleEndpoint:
    def _act(self, api: tuple[Client, AccessToken], release: Release, **body: Any) -> Any:
        client, token = api
        return client.post(
            f"/api/v1/releases/{release.pk}/lifecycle",
            data=body,
            content_type="application/json",
            **get_api_headers(token),
        )

    def test_withdraw_then_reactivate(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        release = _release(sample_product, "1.0.0")
        response = self._act(authenticated_api_client, release, action="withdraw", reason="compromised")
        assert response.status_code == 200, response.content
        assert response.json()["lifecycle_state"] == "withdrawn"
        assert response.json()["withdrawn_reason"] == "compromised"
        assert response.json()["withdrawn_at"] is not None

        response = self._act(authenticated_api_client, release, action="reactivate")
        assert response.status_code == 200, response.content
        assert response.json()["lifecycle_state"] == "active"

    def test_withdrawing_a_successor_hands_its_predecessor_back(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        _supersede(old, new)
        assert _state(old) == Release.LifecycleState.SUPERSEDED

        assert self._act(authenticated_api_client, new, action="withdraw", reason="defective").status_code == 200
        assert _state(old) == Release.LifecycleState.ACTIVE

    def test_archive(self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product) -> None:
        release = _release(sample_product, "1.0.0")
        response = self._act(authenticated_api_client, release, action="archive")
        assert response.status_code == 200, response.content
        assert response.json()["lifecycle_state"] == "archived"
        assert response.json()["is_tracked"] is False

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"action": "withdraw"}, 400),
            ({"action": "delete"}, 422),
        ],
    )
    def test_invalid_requests_are_refused(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        sample_product: Product,
        body: dict[str, str],
        status: int,
    ) -> None:
        release = _release(sample_product, "1.0.0")
        assert self._act(authenticated_api_client, release, **body).status_code == status
        assert _state(release) == Release.LifecycleState.ACTIVE

    def test_latest_is_refused(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        latest = Release.objects.create(product=sample_product, name="latest", is_latest=True)
        assert self._act(authenticated_api_client, latest, action="archive").status_code == 400

    def test_an_operator_cannot_withdraw(
        self, guest_api_client: tuple[Client, AccessToken], guest_user: AbstractBaseUser, sample_product: Product
    ) -> None:
        Member.objects.create(team_id=sample_product.team_id, user=guest_user, role="operator")
        release = _release(sample_product, "1.0.0")
        response = self._act(guest_api_client, release, action="withdraw", reason="defective")
        assert response.status_code == 403, response.content
        assert _state(release) == Release.LifecycleState.ACTIVE

    def test_a_release_response_says_where_it_stands(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        old, new = _release(sample_product, "1.0.0"), _release(sample_product, "1.0.1")
        _supersede(old, new)
        client, token = authenticated_api_client
        data = client.get(f"/api/v1/releases/{old.pk}", **get_api_headers(token)).json()
        assert data["lifecycle_state"] == "superseded"
        assert data["is_tracked"] is False
        assert data["superseded_at"] is not None
        for field in ("end_of_support", "end_of_life", "withdrawn_at", "withdrawn_reason", "archived_at"):
            assert field in data


class TestNewReleasePage:
    def test_the_newest_stable_release_is_offered_first(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        Release.objects.create(product=product, name="latest", is_latest=True)
        older = _release(product, "1.0.0", **_on(datetime(2026, 1, 1, tzinfo=dt_timezone.utc)))
        stable = _release(product, "1.1.0", **_on(datetime(2026, 2, 1, tzinfo=dt_timezone.utc)))
        candidate = _release(product, "1.2.0-rc1", is_prerelease=True, **_on(datetime(2026, 3, 1, tzinfo=dt_timezone.utc)))
        retired = _release(product, "0.9.0", **_on(datetime(2025, 1, 1, tzinfo=dt_timezone.utc)))
        set_release_state(retired, "archive")

        response = authenticated_web_client.get(reverse("core:release_new"), {"product": product.id})
        assert response.status_code == 200
        form = response.context["form"]
        # Newest first. latest and anything sbomify no longer monitors are not offered.
        assert [value for value, _label in form.fields["replaces"].choices if value] == [
            candidate.pk,
            stable.pk,
            older.pk,
        ]
        # A prerelease is offered but never chosen for you.
        assert form["replaces"].value() == stable.pk

    def test_changing_the_product_offers_its_releases(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        release = _release(product, "3.4.0")
        response = authenticated_web_client.get(
            reverse("core:release_new"), {"product_id": product.id}, headers={"HX-Request": "true"}
        )
        assert response.status_code == 200
        assert 'id="release-replaces"' in response.content.decode()
        assert release.pk in [value for value, _label in response.context["form"].fields["replaces"].choices]

    def test_a_prerelease_gets_no_default_when_the_product_changes(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        stable = _release(product, "3.4.0")
        response = authenticated_web_client.get(
            reverse("core:release_new"), {"product_id": product.id, "is_prerelease": "on"}, headers={"HX-Request": "true"}
        )
        assert response.status_code == 200
        form = response.context["form"]
        assert stable.pk in [value for value, _label in form.fields["replaces"].choices]
        assert not form["replaces"].value()
        # The product select sends the checkbox along, so the reload knows.
        assert 'hx-include="#release-prerelease"' in response.content.decode()

    @pytest.mark.parametrize(("line", "drop_in"), [("same", True), ("new", False)])
    def test_creating_a_release_that_replaces_another(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace, line: str, drop_in: bool
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        old = _release(product, "1.0.0")
        response = authenticated_web_client.post(
            reverse("core:release_new"),
            {"product_id": product.id, "name": "1.0.1", "version": "1.0.1", "replaces": old.pk, "replaces_line": line},
        )
        assert response.status_code == 302, response.context and response.context["form"].errors
        (edge,) = _edges(old)
        assert edge.drop_in is drop_in
        assert edge.to_release == Release.objects.get(product=product, name="1.0.1")

    def test_a_release_from_another_product_cannot_be_replaced(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        other = Product.objects.create(team=team_with_business_plan, name="Console")
        foreign = _release(other, "1.0.0")
        response = authenticated_web_client.post(
            reverse("core:release_new"),
            {"product_id": product.id, "name": "1.0.1", "replaces": foreign.pk, "replaces_line": "same"},
        )
        assert response.status_code == 200
        assert response.context["form"].errors["replaces"]
        assert not Release.objects.filter(product=product, name="1.0.1").exists()


class TestWhereAReleaseStands:
    def test_the_details_page_shows_the_state_and_offers_the_actions(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        old, new, major = _release(product, "1.0.0"), _release(product, "1.0.1"), _release(product, "2.0.0")
        _supersede(old, new)
        assert create_release_cle_event(old, "supersededBy", PAST, superseded_by_version="2.0.0").ok

        content = authenticated_web_client.get(reverse("core:release_details", args=[product.id, old.id])).content
        page = content.decode()
        assert "Superseded" in page
        assert "Next releases" in page
        assert "Same line, replaces this release" in page and "New line" in page
        # The state badge says whether a release is monitored; the links only say how releases relate.
        assert "stays monitored" not in page and "still monitored" not in page
        assert "Withdraw release" in page and "Archive release" in page

        page = authenticated_web_client.get(reverse("core:release_details", args=[product.id, major.id])).content
        assert "Previous releases" in page.decode() and "New line" in page.decode()
        assert "still monitored" not in page.decode()

    def test_withdrawing_from_the_details_page(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        release = _release(product, "1.0.0")
        url = reverse("core:release_lifecycle", args=[product.id, release.id])

        response = authenticated_web_client.post(url, {"action": "withdraw", "reason": "published_in_error"})
        assert response.status_code == 302
        assert response["Location"] == reverse("core:release_details", args=[product.id, release.id])
        assert _state(release) == Release.LifecycleState.WITHDRAWN

        page = authenticated_web_client.get(response["Location"]).content.decode()
        assert "Withdrawn" in page and "Reactivate release" in page

        authenticated_web_client.post(url, {"action": "reactivate"})
        assert _state(release) == Release.LifecycleState.ACTIVE

    def test_the_releases_list_marks_a_retired_release(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        set_release_state(_release(product, "1.0.0"), "withdraw", reason="defective")
        page = authenticated_web_client.get(reverse("core:product_releases", args=[product.id])).content.decode()
        assert "Withdrawn" in page

    def test_the_trust_center_marks_a_superseded_release(self) -> None:
        workspace = Workspace.objects.create(name="Public Test Team", is_public=True)
        product = Product.objects.create(name="Public product", team=workspace, is_public=True)
        old, new = _release(product, "1.0.0"), _release(product, "1.0.1")
        _supersede(old, new)

        for name in ("core:product_details_public", "core:product_releases_public"):
            page = Client().get(reverse(name, kwargs={"product_id": product.id})).content.decode()
            assert "Superseded" in page, name
        page = Client().get(reverse("core:release_details_public", args=[product.id, old.id])).content.decode()
        assert "Superseded" in page


class TestNameCollision:
    """Creating a release under a name the product already uses writes nothing new onto that release."""

    def test_the_api_refuses_to_add_edges_to_an_existing_release(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        _release(sample_product, "1.0", **_on(datetime(2026, 1, 1, tzinfo=dt_timezone.utc)))
        newest = _release(sample_product, "1.1", **_on(datetime(2026, 2, 1, tzinfo=dt_timezone.utc)))

        response = client.post(
            "/api/v1/releases",
            data={"product_id": sample_product.pk, "name": "1.0", "supersedes": [{"release_id": newest.pk}]},
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 409, response.content
        assert "1.0 already exists" in response.json()["detail"]
        assert _edges(newest) == []
        assert _state(newest) == Release.LifecycleState.ACTIVE

    def test_the_form_reports_the_name_and_writes_no_edge(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        _release(product, "1.0", **_on(datetime(2026, 1, 1, tzinfo=dt_timezone.utc)))
        newest = _release(product, "1.1", **_on(datetime(2026, 2, 1, tzinfo=dt_timezone.utc)))

        response = authenticated_web_client.post(
            reverse("core:release_new"),
            {"product_id": product.id, "name": "1.0", "replaces": newest.pk, "replaces_line": "same"},
        )

        assert response.status_code == 200
        assert "already exists" in " ".join(response.context["form"].non_field_errors())
        assert _edges(newest) == []


class TestChoosingTheLine:
    """Replacing a release is a decision: the form never picks same line or new line for you."""

    def test_no_line_is_chosen_for_you(self, authenticated_web_client: Client, team_with_business_plan: Workspace) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        stable = _release(product, "1.2.4")

        form = authenticated_web_client.get(reverse("core:release_new"), {"product": product.id}).context["form"]

        assert form["replaces"].value() == stable.pk
        assert not form["replaces_line"].value()

    def test_a_backport_without_a_line_is_not_created(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        _release(product, "1.2.4", **_on(datetime(2026, 3, 1, tzinfo=dt_timezone.utc)))
        major = _release(product, "2.0.0", **_on(datetime(2026, 9, 1, tzinfo=dt_timezone.utc)))

        response = authenticated_web_client.post(
            reverse("core:release_new"), {"product_id": product.id, "name": "1.2.5", "replaces": major.pk}
        )

        assert response.status_code == 200
        assert response.context["form"].errors["replaces_line"]
        assert not Release.objects.filter(product=product, name="1.2.5").exists()
        assert _state(major) == Release.LifecycleState.ACTIVE

    def test_a_backport_on_a_new_line_keeps_the_major_monitored(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        major = _release(product, "2.0.0", **_on(datetime(2026, 9, 1, tzinfo=dt_timezone.utc)))

        response = authenticated_web_client.post(
            reverse("core:release_new"),
            {"product_id": product.id, "name": "1.2.5", "replaces": major.pk, "replaces_line": "new"},
        )

        assert response.status_code == 302
        assert _state(major) == Release.LifecycleState.ACTIVE

    def test_a_release_cannot_replace_one_released_after_it_on_the_same_line(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        major = _release(sample_product, "2.0.0", **_on(datetime(2026, 9, 1, tzinfo=dt_timezone.utc)))
        historical = {"product_id": sample_product.pk, "name": "0.9", **{k: v.isoformat() for k, v in _on(PAST).items()}}

        refused = client.post(
            "/api/v1/releases",
            data={**historical, "supersedes": [{"release_id": major.pk}]},
            content_type="application/json",
            **get_api_headers(token),
        )
        upgrade_path = client.post(
            "/api/v1/releases",
            data={**historical, "supersedes": [{"release_id": major.pk, "drop_in": False}]},
            content_type="application/json",
            **get_api_headers(token),
        )

        assert refused.status_code == 400, refused.content
        assert "released after" in refused.json()["detail"]
        assert upgrade_path.status_code == 201, upgrade_path.content
        assert _state(major) == Release.LifecycleState.ACTIVE

    def test_a_prerelease_replaces_nothing_even_if_the_page_script_never_ran(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        # The box clears Replaces in the browser, but a submit that beats Alpine still carries the preselection.
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        stable = _release(product, "1.2.4", **_on(datetime(2026, 3, 1, tzinfo=dt_timezone.utc)))

        response = authenticated_web_client.post(
            reverse("core:release_new"),
            {"product_id": product.id, "name": "2.0.0-rc.1", "is_prerelease": "on", "replaces": stable.pk},
        )

        assert response.status_code == 302
        candidate = Release.objects.get(product=product, name="2.0.0-rc.1")
        assert candidate.is_prerelease
        assert not ReleaseSupersession.objects.filter(to_release=candidate).exists()
        assert _state(stable) == Release.LifecycleState.ACTIVE

    def test_the_prerelease_box_clears_replaces_without_a_cached_ref(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        # Alpine caches $refs on first read, so a select HTMX swaps in later is invisible to it.
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        _release(product, "1.0.0")
        page = authenticated_web_client.get(reverse("core:release_new"), {"product": product.id}).content.decode()
        assert "$refs.replaces" not in page and 'x-ref="replaces"' not in page
        assert "getElementById('release-replaces-select')" in page


class TestWithdrawnReason:
    """Why a release was withdrawn is internal. The Trust Center only says that it was."""

    def _public_withdrawn(self) -> Release:
        workspace = Workspace.objects.create(name="Public Test Team", is_public=True)
        product = Product.objects.create(name="Public product", team=workspace, is_public=True)
        release = _release(product, "2.3.1")
        assert set_release_state(release, "withdraw", reason="compromised").ok
        return release

    @pytest.mark.parametrize("prefix", ["v1", "v2"])
    def test_anonymous_readers_do_not_see_it(self, prefix: str) -> None:
        release = self._public_withdrawn()
        single = Client().get(f"/api/{prefix}/releases/{release.pk}")
        listed = Client().get(f"/api/{prefix}/releases", {"product_id": release.product_id})

        assert single.status_code == 200, single.content
        assert single.json()["withdrawn_reason"] is None
        assert single.json()["lifecycle_state"] == "withdrawn"
        assert listed.status_code == 200, listed.content
        assert [item["withdrawn_reason"] for item in listed.json()["items"] if item["id"] == release.pk] == [None]

    def test_the_workspace_sees_it(
        self, authenticated_api_client: tuple[Client, AccessToken], sample_product: Product
    ) -> None:
        client, token = authenticated_api_client
        release = _release(sample_product, "2.3.1")
        assert set_release_state(release, "withdraw", reason="compromised").ok

        data = client.get(f"/api/v1/releases/{release.pk}", **get_api_headers(token)).json()

        assert data["withdrawn_reason"] == "compromised"


class TestRemoveLink:
    """A mistaken Replaces can be undone from the Lifecycle card."""

    def test_removing_a_link_brings_the_release_back_and_frees_the_delete(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        old, new = _release(product, "1.0.0"), _release(product, "2.0.0")
        _supersede(old, new)
        (edge,) = _edges(old)

        page = authenticated_web_client.get(reverse("core:release_details", args=[product.id, new.id])).content.decode()
        assert "Remove link" in page

        response = authenticated_web_client.post(
            reverse("core:release_lifecycle", args=[product.id, new.id]), {"action": "remove_link", "edge_id": edge.pk}
        )

        assert response.status_code == 302
        assert _edges(old) == []
        assert ReleaseSupersession.objects.get(pk=edge.pk).cle_event.release.cle_events.filter(
            event_type="withdrawn"
        ).exists()
        assert _state(old) == Release.LifecycleState.ACTIVE

    def test_a_link_of_another_release_is_not_removed_from_this_page(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        old, new, bystander = _release(product, "1.0.0"), _release(product, "2.0.0"), _release(product, "3.0.0")
        _supersede(old, new)
        (edge,) = _edges(old)

        authenticated_web_client.post(
            reverse("core:release_lifecycle", args=[product.id, bystander.id]),
            {"action": "remove_link", "edge_id": edge.pk},
        )

        assert _edges(old) == [edge]

    def test_the_trust_center_never_offers_it(self) -> None:
        workspace = Workspace.objects.create(name="Public Test Team", is_public=True)
        product = Product.objects.create(name="Public product", team=workspace, is_public=True)
        old, new = _release(product, "1.0.0"), _release(product, "1.0.1")
        _supersede(old, new)

        page = Client().get(reverse("core:release_details_public", args=[product.id, old.id])).content.decode()

        assert "Remove link" not in page


class TestTrustCenterWithdrawn:
    def test_a_withdrawn_release_wears_the_outline_badge(self) -> None:
        workspace = Workspace.objects.create(name="Public Test Team", is_public=True)
        product = Product.objects.create(name="Public product", team=workspace, is_public=True)
        release = _release(product, "2.3.1")
        assert set_release_state(release, "withdraw", reason="defective").ok

        page = Client().get(reverse("core:release_details_public", args=[product.id, release.id])).content.decode()

        badge = page[page.index("Withdrawn") - 600 : page.index("Withdrawn")]
        assert "border-dashed" in badge


class TestEffectiveDates:
    def test_the_response_and_the_card_show_the_dates_that_apply(
        self,
        authenticated_api_client: tuple[Client, AccessToken],
        authenticated_web_client: Client,
        sample_product: Product,
    ) -> None:
        client, token = authenticated_api_client
        release = _release(sample_product, "1.0.0")
        every = create_cle_event(sample_product, "endOfSupport", PAST, versions=[{"range": "vers:generic/*"}])
        assert every.ok

        data = client.get(f"/api/v1/releases/{release.pk}", **get_api_headers(token)).json()

        assert data["end_of_support"] is None
        assert data["effective_end_of_support"] == "2025-01-01"
        assert data["lifecycle_state"] == "end_of_support"

    def test_a_product_date_for_some_versions_is_not_shown_as_the_release_date(
        self, authenticated_web_client: Client, team_with_business_plan: Workspace
    ) -> None:
        product = Product.objects.create(team=team_with_business_plan, name="Gateway")
        release = _release(product, "2.0.0")
        scoped = create_cle_event(product, "endOfSupport", PAST, versions=[{"range": "vers:semver/<2.0.0"}])
        assert scoped.ok

        page = authenticated_web_client.get(reverse("core:release_details", args=[product.id, release.id]))

        assert "End of support" not in page.content.decode()

    def test_is_tracked_says_what_it_covers(self) -> None:
        description = ReleaseResponseSchema.model_fields["is_tracked"].description or ""
        assert "links" in description
