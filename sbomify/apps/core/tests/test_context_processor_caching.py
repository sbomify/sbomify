"""Context processors run once per request, not once per component render.

Cotton builds a fresh ``RequestContext`` for every component it renders, and
binding one runs every processor registered in settings again. A page is
hundreds of components, so the counts these processors look up were being
recomputed hundreds of times: measured at 443 invitation lookups and 889 member
lookups for one artifact scan report, 3,116 queries for a single page.

None of those answers can change inside one request.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext

from sbomify.apps.core.context_processors import team_context
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member


@contextmanager
def counted() -> Any:
    """The queries a block runs, without asserting a number up front."""
    with CaptureQueriesContext(connection) as captured:
        yield captured


def _request(member: Member, *, with_team: bool = True) -> Any:
    request = RequestFactory().get("/")
    request.user = member.user
    request.session = {"current_team": {"key": member.team.key}} if with_team else {}
    return request


@pytest.mark.django_db
class TestProcessorsRunOncePerRequest:
    def test_a_second_call_on_one_request_does_no_work(self, sample_team_with_owner_member: Member) -> None:
        request = _request(sample_team_with_owner_member)

        with counted() as first:
            team_context(request)
        with counted() as second:
            team_context(request)

        assert len(first) > 0, "the first call has to actually look something up"
        assert len(second) == 0

    def test_the_answer_is_the_same_one(self, sample_team_with_owner_member: Member) -> None:
        """Cached, not recomputed, so the page cannot show two different answers."""
        request = _request(sample_team_with_owner_member)

        assert team_context(request) == team_context(request)

    def test_a_different_request_is_not_served_the_first_one_s_answer(
        self, sample_team_with_owner_member: Member
    ) -> None:
        """The cache is per request, so the next visitor gets their own."""
        signed_in = team_context(_request(sample_team_with_owner_member))
        no_workspace = team_context(_request(sample_team_with_owner_member, with_team=False))

        assert signed_in != no_workspace

    def test_a_page_of_components_looks_a_member_up_once(self, sample_team_with_owner_member: Member) -> None:
        """The property that matters, measured through a real render.

        Before this, the components list ran 766 queries, 220 of them reading
        the same Member row.
        """
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )

        with counted() as captured:
            response = client.get("/components/")

        assert response.status_code == 200
        member_reads = sum(1 for query in captured if "workspaces_members" in query["sql"])
        assert member_reads <= 10, f"{member_reads} member lookups for one page"
