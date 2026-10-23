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

from .conftest import publish

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
            "moved_statuses": [{"id": triaged.pk, "status": "in_triage", "response": "", "recommended_version": ""}],
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

    def test_a_fixed_range_is_the_products_own_fix(self, team, user, advisory, triaged):
        AdvisoryVersionRange.objects.create(product_status=triaged, introduced="1.0", fixed="1.4.3")

        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="2.0.0").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.RESOLVED
        assert triaged.recommended_version == ""

    def test_a_contradicting_response_becomes_update(self, team, user, advisory, triaged):
        triaged.response = AdvisoryProductStatus.Response.WILL_NOT_FIX
        triaged.save()

        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        triaged.refresh_from_db()
        assert triaged.response == AdvisoryProductStatus.Response.UPDATE

    def test_a_rollback_response_is_kept(self, team, user, advisory, triaged):
        triaged.response = AdvisoryProductStatus.Response.ROLLBACK
        triaged.save()

        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.3.9").ok

        triaged.refresh_from_db()
        assert triaged.response == AdvisoryProductStatus.Response.ROLLBACK

    def test_resolving_is_refused_while_a_product_names_no_fix(self, team, user, advisory, triaged):
        """A fixed row with no fixed version would make the advisory unpublishable."""
        result = post_update(team, user, advisory.id, kind="resolved")

        assert not result.ok
        assert result.status_code == 400
        assert "fixed version" in (result.error or "")
        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.IN_TRIAGE
        advisory.refresh_from_db()
        assert advisory.remediation_status == "identified"
        assert advisory.events.count() == 0

    def test_not_affected_products_are_not_touched(self, team, user, advisory, triaged):
        triaged.status = AdvisoryProductStatus.Status.NOT_AFFECTED
        triaged.impact_statement = "The parser is not shipped."
        triaged.save()

        assert post_update(team, user, advisory.id, kind="resolved").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.NOT_AFFECTED
        assert triaged.recommended_version == ""

    def test_reopening_puts_the_products_back(self, team, user, advisory, triaged):
        triaged.response = AdvisoryProductStatus.Response.WILL_NOT_FIX
        triaged.save()
        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        assert post_update(team, user, advisory.id, kind="investigating", note="The fix is incomplete.").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.IN_TRIAGE
        assert triaged.response == AdvisoryProductStatus.Response.WILL_NOT_FIX
        assert triaged.recommended_version == ""
        reopened = advisory.events.order_by("-created_at").first()
        assert reopened.payload == {"from": "resolved", "to": "investigating", "reverted_statuses": 1}

    def test_reopening_leaves_a_product_fixed_some_other_way(self, team, user, advisory, triaged):
        advisory.remediation_status = SecurityAdvisory.RemediationStatus.RESOLVED
        advisory.save()
        triaged.status = AdvisoryProductStatus.Status.RESOLVED
        triaged.recommended_version = "1.4.3"
        triaged.save()

        assert post_update(team, user, advisory.id, kind="investigating").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.RESOLVED

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
        assert event.payload["fixed_version"] == "1.4.3"
        assert [row["id"] for row in event.payload["moved_statuses"]] == [triaged.pk]

    def test_a_repaired_advisory_reopens_cleanly(self, team, user, advisory, triaged):
        """The repair records its moves, so a later reopen can find them."""
        post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3")
        AdvisoryProductStatus.objects.filter(pk=triaged.pk).update(status="in_triage", recommended_version="")
        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.4").ok

        assert post_update(team, user, advisory.id, kind="fix_in_progress").ok

        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.IN_TRIAGE
        assert triaged.recommended_version == ""

    def test_a_repair_that_moves_nothing_is_refused(self, team, user, advisory, triaged):
        assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        again = post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3")

        assert not again.ok
        assert again.status_code == 400
        assert advisory.events.count() == 1

    def test_resolving_again_without_a_version_is_still_refused(self, team, user, advisory, triaged):
        advisory.remediation_status = SecurityAdvisory.RemediationStatus.RESOLVED
        advisory.save()

        result = post_update(team, user, advisory.id, kind="resolved")

        assert not result.ok
        assert "already" in (result.error or "")

    def test_a_withdrawn_advisorys_products_are_not_touched(self, team, user, advisory, triaged):
        from django.utils import timezone

        publish(advisory)
        advisory.status = SecurityAdvisory.Status.WITHDRAWN
        advisory.withdrawn_at = timezone.now()
        advisory.withdrawal_reason = "Published against the wrong product."
        advisory.save()

        with_version = post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3")
        without = post_update(team, user, advisory.id, kind="resolved")

        assert with_version.status_code == 409
        assert without.ok
        triaged.refresh_from_db()
        assert triaged.status == AdvisoryProductStatus.Status.IN_TRIAGE

    def test_one_resolve_moves_the_csaf_revision_once_per_write(
        self, team, user, advisory, advisory_product, vulnerability, django_capture_on_commit_callbacks
    ):
        """Thirty rows used to schedule thirty revision bumps for one change."""
        from sbomify.apps.security_advisories.models import AdvisoryVulnerability

        for index in range(5):
            extra = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id=f"CVE-2026-{1000 + index}")
            AdvisoryProductStatus.objects.create(vulnerability=extra, advisory_product=advisory_product)
        publish(advisory, visibility=SecurityAdvisory.Visibility.PUBLIC)
        advisory.refresh_from_db()
        before = advisory.csaf_revision

        with django_capture_on_commit_callbacks(execute=True):
            assert post_update(team, user, advisory.id, kind="resolved", fixed_version="1.4.3").ok

        advisory.refresh_from_db()
        assert AdvisoryProductStatus.objects.filter(vulnerability__advisory=advisory, status="resolved").count() == 5
        assert 1 <= advisory.csaf_revision - before <= 2

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

    def test_the_composer_resolves_with_a_fixed_version(self, sample_team_with_owner_member, advisory, triaged, client):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)
        url = reverse("core:security_advisory_detail", args=[advisory.id])

        page = client.get(url)
        response = client.post(url, {"kind": "resolved", "note": "Shipped.", "fixed_version": "1.4.3"})

        assert 'name="fixed_version"' in page.content.decode()
        assert response.status_code == 302
        triaged.refresh_from_db()
        assert (triaged.status, triaged.recommended_version) == ("resolved", "1.4.3")

    def test_the_composer_ignores_a_fixed_version_on_other_kinds(
        self, sample_team_with_owner_member, advisory, client
    ):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        member = sample_team_with_owner_member
        setup_authenticated_client_session(client, member.team, member.user)

        client.post(
            reverse("core:security_advisory_detail", args=[advisory.id]),
            {"kind": "investigating", "note": "Looking.", "fixed_version": "1.4.3"},
        )

        advisory.refresh_from_db()
        assert advisory.remediation_status == "investigating"


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
