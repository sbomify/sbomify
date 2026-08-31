"""The delete intent on the advisory detail view.

The invariant worth guarding: deletion is gated to the same write roles as
every other advisory intent, and a forbidden POST leaves the advisory
standing rather than erroring after the fact.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


class TestDeletePost:
    def test_owner_deletes_and_lands_on_the_dashboard(self, sample_team_with_owner_member, advisory, client):
        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(
            reverse("core:security_advisory_detail", args=[advisory.id]),
            {"intent": "delete"},
        )

        assert response.status_code == 302
        assert response.url == reverse("core:security_advisories_dashboard")
        assert not SecurityAdvisory.objects.filter(id=advisory.id).exists()

    def test_member_may_not_delete(self, sample_team_with_owner_member, advisory, guest_user, client):
        team = sample_team_with_owner_member.team
        Member.objects.create(team=team, user=guest_user, role="member")
        setup_authenticated_client_session(client, team, guest_user)

        response = client.post(
            reverse("core:security_advisory_detail", args=[advisory.id]),
            {"intent": "delete"},
        )

        assert response.status_code == 404
        assert SecurityAdvisory.objects.filter(id=advisory.id).exists()
