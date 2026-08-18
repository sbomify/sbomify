"""The timeline composer's write path.

The invariant worth guarding: a status kind appends the status_change event
AND moves the denormalised remediation_status in the same transaction, so the
list column and the timeline can never disagree.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import post_update

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(sample_team_with_owner_member):
    return sample_team_with_owner_member.user


class TestPostUpdate:
    def test_note_appends_an_update_event_and_moves_nothing(self, team, user, advisory):
        result = post_update(team, user, advisory.id, kind="update", note="Reproduced on 5.1.x.")

        assert result.ok
        event = advisory.events.get()
        assert event.event_type == "update"
        assert event.body == "Reproduced on 5.1.x."
        assert event.actor == user
        advisory.refresh_from_db()
        assert advisory.remediation_status == "identified"

    def test_status_kind_appends_event_and_moves_the_advisory(self, team, user, advisory):
        result = post_update(team, user, advisory.id, kind="investigating", note="Scoping the parser.")

        assert result.ok
        event = advisory.events.get()
        assert event.event_type == "status_change"
        assert event.payload == {"from": "identified", "to": "investigating"}
        assert event.body == "Scoping the parser."
        advisory.refresh_from_db()
        assert advisory.remediation_status == "investigating"

    def test_status_note_is_optional(self, team, user, advisory):
        assert post_update(team, user, advisory.id, kind="resolved", note="").ok

    def test_note_without_body_is_rejected(self, team, user, advisory):
        result = post_update(team, user, advisory.id, kind="update", note="   ")

        assert not result.ok
        assert advisory.events.count() == 0

    def test_same_status_is_rejected(self, team, user, advisory):
        result = post_update(team, user, advisory.id, kind="identified", note="")

        assert not result.ok
        assert "already" in (result.error or "")
        assert advisory.events.count() == 0

    def test_unknown_kind_is_rejected(self, team, user, advisory):
        assert not post_update(team, user, advisory.id, kind="escalate_to_legal", note="x").ok

    def test_another_workspaces_advisory_reads_as_absent(self, other_team, user, advisory):
        result = post_update(other_team, user, advisory.id, kind="update", note="hi")

        assert not result.ok
        assert result.status_code == 404

    def test_lookup_by_tracking_id(self, team, user, advisory):
        advisory.tracking_id = "ACME-SA-2026-0001"
        advisory.status = SecurityAdvisory.Status.PUBLISHED
        from django.utils import timezone

        advisory.published_at = timezone.now()
        advisory.save()

        assert post_update(team, user, "ACME-SA-2026-0001", kind="investigating", note="").ok


class TestComposerPost:
    def test_post_moves_status_and_redirects(self, sample_team_with_owner_member, advisory, client):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        response = client.post(
            reverse("core:security_advisory_detail", args=[advisory.id]),
            {"kind": "fix_in_progress", "note": "Patch in review."},
        )

        assert response.status_code == 302
        advisory.refresh_from_db()
        assert advisory.remediation_status == "fix_in_progress"
        assert advisory.events.get().payload["to"] == "fix_in_progress"
