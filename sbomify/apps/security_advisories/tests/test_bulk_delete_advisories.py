"""The advisories table's bulk delete: the service and the view it posts to.

What matters: only the workspace's own advisories go, only for the roles that
may delete one, and a refused request leaves every advisory standing.
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import BULK_DELETE_LIMIT, delete_advisories
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def advisories(team):
    return [SecurityAdvisory.objects.create(team=team, title=f"Advisory {index}") for index in range(3)]


def _messages(response) -> list[dict[str, str]]:
    return json.loads(response["HX-Trigger"])["messages"]


class TestDeleteAdvisoriesService:
    def test_deletes_the_named_advisories_and_leaves_the_rest(self, team, advisories):
        result = delete_advisories(team, [advisories[0].id, advisories[2].id])

        assert result.ok
        assert result.value == 2
        assert list(SecurityAdvisory.objects.filter(team=team)) == [advisories[1]]

    def test_matches_a_tracking_id_like_the_single_delete(self, team, advisories):
        published = SecurityAdvisory.objects.create(
            team=team,
            title="Published",
            status="published",
            tracking_id="ACME-SA-2026-0001",
            published_at=timezone.now(),
        )

        assert delete_advisories(team, ["ACME-SA-2026-0001"]).value == 1
        assert not SecurityAdvisory.objects.filter(id=published.id).exists()

    def test_another_workspaces_advisory_is_never_touched(self, team, other_team, advisories):
        foreign = SecurityAdvisory.objects.create(team=other_team, title="Not yours")

        result = delete_advisories(team, [advisories[0].id, foreign.id])

        assert result.value == 1
        assert SecurityAdvisory.objects.filter(id=foreign.id).exists()

    def test_nothing_matching_is_a_404_and_deletes_nothing(self, team, other_team, advisories):
        foreign = SecurityAdvisory.objects.create(team=other_team, title="Not yours")

        result = delete_advisories(team, [foreign.id, "missing"])

        assert result.status_code == 404
        assert SecurityAdvisory.objects.filter(team=team).count() == 3

    def test_an_empty_selection_is_refused(self, team, advisories):
        assert delete_advisories(team, ["", "  "]).status_code == 400

    def test_more_than_the_limit_is_refused_before_anything_goes(self, team, advisories):
        ids = [advisories[0].id] + [f"x{index}" for index in range(BULK_DELETE_LIMIT)]

        assert delete_advisories(team, ids).status_code == 400
        assert SecurityAdvisory.objects.filter(team=team).count() == 3


class TestBulkDeleteView:
    url = reverse("core:security_advisories_bulk_delete")

    def test_owner_deletes_and_the_table_is_told_to_refresh(self, sample_team_with_owner_member, advisories, client):
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(self.url, {"ids": [advisories[0].id, advisories[1].id]}, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        trigger = json.loads(response["HX-Trigger"])
        assert trigger["refresh-advisories"] is True
        assert trigger["messages"] == [{"type": "success", "message": "Deleted 2 advisories."}]
        assert SecurityAdvisory.objects.filter(team=member.team).count() == 1

    def test_one_advisory_reads_as_one(self, sample_team_with_owner_member, advisories, client):
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(self.url, {"ids": [advisories[0].id]}, HTTP_HX_REQUEST="true")

        assert _messages(response)[0]["message"] == "Deleted 1 advisory."

    @pytest.mark.parametrize("role", ["member", "operator"])
    def test_roles_that_cannot_delete_one_cannot_delete_many(
        self, sample_team_with_owner_member, advisories, guest_user, client, role
    ):
        team = sample_team_with_owner_member.team
        Member.objects.create(team=team, user=guest_user, role=role)
        setup_authenticated_client_session(client, team, guest_user)

        response = client.post(self.url, {"ids": [advisory.id for advisory in advisories]}, HTTP_HX_REQUEST="true")

        assert response["HX-Reswap"] == "none"
        assert _messages(response)[0]["type"] == "error"
        assert SecurityAdvisory.objects.filter(team=team).count() == 3

    def test_a_failure_is_reported_and_keeps_the_selection(self, sample_team_with_owner_member, advisories, client):
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(self.url, {"ids": ["missing"]}, HTTP_HX_REQUEST="true")

        assert response["HX-Reswap"] == "none"
        assert _messages(response) == [{"type": "error", "message": "Advisories not found"}]

    def test_anonymous_is_sent_to_sign_in(self, advisories, client):
        response = client.post(self.url, {"ids": [advisories[0].id]})

        assert response.status_code == 302
        assert SecurityAdvisory.objects.count() == 3


class TestTableOffersBulkDeleteOnlyToWriters:
    table_url = reverse("core:security_advisories_dashboard")

    def test_owner_sees_the_select_column_and_the_dialog(self, sample_team_with_owner_member, advisories, client):
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        html = client.get(self.table_url).content.decode()

        assert 'x-data="tableSelection"' in html
        assert "data-row-select-all" in html
        assert f'hx-post="{reverse("core:security_advisories_bulk_delete")}"' in html

    def test_member_gets_no_select_column(self, sample_team_with_owner_member, advisories, guest_user, client):
        team = sample_team_with_owner_member.team
        Member.objects.create(team=team, user=guest_user, role="member")
        setup_authenticated_client_session(client, team, guest_user)

        html = client.get(self.table_url).content.decode()

        assert "data-row-select-all" not in html
        assert "data-bulk-delete-form" not in html
