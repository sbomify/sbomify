"""The wire during the rename: both names, one value, codes frozen.

`is_default_team` has a live consumer. The sbomify action's CLI wizard reads it
to pick a workspace, and a missing field there fails *silently*: `.get()`
returns None, the picker falls through to the first workspace in the list, and
uploads land somewhere the user did not choose. So the old name ships beside
the new one until the action has shipped a release that prefers the new one.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from sbomify.apps.core.schemas import ErrorCode
from sbomify.apps.core.tests.shared_fixtures import get_api_headers


@pytest.mark.django_db
class TestMemberSchemaDuringTheRename:
    def _members(self, client: Client, token, team) -> list[dict]:
        response = client.get(f"/api/v1/workspaces/{team.key}", **get_api_headers(token))
        assert response.status_code == 200, response.content
        return json.loads(response.content)["members"]

    def test_both_names_are_served(self, authenticated_api_client, sample_team_with_owner_member):
        client, token = authenticated_api_client
        members = self._members(client, token, sample_team_with_owner_member.team)

        assert members, "no members serialised"
        for member in members:
            assert "is_default_team" in member, "the action still reads this one"
            assert "is_default_workspace" in member

    def test_they_never_disagree(self, authenticated_api_client, sample_team_with_owner_member):
        """One value, two names. A client migrating must not see a behaviour change."""
        client, token = authenticated_api_client
        members = self._members(client, token, sample_team_with_owner_member.team)

        assert all(m["is_default_team"] == m["is_default_workspace"] for m in members)


class TestFrozenErrorCodes:
    """The prose beside these now says workspace; the codes must not follow.

    They are contract strings a client may branch on, so renaming one is a
    shape break that waits for a v2.
    """

    @pytest.mark.parametrize(
        ("code", "value"),
        [
            (ErrorCode.NO_CURRENT_TEAM, "NO_CURRENT_TEAM"),
            (ErrorCode.TEAM_NOT_FOUND, "TEAM_NOT_FOUND"),
            (ErrorCode.TEAM_MISMATCH, "TEAM_MISMATCH"),
        ],
    )
    def test_the_value_is_unchanged(self, code, value):
        assert code.value == value


@pytest.mark.django_db
class TestErrorProseSaysWorkspace:
    def test_the_no_current_workspace_error_says_workspace(self, authenticated_api_client):
        """A token with no workspace context hits the reworded 403.

        The prose changes; the error_code beside it does not.
        """
        client, token = authenticated_api_client

        response = client.post(
            "/api/v1/products",
            data=json.dumps({"name": "Lithium"}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 403
        body = json.loads(response.content)
        assert body["detail"] == "No current workspace selected"
        assert body["error_code"] == ErrorCode.NO_CURRENT_TEAM.value
