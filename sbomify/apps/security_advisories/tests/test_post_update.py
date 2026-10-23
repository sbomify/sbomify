"""The timeline composer's write path.

The invariant worth guarding: a status kind appends the status_change event
AND moves the denormalised remediation_status in the same transaction, so the
list column and the timeline can never disagree.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sbomify.apps.security_advisories.models import (
    AdvisoryProductStatus,
    AdvisoryVersionRange,
    SecurityAdvisory,
    validate_publishable,
)
from sbomify.apps.security_advisories.services.advisories import post_update

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(sample_team_with_owner_member):
    return sample_team_with_owner_member.user


@pytest.fixture
def triaged(vulnerability, advisory_product):
    """A product status as create_advisory leaves one: under investigation, no fix named."""
    return AdvisoryProductStatus.objects.create(vulnerability=vulnerability, advisory_product=advisory_product)


class TestResolvingMovesTheProducts:
    """Resolving the advisory has to reach the per-product statuses.

    The trust center's "Am I affected?" table reads those rows, not the
    advisory, so a resolved advisory whose rows stayed in triage told readers
    every product was still under investigation.
    """

    def test_a_fixed_version_marks_each_open_product_fixed(self, team, user, advisory, triaged):
        result = post_update(team, user, advisory.id, kind="resolved", fixed_version=" 1.4.3 ")

        assert result.ok
        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.RESOLVED
        assert triaged.recommended_version == "1.4.3"
        assert triaged.response == AdvisoryProductStatus.Response.UPDATE
        event = advisory.events.get()
        assert event.payload == {
            "from": "identified",
            "to": "resolved",
            "fixed_version": "1.4.3",
            "resolved_statuses": 1,
        }
        assert validate_publishable(advisory) == []

    def test_affected_products_are_fixed_too(self, team, user, advisory, make_publishable):
        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        status = AdvisoryProductStatus.objects.get(vulnerability__advisory=advisory)
        assert status.status == AdvisoryProductStatus.Status.RESOLVED

    def test_a_product_naming_its_own_fix_keeps_it(self, team, user, advisory, triaged):
        triaged.recommended_version = "2.0.1"
        triaged.save()

        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.RESOLVED
        assert triaged.recommended_version == "2.0.1"

    def test_a_fixed_range_is_a_fix_without_a_version(self, team, user, advisory, triaged):
        AdvisoryVersionRange.objects.create(product_status=triaged, introduced="1.0", fixed="1.4.3")

        assert post_update(team, user, advisory.id, kind="resolved").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.RESOLVED
        assert triaged.recommended_version == ""

    def test_a_product_with_no_fix_to_name_is_left_alone(self, team, user, advisory, triaged):
        """A fixed row with no fixed version would make the advisory unpublishable."""
        result = post_update(team, user, advisory.id, kind="resolved")

        assert result.ok
        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.IN_TRIAGE
        assert advisory.events.get().payload == {"from": "identified", "to": "resolved"}

    def test_not_affected_products_are_not_touched(self, team, user, advisory, triaged):
        triaged.status = AdvisoryProductStatus.Status.NOT_AFFECTED
        triaged.impact_statement = "The parser is not shipped."
        triaged.save()

        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.NOT_AFFECTED
        assert triaged.recommended_version == ""

    def test_an_already_resolved_advisory_can_bring_its_products_into_line(self, team, user, advisory, triaged):
        advisory.remediation_status = SecurityAdvisory.RemediationStatus.RESOLVED
        advisory.save()

        result = post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3")

        assert result.ok
        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.RESOLVED
        event = advisory.events.get()
        assert event.event_type == "update"
        assert event.body == "Fixed in 1.4.3."
        assert event.payload == {"fixed_version": "1.4.3", "resolved_statuses": 1}

    def test_resolving_again_without_a_version_is_still_refused(self, team, user, advisory, triaged):
        advisory.remediation_status = SecurityAdvisory.RemediationStatus.RESOLVED
        advisory.save()

        result = post_update(team, user, advisory.id, kind="resolved")

        assert not result.ok
        assert "already" in (result.error or "")

    def test_a_fixed_version_needs_the_resolved_kind(self, team, user, advisory, triaged):
        result = post_update(team, user, advisory.id, kind="investigating", fixed_version="1.4.3")

        assert not result.ok
        assert result.status_code == 400
        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.IN_TRIAGE
        assert advisory.events.count() == 0

    def test_a_fixed_version_longer_than_the_column_is_refused(self, team, user, advisory, triaged):
        result = post_update(team, user, advisory.id, kind="resolved", fixed_version="1" * 101)

        assert not result.ok
        assert result.status_code == 400
        assert advisory.events.count() == 0


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


class TestTimelineMarkdown:
    def test_notes_render_as_markdown_and_the_composer_says_so(self, sample_team_with_owner_member, advisory, client):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)
        assert post_update(member.team, member.user, advisory.id, kind="update", note="Fix is **merged**.").ok

        response = client.get(reverse("core:security_advisory_detail", args=[advisory.id]))

        content = response.content.decode()
        assert response.status_code == 200
        assert "Fix is <strong>merged</strong>." in content
        assert 'id="composerNoteHint"' in content
        assert "Supports Markdown" in content
