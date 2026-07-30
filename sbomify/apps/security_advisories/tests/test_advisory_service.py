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
    get_advisory,
    list_advisories,
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

    def test_anything_else_reads_as_other(self, sample_team):
        _advisory(sample_team)

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
