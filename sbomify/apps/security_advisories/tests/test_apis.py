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
