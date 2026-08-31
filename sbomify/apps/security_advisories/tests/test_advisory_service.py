"""The projection the advisory UI renders.

Most of these guard the two-axis distinction: ``status`` is where the fix is and
``publication_status`` is who can read it, and collapsing them would make either
question unanswerable.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryReference,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.advisories import (
    advisory_counts,
    delete_advisory,
    get_advisory,
    list_advisories,
    publish_advisory,
    update_advisory,
)

pytestmark = pytest.mark.django_db


def _advisory(team, **kwargs):
    defaults = {
        "team": team,
        "title": "Improper authentication",
        "description": "A flaw in signature validation.",
        "severity": "critical",
    }
    return SecurityAdvisory.objects.create(**{**defaults, **kwargs})


class TestTheTwoStatusAxes:
    def test_status_is_remediation_not_publication(self, sample_team):
        """The Status column means where the fix is. A resolved advisory that
        nobody has published yet must not read as a draft in that column."""
        _advisory(sample_team, remediation_status="resolved", status="draft")

        row = list_advisories(sample_team).value[0]

        assert row["status"] == "resolved"
        assert row["status_label"] == "Resolved"
        assert row["publication_status"] == "draft"

    def test_a_published_advisory_can_still_be_mid_fix(self, sample_team):
        _advisory(
            sample_team,
            remediation_status="fix_in_progress",
            status="published",
            tracking_id="OSPN-2026-0001",
            published_at=timezone.now(),
        )

        row = list_advisories(sample_team).value[0]

        assert row["status"] == "fix_in_progress"
        assert row["publication_status"] == "published"
        assert row["is_open"] is True

    @pytest.mark.parametrize("closed", ["resolved", "wont_fix"])
    def test_resolved_and_wont_fix_are_both_closed(self, sample_team, closed):
        _advisory(sample_team, remediation_status=closed)

        assert list_advisories(sample_team).value[0]["is_open"] is False


class TestDisplayId:
    def test_the_tracking_id_is_shown_when_set(self, sample_team):
        _advisory(sample_team, status="published", tracking_id="OSPN-2026-0034", published_at=timezone.now())

        assert list_advisories(sample_team).value[0]["id"] == "OSPN-2026-0034"

    def test_a_draft_falls_back_to_its_primary_key(self, sample_team):
        """The model assigns a tracking id at publication, so a draft has none
        and the list still needs something to show and link."""
        advisory = _advisory(sample_team)

        row = list_advisories(sample_team).value[0]

        assert row["id"] == advisory.id
        assert get_advisory(sample_team, advisory.id).ok


class TestSeverity:
    def test_it_falls_back_to_the_worst_vulnerability(self, sample_team):
        """An advisory carrying three CVEs but no severity of its own should not
        read as less severe than the worst thing in it."""
        advisory = _advisory(sample_team, severity="")
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0001", severity="low")
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0002", severity="high")

        assert list_advisories(sample_team).value[0]["severity"] == "high"

    def test_its_own_severity_wins(self, sample_team):
        advisory = _advisory(sample_team, severity="medium")
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0002", severity="critical")

        assert list_advisories(sample_team).value[0]["severity"] == "medium"


class TestType:
    def test_a_cve_reads_as_cve(self, sample_team):
        advisory = _advisory(sample_team)
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-4471", severity="high")

        assert list_advisories(sample_team).value[0]["type"] == "cve"

    def test_a_ghsa_comes_from_the_references(self, sample_team):
        """cve_id is validated as a real CVE id, so a GHSA can only ever arrive
        as a reference. Reading the type off cve_id would never fire."""
        advisory = _advisory(sample_team)
        AdvisoryReference.objects.create(advisory=advisory, reference_type="ghsa", external_id="GHSA-hxxf-q3w9-4xgw")

        row = list_advisories(sample_team).value[0]

        assert row["type"] == "ghsa"
        assert row["type_label"] == "GHSA"

    def test_no_external_identifier_reads_as_internal(self, sample_team):
        """An advisory carrying no CVE and no reference is the workspace's own
        finding. "Other" read like the field had failed to populate."""
        _advisory(sample_team)

        assert list_advisories(sample_team).value[0]["type"] == "internal"

    def test_an_unrecognised_database_still_reads_as_other(self, sample_team):
        advisory = _advisory(sample_team)
        AdvisoryReference.objects.create(advisory=advisory, external_id="VENDOR-2026-1")

        assert list_advisories(sample_team).value[0]["type"] == "other"


class TestTimeline:
    def test_it_is_newest_first(self, sample_team):
        advisory = _advisory(sample_team)
        for body in ("first", "second", "third"):
            AdvisoryEvent.objects.create(advisory=advisory, event_type="update", body=body)

        timeline = get_advisory(sample_team, advisory.id).value["timeline"]

        assert [e["note"] for e in timeline] == ["third", "second", "first"]

    def test_only_status_changes_are_marked_as_setting_status(self, sample_team):
        advisory = _advisory(sample_team)
        AdvisoryEvent.objects.create(advisory=advisory, event_type="status_change", payload={"to": "investigating"})
        AdvisoryEvent.objects.create(advisory=advisory, event_type="update", body="A note")

        timeline = get_advisory(sample_team, advisory.id).value["timeline"]

        assert {e["kind"]: e["sets_status"] for e in timeline} == {"status_change": True, "update": False}

    def test_updated_at_follows_the_newest_event_of_any_kind(self, sample_team):
        """A note-only entry still means someone touched it."""
        advisory = _advisory(sample_team)
        AdvisoryEvent.objects.create(advisory=advisory, event_type="update", body="A note")

        row = list_advisories(sample_team).value[0]

        assert row["updates_count"] == 1
        assert row["updated_at"] >= advisory.created_at


class TestProducts:
    def test_a_linked_product_carries_its_id_so_the_chip_links(self, sample_team, sample_product):
        advisory = _advisory(sample_team)
        AdvisoryProduct.objects.create(advisory=advisory, product=sample_product, product_name=sample_product.name)

        product = list_advisories(sample_team).value[0]["products"][0]

        assert product["id"] == sample_product.id
        assert product["name"] == sample_product.name

    def test_an_unlinked_product_keeps_its_name_without_an_id(self, sample_team):
        """An advisory can name a product this workspace does not track, and
        keeps naming it after one is deleted. The template renders plain text
        rather than a dead link."""
        advisory = _advisory(sample_team)
        AdvisoryProduct.objects.create(advisory=advisory, product=None, product_name="Third-party Appliance")

        product = list_advisories(sample_team).value[0]["products"][0]

        assert product["id"] is None
        assert product["name"] == "Third-party Appliance"


class TestScoping:
    def test_the_list_shows_only_this_workspaces_advisories(self, sample_team, guest_user):
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        other = Team.objects.create(name="Other Workspace")
        other.key = number_to_random_token(other.pk)
        other.save(update_fields=["key"])
        _advisory(sample_team, title="Ours")
        _advisory(other, title="Theirs")

        assert [a["title"] for a in list_advisories(sample_team).value] == ["Ours"]

    def test_another_workspaces_advisory_reads_as_absent(self, sample_team):
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        other = Team.objects.create(name="Other Workspace")
        other.key = number_to_random_token(other.pk)
        other.save(update_fields=["key"])
        theirs = _advisory(other, title="Theirs")

        result = get_advisory(sample_team, theirs.id)

        assert not result.ok
        assert result.status_code == 404


class TestSearchAndCounts:
    def test_search_matches_the_cve(self, sample_team):
        advisory = _advisory(sample_team, title="Something else")
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-4471", severity="high")
        _advisory(sample_team, title="Unrelated")

        assert [a["title"] for a in list_advisories(sample_team, "4471").value] == ["Something else"]

    def test_counts_split_the_two_axes(self, sample_team):
        _advisory(sample_team, remediation_status="investigating", status="draft")
        _advisory(sample_team, remediation_status="resolved", status="draft")
        _advisory(
            sample_team,
            remediation_status="resolved",
            status="published",
            tracking_id="OSPN-2026-0002",
            published_at=timezone.now(),
        )

        counts = advisory_counts(list_advisories(sample_team).value)

        assert counts == {"total": 3, "open": 1, "resolved": 2, "published": 1}


class TestLookup:
    def test_it_resolves_by_tracking_id_as_well_as_pk(self, sample_team):
        """The tracking id is what the list links and what a person pastes."""
        advisory = _advisory(sample_team, status="published", tracking_id="OSPN-2026-0099", published_at=timezone.now())

        assert get_advisory(sample_team, "OSPN-2026-0099").value["id"] == "OSPN-2026-0099"
        assert get_advisory(sample_team, advisory.id).ok

    def test_it_takes_one_query_either_way(self, sample_team, django_assert_num_queries):
        """Two sequential lookups would rebuild the prefetches and re-run them
        for anything found by tracking id."""
        advisory = _advisory(sample_team, status="published", tracking_id="OSPN-2026-0100", published_at=timezone.now())
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0100", severity="high")

        # One for the advisory, then one per prefetched relation.
        with django_assert_num_queries(5):
            get_advisory(sample_team, "OSPN-2026-0100")


def test_the_display_id_is_always_a_string(sample_team):
    """The table's client-side search lowercases it, so a non-string would
    throw at runtime rather than just sorting oddly."""
    _advisory(sample_team)

    row = list_advisories(sample_team).value[0]

    assert isinstance(row["id"], str)
    assert isinstance(row["pk"], str)


class TestUpdateAdvisory:
    def test_each_changed_field_gets_its_own_timeline_entry(self, sample_team, sample_user):
        """One event per field, so the history answers who changed the severity
        rather than only recording status moves."""
        advisory = _advisory(sample_team, title="Old title", severity="low", description="Old body.")

        result = update_advisory(
            sample_team,
            sample_user,
            advisory.id,
            title="New title",
            severity="high",
            description="New body.",
        )

        assert result.ok, result.error
        advisory.refresh_from_db()
        assert (advisory.title, advisory.severity, advisory.description) == ("New title", "high", "New body.")
        events = AdvisoryEvent.objects.filter(advisory=advisory, event_type=AdvisoryEvent.EventType.FIELD_CHANGE)
        assert {event.payload["field"] for event in events} == {"title", "severity", "description"}

    def test_a_field_change_entry_says_what_changed(self, sample_team, sample_user):
        """The timeline renders an event's body. A payload-only event showed a
        "Field change" badge with no text under it."""
        advisory = _advisory(sample_team, severity="low")

        update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, severity="high")

        event = AdvisoryEvent.objects.get(
            advisory=advisory, event_type=AdvisoryEvent.EventType.FIELD_CHANGE, payload__field="severity"
        )
        assert event.body == "Severity changed from “low” to “high”."

    def test_an_unchanged_field_records_nothing(self, sample_team, sample_user):
        advisory = _advisory(sample_team, title="Same", severity="high", description="Same body.")

        result = update_advisory(
            sample_team, sample_user, advisory.id, title="Same", severity="high", description="Same body."
        )

        assert result.ok
        assert not AdvisoryEvent.objects.filter(advisory=advisory).exists()

    def test_an_omitted_severity_is_left_alone(self, sample_team, sample_user):
        """A <select> always posts something, so "not submitted" has to be
        distinguishable from "submitted blank" or editing a title would set a
        severity nobody chose."""
        advisory = _advisory(sample_team, severity="")

        update_advisory(sample_team, sample_user, advisory.id, title="Retitled")

        advisory.refresh_from_db()
        assert advisory.severity == ""

    def test_a_blank_severity_clears_it(self, sample_team, sample_user):
        advisory = _advisory(sample_team, severity="high")

        update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, severity="")

        advisory.refresh_from_db()
        assert advisory.severity == ""

    def test_surrounding_whitespace_on_severity_is_tolerated(self, sample_team, sample_user):
        advisory = _advisory(sample_team, severity="low")

        result = update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, severity=" high ")

        assert result.ok, result.error
        advisory.refresh_from_db()
        assert advisory.severity == "high"

    def test_an_empty_title_is_refused(self, sample_team, sample_user):
        advisory = _advisory(sample_team, title="Keeps its title")

        result = update_advisory(sample_team, sample_user, advisory.id, title="   ")

        assert not result.ok
        assert result.status_code == 400
        advisory.refresh_from_db()
        assert advisory.title == "Keeps its title"

    def test_an_unknown_severity_is_refused(self, sample_team, sample_user):
        advisory = _advisory(sample_team, severity="low")

        result = update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, severity="spicy")

        assert not result.ok
        assert result.status_code == 400
        advisory.refresh_from_db()
        assert advisory.severity == "low"

    def test_another_workspaces_advisory_is_not_found(self, sample_team, guest_user, sample_user):
        from sbomify.apps.teams.models import Team

        other = Team.objects.create(name="Someone else")
        advisory = _advisory(other, title="Not yours")

        result = update_advisory(sample_team, sample_user, advisory.id, title="Mine now")

        assert not result.ok
        assert result.status_code == 404
        advisory.refresh_from_db()
        assert advisory.title == "Not yours"


VECTOR = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"


class TestUpdateAdvisoryCvss:
    """CVSS lives on the vulnerability, so the edit path crosses one model over."""

    def test_setting_cvss_writes_the_entry_and_the_timeline(self, sample_team, sample_user):
        advisory = _advisory(sample_team)
        vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0001")

        result = update_advisory(
            sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="9.8", cvss_vector=VECTOR
        )

        assert result.ok, result.error
        vulnerability.refresh_from_db()
        assert vulnerability.cvss_scores == [{"version": "3.1", "vector": VECTOR, "base_score": 9.8}]
        event = AdvisoryEvent.objects.get(advisory=advisory, payload__field="cvss")
        assert event.payload == {"field": "cvss", "old": "", "new": f"9.8 ({VECTOR})"}
        assert event.body == f"CVSS set to “9.8 ({VECTOR})”."

    def test_a_bare_score_stores_no_version(self, sample_team, sample_user):
        advisory = _advisory(sample_team)
        vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0001")

        update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="7.5")

        vulnerability.refresh_from_db()
        assert vulnerability.cvss_scores == [{"version": "", "vector": "", "base_score": 7.5}]

    def test_a_blank_score_clears_it(self, sample_team, sample_user):
        advisory = _advisory(sample_team)
        vulnerability = AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id="CVE-2026-0001", cvss_scores=[{"version": "", "vector": "", "base_score": 9.8}]
        )

        update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="")

        vulnerability.refresh_from_db()
        assert vulnerability.cvss_scores == []
        assert AdvisoryEvent.objects.get(advisory=advisory, payload__field="cvss").body == "CVSS cleared."

    def test_an_omitted_cvss_is_left_alone(self, sample_team, sample_user):
        advisory = _advisory(sample_team)
        vulnerability = AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id="CVE-2026-0001", cvss_scores=[{"version": "", "vector": "", "base_score": 9.8}]
        )

        update_advisory(sample_team, sample_user, advisory.id, title="Retitled")

        vulnerability.refresh_from_db()
        assert vulnerability.cvss_scores == [{"version": "", "vector": "", "base_score": 9.8}]

    def test_an_unchanged_cvss_records_nothing_and_keeps_other_entries(self, sample_team, sample_user):
        """Prefill shows the worst entry, so resubmitting it untouched must not
        clobber a hand-entered list down to one row."""
        advisory = _advisory(sample_team)
        entries = [
            {"version": "2.0", "vector": "", "base_score": 6.0},
            {"version": "3.1", "vector": VECTOR, "base_score": 9.8},
        ]
        vulnerability = AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id="CVE-2026-0001", cvss_scores=entries
        )

        result = update_advisory(
            sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="9.8", cvss_vector=VECTOR
        )

        assert result.ok
        vulnerability.refresh_from_db()
        assert vulnerability.cvss_scores == entries
        assert not AdvisoryEvent.objects.filter(advisory=advisory, payload__field="cvss").exists()

    def test_the_write_goes_to_the_vulnerability_holding_the_displayed_entry(self, sample_team, sample_user):
        advisory = _advisory(sample_team)
        mild = AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id="CVE-2026-0001", cvss_scores=[{"version": "", "vector": "", "base_score": 3.0}]
        )
        worst = AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id="CVE-2026-0002", cvss_scores=[{"version": "", "vector": "", "base_score": 9.0}]
        )

        update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="9.5")

        mild.refresh_from_db()
        worst.refresh_from_db()
        assert mild.cvss_scores == [{"version": "", "vector": "", "base_score": 3.0}]
        assert worst.cvss_scores == [{"version": "", "vector": "", "base_score": 9.5}]

    def test_an_advisory_with_no_vulnerability_grows_one(self, sample_team, sample_user):
        advisory = _advisory(sample_team, title="Shell-made")

        result = update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="5")

        assert result.ok, result.error
        vulnerability = advisory.vulnerabilities.get()
        assert vulnerability.title == "Shell-made"
        assert vulnerability.cvss_scores == [{"version": "", "vector": "", "base_score": 5.0}]

    def test_a_non_numeric_score_is_refused(self, sample_team, sample_user):
        advisory = _advisory(sample_team)

        result = update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="spicy")

        assert not result.ok
        assert result.status_code == 400
        assert result.error == "CVSS score must be a number from 0 to 10."

    def test_an_out_of_range_score_is_refused(self, sample_team, sample_user):
        advisory = _advisory(sample_team)

        result = update_advisory(sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="10.1")

        assert not result.ok
        assert result.status_code == 400

    def test_a_vector_without_a_score_is_refused(self, sample_team, sample_user):
        advisory = _advisory(sample_team)

        result = update_advisory(
            sample_team, sample_user, advisory.id, title=advisory.title, cvss_score="", cvss_vector=VECTOR
        )

        assert not result.ok
        assert result.status_code == 400
        assert result.error == "Enter the CVSS score for the vector."


class TestCvssProjection:
    def test_the_projection_carries_the_worst_entry_and_its_vector(self, sample_team):
        advisory = _advisory(sample_team)
        AdvisoryVulnerability.objects.create(
            advisory=advisory, cve_id="CVE-2026-0001", cvss_scores=[{"version": "", "vector": "", "base_score": 5.0}]
        )
        AdvisoryVulnerability.objects.create(
            advisory=advisory,
            cve_id="CVE-2026-0002",
            cvss_scores=[{"version": "3.1", "vector": VECTOR, "base_score": 9.8}],
        )

        projection = get_advisory(sample_team, advisory.id).value

        assert projection["cvss_score"] == 9.8
        assert projection["cvss_vector"] == VECTOR

    def test_an_unscored_advisory_projects_none(self, sample_team):
        advisory = _advisory(sample_team)
        AdvisoryVulnerability.objects.create(advisory=advisory, cve_id="CVE-2026-0001")

        projection = get_advisory(sample_team, advisory.id).value

        assert projection["cvss_score"] is None
        assert projection["cvss_vector"] == ""

    def test_a_malformed_entry_is_skipped(self, sample_team):
        advisory = _advisory(sample_team)
        AdvisoryVulnerability.objects.create(
            advisory=advisory,
            cve_id="CVE-2026-0001",
            cvss_scores=["garbage", {"vector": "no score"}, {"version": "", "vector": "", "base_score": "4.2"}],
        )

        projection = get_advisory(sample_team, advisory.id).value

        assert projection["cvss_score"] == 4.2


class TestPublishAdvisory:
    """Publishing is what puts an advisory on the Trust Center: until it runs the
    advisory is a draft with private visibility, and that page filters out both."""

    def _publishable(self, team, name="Gateway"):
        from sbomify.apps.core.models import Product

        advisory = _advisory(team)
        product, _ = Product.objects.get_or_create(team=team, name=name)
        AdvisoryProduct.objects.create(advisory=advisory, product=product)
        return advisory

    def test_publishing_public_makes_it_externally_visible(self, sample_team, sample_user):
        advisory = self._publishable(sample_team)

        result = publish_advisory(sample_team, sample_user, advisory.id, visibility="public")

        assert result.ok, result.error
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.PUBLISHED
        assert advisory.visibility == SecurityAdvisory.Visibility.PUBLIC
        assert advisory.is_externally_visible

    def test_publishing_records_the_disclosure(self, sample_team, sample_user):
        """published_at is when it left the workspace; made_public_at is when it
        became public, which a gated disclosure is not."""
        advisory = self._publishable(sample_team)

        publish_advisory(sample_team, sample_user, advisory.id, visibility="public")

        advisory.refresh_from_db()
        assert advisory.published_at is not None
        assert advisory.made_public_at is not None

    def test_a_gated_disclosure_is_not_public_disclosure(self, sample_team, sample_user):
        advisory = self._publishable(sample_team)

        publish_advisory(sample_team, sample_user, advisory.id, visibility="gated")

        advisory.refresh_from_db()
        assert advisory.visibility == SecurityAdvisory.Visibility.GATED
        assert advisory.published_at is not None
        assert advisory.made_public_at is None

    def test_a_tracking_id_is_allocated_and_sequential(self, sample_team, sample_user):
        first = self._publishable(sample_team)
        second = self._publishable(sample_team)

        publish_advisory(sample_team, sample_user, first.id, visibility="public")
        publish_advisory(sample_team, sample_user, second.id, visibility="public")

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.tracking_id.endswith("-0001")
        assert second.tracking_id.endswith("-0002")
        assert first.tracking_id[:-4] == second.tracking_id[:-4]

    def test_publishing_lands_on_the_timeline(self, sample_team, sample_user):
        advisory = self._publishable(sample_team)

        publish_advisory(sample_team, sample_user, advisory.id, visibility="public")

        advisory.refresh_from_db()
        event = AdvisoryEvent.objects.get(advisory=advisory, event_type=AdvisoryEvent.EventType.PUBLISHED)
        assert advisory.tracking_id in event.body
        assert event.payload["visibility"] == "public"

    def test_publishing_private_is_refused(self, sample_team, sample_user):
        """It would move the status and disclose nothing — the Trust Center
        excludes private advisories in SQL."""
        advisory = self._publishable(sample_team)

        result = publish_advisory(sample_team, sample_user, advisory.id, visibility="private")

        assert not result.ok
        assert result.status_code == 400
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.DRAFT

    def test_a_product_advisory_with_no_products_is_refused(self, sample_team, sample_user):
        advisory = _advisory(sample_team)

        result = publish_advisory(sample_team, sample_user, advisory.id, visibility="public")

        assert not result.ok
        assert result.status_code == 400
        assert "at least one product" in result.error
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.DRAFT
        assert advisory.tracking_id == ""

    def test_publishing_twice_is_refused(self, sample_team, sample_user):
        advisory = self._publishable(sample_team)
        publish_advisory(sample_team, sample_user, advisory.id, visibility="public")
        advisory.refresh_from_db()
        first_id = advisory.tracking_id

        result = publish_advisory(sample_team, sample_user, advisory.id, visibility="public")

        assert not result.ok
        assert result.status_code == 409
        advisory.refresh_from_db()
        assert advisory.tracking_id == first_id

    def test_another_workspaces_advisory_is_not_found(self, sample_team, sample_user):
        from sbomify.apps.teams.models import Team

        other = Team.objects.create(name="Someone else")
        advisory = _advisory(other)

        result = publish_advisory(sample_team, sample_user, advisory.id, visibility="public")

        assert not result.ok
        assert result.status_code == 404
        advisory.refresh_from_db()
        assert advisory.status == SecurityAdvisory.Status.DRAFT


class TestDelete:
    def test_the_whole_graph_goes_with_it(self, sample_team):
        advisory = _advisory(sample_team)
        vulnerability = AdvisoryVulnerability.objects.create(advisory=advisory, title="Auth bypass")
        AdvisoryProduct.objects.create(advisory=advisory, product_name="Ghost product")
        AdvisoryEvent.objects.create(advisory=advisory, event_type="update", body="First update")

        result = delete_advisory(sample_team, advisory.id)

        assert result.ok
        assert not SecurityAdvisory.objects.filter(id=advisory.id).exists()
        assert not AdvisoryVulnerability.objects.filter(id=vulnerability.id).exists()

    def test_it_resolves_by_tracking_id_too(self, sample_team):
        advisory = _advisory(sample_team, status="published", tracking_id="OSPN-2026-0001", published_at=timezone.now())

        result = delete_advisory(sample_team, "OSPN-2026-0001")

        assert result.ok
        assert not SecurityAdvisory.objects.filter(id=advisory.id).exists()

    def test_another_workspaces_advisory_is_not_found(self, sample_team):
        from sbomify.apps.teams.models import Team

        other = Team.objects.create(name="Someone else")
        advisory = _advisory(other)

        result = delete_advisory(sample_team, advisory.id)

        assert not result.ok
        assert result.status_code == 404
        assert SecurityAdvisory.objects.filter(id=advisory.id).exists()
