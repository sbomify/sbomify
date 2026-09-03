"""The advisories API.

Advisories were the one domain with no API: the pages reached past it into the
services, the MCP server had no advisory tools to offer, and reading a trust
centre's advisories programmatically meant parsing HTML.

These drive the endpoints rather than the services underneath, because the
things that can be wrong here are the wire ones: who is allowed in, what the
contract says a field means, and whether one workspace can see another's.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.security_advisories.models import SecurityAdvisory

from .conftest import publish

pytestmark = pytest.mark.django_db

LIST = "/api/v1/advisories/"


def _detail(advisory_id: str) -> str:
    return f"/api/v1/advisories/{advisory_id}"


@pytest.fixture
def client_and_headers(authenticated_api_client, sample_team_with_owner_member):
    client, token = authenticated_api_client
    return client, get_api_headers(token)


class TestReadingThem:
    def test_the_workspace_sees_its_own(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        response = client.get(LIST, **headers)

        assert response.status_code == 200, response.content
        titles = [item["title"] for item in response.json()]
        assert "Log4Shell in Acme Gateway" in titles

    def test_another_workspace_is_not_listed(self, client_and_headers, other_team) -> None:
        client, headers = client_and_headers
        SecurityAdvisory.objects.create(team=other_team, title="Not yours")

        response = client.get(LIST, **headers)

        assert "Not yours" not in [item["title"] for item in response.json()]

    def test_another_workspace_advisory_is_not_readable(self, client_and_headers, other_team) -> None:
        client, headers = client_and_headers
        theirs = SecurityAdvisory.objects.create(team=other_team, title="Not yours")

        response = client.get(_detail(theirs.id), **headers)

        assert response.status_code == 404

    def test_an_unauthenticated_caller_is_refused(self, client_and_headers) -> None:
        client, _ = client_and_headers

        assert client.get(LIST).status_code in (401, 403)


class TestTheContract:
    def test_status_means_publication_and_the_fix_has_its_own_field(self, client_and_headers, advisory) -> None:
        """The projection behind this calls the fix's progress "status"; the
        model does not, and the wire follows the model."""
        client, headers = client_and_headers

        body = client.get(_detail(advisory.id), **headers).json()

        assert body["status"] == SecurityAdvisory.Status.DRAFT
        assert body["remediation_status"] == advisory.remediation_status
        assert body["id"] == advisory.id

    def test_no_presentation_fields_reach_the_wire(self, client_and_headers, advisory) -> None:
        """A badge variant and an icon name are for the pages, not a contract."""
        client, headers = client_and_headers

        body = client.get(_detail(advisory.id), **headers).json()

        for leaked in ("status_variant", "status_icon", "severity_rank", "updated_display", "pk"):
            assert leaked not in body

    def test_the_detail_carries_the_history(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        body = client.get(_detail(advisory.id), **headers).json()

        assert "timeline" in body
        assert "vulnerabilities" in body
        assert "references" in body


class TestWriting:
    def test_an_advisory_can_be_created(self, client_and_headers) -> None:
        client, headers = client_and_headers

        response = client.post(
            LIST,
            data={"title": "Heap overflow in parser", "severity": "high", "description": "Found in review"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["title"] == "Heap overflow in parser"
        assert body["status"] == SecurityAdvisory.Status.DRAFT
        assert SecurityAdvisory.objects.filter(id=body["id"]).exists()

    def test_a_title_is_required(self, client_and_headers) -> None:
        client, headers = client_and_headers

        response = client.post(LIST, data={"title": ""}, content_type="application/json", **headers)

        assert response.status_code == 422

    def test_a_product_from_another_workspace_is_not_attached(self, client_and_headers, other_team) -> None:
        """An id from elsewhere names no product here."""
        from sbomify.apps.core.models import Product

        client, headers = client_and_headers
        theirs = Product.objects.create(name="Their product", team=other_team)

        response = client.post(
            LIST,
            data={"title": "Scoped", "product_ids": [theirs.id]},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201, response.content
        assert response.json()["products"] == []

    def test_an_advisory_can_be_edited(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        response = client.patch(
            _detail(advisory.id),
            data={"title": "Log4Shell in Acme Gateway (revised)"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        assert response.json()["title"] == "Log4Shell in Acme Gateway (revised)"


class TestPublishing:
    def test_it_moves_both_axes(self, client_and_headers, advisory, make_publishable) -> None:
        """Status alone would leave it invisible; visibility alone would expose a draft.

        The advisory needs the graph publication validates, which is what
        ``make_publishable`` builds.
        """
        client, headers = client_and_headers

        response = client.post(
            f"{_detail(advisory.id)}/publish",
            data={"visibility": SecurityAdvisory.Visibility.PUBLIC},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == SecurityAdvisory.Status.PUBLISHED
        assert body["visibility"] == SecurityAdvisory.Visibility.PUBLIC
        assert body["tracking_id"], "publication allocates the workspace's own identifier"

    def test_an_incomplete_advisory_is_refused_with_its_reasons(self, client_and_headers, advisory) -> None:
        """Publication validates the whole graph, and the caller gets told why."""
        client, headers = client_and_headers

        response = client.post(
            f"{_detail(advisory.id)}/publish",
            data={"visibility": "public"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400, response.content
        assert response.json()["detail"]
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.DRAFT

    def test_another_workspace_advisory_cannot_be_published(self, client_and_headers, other_team) -> None:
        client, headers = client_and_headers
        theirs = SecurityAdvisory.objects.create(team=other_team, title="Not yours")

        response = client.post(
            f"{_detail(theirs.id)}/publish",
            data={"visibility": "public"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 404
        theirs.refresh_from_db()
        assert theirs.status == SecurityAdvisory.Status.DRAFT


class TestBothVersionsServeIt:
    def test_v2_serves_the_same_resource(self, client_and_headers, advisory) -> None:
        """A router born after the v2 work is cloned onto it without asking."""
        client, headers = client_and_headers

        response = client.get("/api/v2/advisories/", **headers)

        assert response.status_code == 200, response.content
        assert advisory.title in [item["title"] for item in response.json()]


class TestTrackingIds:
    def test_a_draft_reports_no_tracking_id(self, client_and_headers, advisory) -> None:
        """The page falls back to the record id on screen; the contract does not."""
        client, headers = client_and_headers

        body = client.get(_detail(advisory.id), **headers).json()

        assert body["id"] == advisory.id
        assert body["tracking_id"] == ""

    def test_a_published_advisory_reports_the_allocated_id(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers
        publish(advisory)

        body = client.get(_detail(advisory.id), **headers).json()

        assert body["tracking_id"] == advisory.tracking_id
        assert body["tracking_id"] != advisory.id


class TestPartialUpdates:
    def test_a_field_left_out_keeps_its_value(self, client_and_headers, team) -> None:
        client, headers = client_and_headers
        advisory = SecurityAdvisory.objects.create(
            team=team, title="Parser overflow", description="Found in review", severity="high"
        )

        response = client.patch(
            _detail(advisory.id),
            data={"title": "Parser overflow (revised)"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["title"] == "Parser overflow (revised)"
        assert body["description"] == "Found in review"
        assert body["severity"] == "high"

    def test_a_field_sent_blank_is_cleared(self, client_and_headers, team) -> None:
        client, headers = client_and_headers
        advisory = SecurityAdvisory.objects.create(team=team, title="Parser overflow", description="Found in review")

        response = client.patch(
            _detail(advisory.id), data={"description": ""}, content_type="application/json", **headers
        )

        assert response.status_code == 200, response.content
        assert response.json()["description"] == ""

    def test_cvss_is_written_as_a_pair_and_cleared_with_null(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers
        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"

        written = client.patch(
            _detail(advisory.id),
            data={"cvss_score": 9.8, "cvss_vector": vector},
            content_type="application/json",
            **headers,
        )
        assert written.status_code == 200, written.content
        assert written.json()["cvss_score"] == 9.8
        assert written.json()["cvss_vector"] == vector

        cleared = client.patch(
            _detail(advisory.id), data={"cvss_score": None}, content_type="application/json", **headers
        )
        assert cleared.status_code == 200, cleared.content
        assert cleared.json()["cvss_score"] is None
        assert cleared.json()["cvss_vector"] == ""


class TestWhoMayWrite:
    """Advisories are outward-facing, so every write sits at ADMINISTER, the same tier the pages use."""

    def test_a_member_can_read_but_not_write(
        self, client_and_headers, sample_team_with_owner_member, advisory, make_publishable
    ) -> None:
        client, headers = client_and_headers
        sample_team_with_owner_member.role = "member"
        sample_team_with_owner_member.save()

        assert client.get(LIST, **headers).status_code == 200
        assert client.get(_detail(advisory.id), **headers).status_code == 200

        created = client.post(LIST, data={"title": "Nope"}, content_type="application/json", **headers)
        edited = client.patch(_detail(advisory.id), data={"title": "Nope"}, content_type="application/json", **headers)
        published = client.post(
            f"{_detail(advisory.id)}/publish", data={"visibility": "public"}, content_type="application/json", **headers
        )
        assert (created.status_code, edited.status_code, published.status_code) == (403, 403, 403)
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.DRAFT
        assert advisory.title == "Log4Shell in Acme Gateway"

    def test_an_admin_may_write(self, client_and_headers, sample_team_with_owner_member) -> None:
        client, headers = client_and_headers
        sample_team_with_owner_member.role = "admin"
        sample_team_with_owner_member.save()

        response = client.post(LIST, data={"title": "Admin wrote this"}, content_type="application/json", **headers)

        assert response.status_code == 201, response.content


class TestWithdrawing:
    def test_a_published_advisory_can_be_withdrawn(self, client_and_headers, advisory, make_publishable) -> None:
        """The record keeps its id and its publication date; only the status and the reason move."""
        from sbomify.apps.security_advisories.models import AdvisoryEvent

        client, headers = client_and_headers
        client.post(
            f"{_detail(advisory.id)}/publish", data={"visibility": "public"}, content_type="application/json", **headers
        )
        advisory.refresh_from_db()
        tracking_id = advisory.tracking_id

        response = client.post(
            f"{_detail(advisory.id)}/withdraw",
            data={"reason": "The affected version range was wrong."},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == SecurityAdvisory.Status.WITHDRAWN
        assert body["tracking_id"] == tracking_id
        assert body["withdrawal_reason"] == "The affected version range was wrong."
        assert body["withdrawn_at"]
        assert body["published_at"]
        assert AdvisoryEvent.objects.filter(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.WITHDRAWN,
            body="The affected version range was wrong.",
        ).exists()

    def test_a_draft_cannot_be_withdrawn(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        response = client.post(
            f"{_detail(advisory.id)}/withdraw",
            data={"reason": "Never mind."},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 409, response.content
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.DRAFT

    def test_a_reason_is_required(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers
        publish(advisory)

        blank = client.post(
            f"{_detail(advisory.id)}/withdraw", data={"reason": "   "}, content_type="application/json", **headers
        )
        missing = client.post(f"{_detail(advisory.id)}/withdraw", data={}, content_type="application/json", **headers)

        assert blank.status_code == 400, blank.content
        assert missing.status_code == 422, missing.content
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.PUBLISHED

    def test_withdrawing_twice_is_a_conflict(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers
        publish(advisory)
        first = client.post(
            f"{_detail(advisory.id)}/withdraw", data={"reason": "Wrong."}, content_type="application/json", **headers
        )
        assert first.status_code == 200, first.content

        second = client.post(
            f"{_detail(advisory.id)}/withdraw",
            data={"reason": "Still wrong."},
            content_type="application/json",
            **headers,
        )

        assert second.status_code == 409


def _public(workspace_key: str, advisory_id: str | None = None, *, csaf: bool = False) -> str:
    url = f"/api/v1/advisories/public/{workspace_key}"
    if advisory_id is not None:
        url = f"{url}/{advisory_id}"
    return f"{url}/csaf" if csaf else url


@pytest.fixture
def public_product(team):
    """A product the trust center lists: public, with a public component."""
    from sbomify.apps.core.models import Component, Product

    product = Product.objects.create(name="Acme Gateway", team=team, is_public=True)
    component = Component.objects.create(name="gateway-core", team=team, visibility=Component.Visibility.PUBLIC)
    product.components.add(component)
    return product


@pytest.fixture
def unlisted_product(team):
    from sbomify.apps.core.models import Product

    return Product.objects.create(name="Skunkworks", team=team, is_public=False)


def _publish_for(team, products, *, visibility: str, title: str = "Advisory") -> SecurityAdvisory:
    from sbomify.apps.security_advisories.models import AdvisoryProduct

    advisory = SecurityAdvisory.objects.create(team=team, title=title, summary="Short version.")
    for product in products:
        AdvisoryProduct.objects.create(advisory=advisory, product=product)
    return publish(advisory, visibility=visibility)


class TestThePublicSide:
    """The trust center over JSON: the same rows, filtered by the same viewer scoping, with no auth needed."""

    def test_an_anonymous_reader_gets_the_public_advisories(self, client_and_headers, team, public_product) -> None:
        client, _ = client_and_headers
        advisory = _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC)

        response = client.get(_public(team.key))

        assert response.status_code == 200, response.content
        body = response.json()
        assert [item["tracking_id"] for item in body["items"]] == [advisory.tracking_id]
        item = body["items"][0]
        assert item["id"] == advisory.id
        assert item["status"] == SecurityAdvisory.Status.PUBLISHED
        assert item["products"] == [{"id": public_product.id, "name": "Acme Gateway"}]
        assert body["pagination"]["total"] == 1
        assert body["hidden_count"] == 0
        assert body["viewer_is_authenticated"] is False
        for leaked in ("pk", "status_variant", "severity_rank", "updated_display", "affected_rows"):
            assert leaked not in item

    def test_drafts_and_private_advisories_never_appear(self, client_and_headers, team, public_product) -> None:
        client, _ = client_and_headers
        SecurityAdvisory.objects.create(team=team, title="Still a draft")
        _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PRIVATE, title="Regulator only")

        body = client.get(_public(team.key)).json()

        assert body["items"] == []
        assert body["hidden_count"] == 0

    def test_a_gated_advisory_is_hidden_from_a_stranger_and_counted(
        self, client_and_headers, team, public_product
    ) -> None:
        """A 404 rather than a 403 on the detail: a 403 would confirm the advisory exists."""
        client, _ = client_and_headers
        advisory = _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.GATED)

        listed = client.get(_public(team.key)).json()
        detail = client.get(_public(team.key, advisory.tracking_id))
        csaf = client.get(_public(team.key, advisory.tracking_id, csaf=True))

        assert listed["items"] == []
        assert listed["hidden_count"] == 1
        assert detail.status_code == 404
        assert csaf.status_code == 404

    def test_a_gated_advisory_is_visible_to_a_workspace_token(self, client_and_headers, team, public_product) -> None:
        """A bearer token identifies the reader on the public side, which is what widens the scope."""
        client, headers = client_and_headers
        advisory = _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.GATED)

        listed = client.get(_public(team.key), **headers).json()
        detail = client.get(_public(team.key, advisory.tracking_id), **headers)

        assert [item["id"] for item in listed["items"]] == [advisory.id]
        assert listed["viewer_is_authenticated"] is True
        assert detail.status_code == 200, detail.content
        assert detail.json()["visibility"] == SecurityAdvisory.Visibility.GATED

    def test_products_the_reader_cannot_see_are_counted_not_named(
        self, client_and_headers, team, public_product, unlisted_product
    ) -> None:
        client, headers = client_and_headers
        advisory = _publish_for(team, [public_product, unlisted_product], visibility=SecurityAdvisory.Visibility.PUBLIC)

        anonymous = client.get(_public(team.key, advisory.id)).json()
        insider = client.get(_public(team.key, advisory.id), **headers).json()

        assert [p["name"] for p in anonymous["products"]] == ["Acme Gateway"]
        assert anonymous["withheld_product_count"] == 1
        assert sorted(p["name"] for p in insider["products"]) == ["Acme Gateway", "Skunkworks"]
        assert insider["withheld_product_count"] == 0

    def test_the_detail_carries_the_statuses_without_presentation(
        self, client_and_headers, team, public_product
    ) -> None:
        from sbomify.apps.security_advisories.models import (
            AdvisoryProductStatus,
            AdvisoryVersionRange,
            AdvisoryVulnerability,
        )

        client, _ = client_and_headers
        advisory = _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC)
        vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2021-44228")
        status = AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability,
            advisory_product=advisory.products.get(),
            status=AdvisoryProductStatus.Status.EXPLOITABLE,
            action_statement="Upgrade to 2.17.1.",
            recommended_version="2.17.1",
        )
        AdvisoryVersionRange.objects.create(product_status=status, introduced="2.0", fixed="2.17.1")

        body = client.get(_public(team.key, advisory.tracking_id)).json()

        assert body["cve_ids"] == ["CVE-2021-44228"]
        [row] = body["statuses"]
        assert row["product"] == "Acme Gateway"
        assert row["product_id"] == public_product.id
        assert row["status"] == AdvisoryProductStatus.Status.EXPLOITABLE
        assert row["affected"] == ">= 2.0, < 2.17.1"
        assert row["unaffected"] == ">= 2.17.1"
        assert row["recommended_version"] == "2.17.1"
        assert "status_variant" not in row
        assert body["timeline"] == []

    def test_search_narrows_the_list_like_the_page(self, client_and_headers, team, public_product) -> None:
        client, _ = client_and_headers
        _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC, title="Log4Shell")
        _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC, title="Heartbleed")

        body = client.get(_public(team.key), {"search": "heart"}).json()

        assert [item["title"] for item in body["items"]] == ["Heartbleed"]
        assert body["pagination"]["total"] == 1

    def test_a_private_workspace_is_not_found(self, client_and_headers, team, public_product) -> None:
        from sbomify.apps.teams.models import Team

        client, _ = client_and_headers
        _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC)
        Team.objects.filter(pk=team.pk).update(is_public=False)

        assert client.get(_public(team.key)).status_code == 404

    def test_an_unknown_workspace_is_not_found(self, client_and_headers) -> None:
        client, _ = client_and_headers

        assert client.get(_public("nope")).status_code == 404

    def test_a_withdrawn_advisory_stays_listed_with_its_reason(
        self, client_and_headers, team, public_product, sample_user
    ) -> None:
        from sbomify.apps.security_advisories.services.advisories import withdraw_advisory

        client, _ = client_and_headers
        advisory = _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC)
        assert withdraw_advisory(team, sample_user, advisory.id, reason="Duplicate of another advisory.").ok

        body = client.get(_public(team.key, advisory.tracking_id)).json()

        assert body["status"] == SecurityAdvisory.Status.WITHDRAWN
        assert body["is_withdrawn"] is True
        assert body["withdrawal_reason"] == "Duplicate of another advisory."
        assert body["tracking_id"] == advisory.tracking_id

    def test_v2_serves_the_public_side_too(self, client_and_headers, team, public_product) -> None:
        client, _ = client_and_headers
        advisory = _publish_for(team, [public_product], visibility=SecurityAdvisory.Visibility.PUBLIC)

        response = client.get(f"/api/v2/advisories/public/{team.key}/{advisory.tracking_id}")

        assert response.status_code == 200, response.content
        assert response.json()["tracking_id"] == advisory.tracking_id


class TestCvssPairs:
    def test_a_vector_without_a_score_is_refused(self, client_and_headers, advisory) -> None:
        """Not silently dropped: the service's own rule reaches the client."""
        client, headers = client_and_headers

        response = client.patch(
            _detail(advisory.id),
            data={"cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400, response.content
        assert "score" in response.json()["detail"].lower()

    def test_changing_the_score_alone_keeps_the_vector(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers
        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        client.patch(
            _detail(advisory.id),
            data={"cvss_score": 9.8, "cvss_vector": vector},
            content_type="application/json",
            **headers,
        )

        response = client.patch(
            _detail(advisory.id), data={"cvss_score": 9.1}, content_type="application/json", **headers
        )

        assert response.status_code == 200, response.content
        assert response.json()["cvss_score"] == 9.1
        assert response.json()["cvss_vector"] == vector


class TestAffectedReleases:
    @pytest.fixture
    def release(self, product):
        from sbomify.apps.core.models import Release

        return Release.objects.create(product=product, name="1.2.0", version="1.2.0")

    def test_a_release_becomes_an_affected_version(self, client_and_headers, product, release) -> None:
        client, headers = client_and_headers

        response = client.post(
            LIST,
            data={"title": "Scoped to 1.2.0", "product_ids": [product.id], "affected_release_ids": [release.id]},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201, response.content
        [named] = response.json()["products"]
        assert named["id"] == product.id
        assert any("1.2.0" in affected for affected in named["affected_ranges"]), named

    def test_a_release_of_an_unnamed_product_is_refused(self, client_and_headers, product, release, team) -> None:
        """The service holds releases to the products the advisory names; nothing half-built survives."""
        from sbomify.apps.core.models import Product

        client, headers = client_and_headers
        other = Product.objects.create(name="Acme Vault", team=team)

        response = client.post(
            LIST,
            data={"title": "Mismatched", "product_ids": [other.id], "affected_release_ids": [release.id]},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400, response.content
        assert not SecurityAdvisory.objects.filter(title="Mismatched").exists()

    def test_a_release_from_another_workspace_is_not_seen(self, client_and_headers, product, other_team) -> None:
        from sbomify.apps.core.models import Product, Release

        client, headers = client_and_headers
        theirs = Release.objects.create(
            product=Product.objects.create(name="Their product", team=other_team), name="9.9.9", version="9.9.9"
        )

        response = client.post(
            LIST,
            data={"title": "Blind", "product_ids": [product.id], "affected_release_ids": [theirs.id]},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201, response.content
        assert response.json()["products"][0]["affected_ranges"] == []


class TestTimelineUpdates:
    def test_a_note_lands_on_the_timeline(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        response = client.post(
            f"{_detail(advisory.id)}/updates",
            data={"kind": "update", "note": "Patch under test on staging."},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["remediation_status"] == advisory.remediation_status
        assert [e for e in body["timeline"] if e["kind"] == "update"][0]["body"] == "Patch under test on staging."

    def test_a_status_kind_moves_the_remediation_status(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        response = client.post(
            f"{_detail(advisory.id)}/updates",
            data={"kind": "fix_in_progress", "note": "Fix branch opened."},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["remediation_status"] == SecurityAdvisory.RemediationStatus.FIX_IN_PROGRESS
        assert body["is_open"] is True
        moved = [e for e in body["timeline"] if e["kind"] == "status_change"][0]
        assert (moved["from_status"], moved["to_status"]) == (advisory.remediation_status, "fix_in_progress")
        advisory.refresh_from_db()
        assert advisory.remediation_status == SecurityAdvisory.RemediationStatus.FIX_IN_PROGRESS

    def test_an_unknown_kind_and_an_empty_note_are_refused(self, client_and_headers, advisory) -> None:
        client, headers = client_and_headers

        unknown = client.post(
            f"{_detail(advisory.id)}/updates", data={"kind": "shipped"}, content_type="application/json", **headers
        )
        empty = client.post(
            f"{_detail(advisory.id)}/updates",
            data={"kind": "update", "note": " "},
            content_type="application/json",
            **headers,
        )

        assert unknown.status_code == 400
        assert empty.status_code == 400

    def test_a_member_may_not_post(self, client_and_headers, sample_team_with_owner_member, advisory) -> None:
        client, headers = client_and_headers
        sample_team_with_owner_member.role = "member"
        sample_team_with_owner_member.save()

        response = client.post(
            f"{_detail(advisory.id)}/updates",
            data={"kind": "resolved", "note": "Done."},
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403
        advisory.refresh_from_db()
        assert advisory.remediation_status != SecurityAdvisory.RemediationStatus.RESOLVED
