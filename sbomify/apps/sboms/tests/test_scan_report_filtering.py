"""The flat scan report filters all advisories before paging."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.sboms.services.vulnerability_report import PAGE_SIZE

from ..models import SBOM
from .fixtures import sample_component, sample_sbom  # noqa: F401
from .test_views import setup_test_session

pytestmark = pytest.mark.django_db


def _run(sbom: SBOM, findings: list[dict]) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        plugin_version="1.0",
        plugin_config_hash="x",
        category="security",
        status="completed",
        run_reason=RunReason.MANUAL.value,
        result={"findings": findings},
    )


def _finding(advisory: str, package: str, severity: str = "medium", **extra) -> dict:
    return {
        "id": advisory,
        "severity": severity,
        "component": {"name": package, "version": "1.0", "ecosystem": "deb"},
        **extra,
    }


def _client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


def _report(sbom: SBOM, **params):
    url = reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sbom.id})
    return _client(sbom).get(url, params)


def _rows(response) -> list[dict]:
    data = response.context["scan_panel"]
    return data["rows"] if data else []


class TestTheFiltersNarrowIt:
    def test_severity_keeps_only_matching_advisories(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "critical"),
                _finding("CVE-2026-0002", "zlib", "low"),
                _finding("CVE-2026-0003", "curl", "low"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert [entry["package"] for entry in _rows(response)] == ["openssl"]

    def test_search_matches_the_package_name(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl"), _finding("CVE-2026-0002", "zlib")],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_search="zlib")

        assert [entry["package"] for entry in _rows(response)] == ["zlib"]

    def test_search_matches_the_advisory_id(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl"), _finding("CVE-2026-0002", "zlib")],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_search="CVE-2026-0002")

        assert [entry["package"] for entry in _rows(response)] == ["zlib"]

    def test_a_package_keeps_only_its_matching_advisories(self, sample_sbom: SBOM):  # noqa: F811
        """Only matching advisories appear, even when they share a package."""
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "critical"),
                _finding("CVE-2026-0002", "openssl", "low"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert [row["id"] for row in _rows(response)] == ["CVE-2026-0001"]

    def test_a_filter_matching_nothing_says_so(self, sample_sbom: SBOM):  # noqa: F811
        """An empty report reads as a clean scan, which is a different thing."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "low")])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert _rows(response) == []
        assert "No vulnerabilities match these filters." in response.content.decode()

    def test_an_unfiltered_report_is_unchanged(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(4)])

        response = _report(sample_sbom)

        assert len(_rows(response)) == 4


class TestTheSuppressedToggleIsAFilter:
    def test_unticking_it_hides_suppressed_advisories_on_its_own(self, sample_sbom: SBOM):  # noqa: F811
        """It has to narrow the list without another filter being active.

        ``FindingQuery.is_filtered`` covers search, severity, state and KEV but
        not this toggle, so gating on it alone made the box do nothing unless
        something else was already set.
        """
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "high", analysis_state="not_affected"),
                _finding("CVE-2026-0002", "zlib", "high"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1")

        assert [entry["package"] for entry in _rows(response)] == ["zlib"]

    def test_leaving_it_ticked_shows_them(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "high", analysis_state="not_affected"),
                _finding("CVE-2026-0002", "zlib", "high"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_suppressed="1")

        assert {entry["package"] for entry in _rows(response)} == {"openssl", "zlib"}

    def test_the_toolbar_counts_it_as_narrowed(self, sample_sbom: SBOM):  # noqa: F811
        """So the Clear control is offered and the empty state reads correctly."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom, scan_submitted="1")

        assert response.context["scan_panel"]["query"].show_suppressed is False

    def test_an_untouched_page_is_not_narrowed(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom)

        assert response.context["scan_panel"]["query"].show_suppressed is True


class TestTheFilterKeepsTheUnfilteredTotal:
    def test_the_counts_are_not_recomputed_from_the_filtered_subset(self, sample_sbom: SBOM):  # noqa: F811
        findings = [_finding("CVE-2026-0001", "openssl", "critical")]
        findings += [_finding(f"CVE-2026-{n:04d}", "openssl", "low") for n in range(2, 40)]
        _run(sample_sbom, findings)

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert len(_rows(response)) == 1
        assert response.context["scan_panel"]["unfiltered_total"] == 39


class TestTheBoundsStillHold:
    def test_filtering_keeps_the_page_size_bound(self, sample_sbom: SBOM):  # noqa: F811
        """A filter must not turn a bounded page into the whole report."""
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}", "high") for n in range(60)])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="high")

        assert len(_rows(response)) == PAGE_SIZE

    def test_one_package_uses_the_same_page_size_bound(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "openssl", "high") for n in range(40)])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="high")

        assert len(_rows(response)) == PAGE_SIZE
        assert response.context["scan_panel"]["total"] == 40


class TestTheToolbarOffersWhatIsThere:
    def test_the_severities_come_from_the_whole_scan(self, sample_sbom: SBOM):  # noqa: F811
        """Built before filtering, so choosing one severity does not empty the
        dropdown that chose it."""
        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl", "critical"), _finding("CVE-2026-0002", "zlib", "low")],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert response.context["scan_panel"]["severity_options"] == ["critical", "low"]

    def test_a_severity_no_advisory_carries_is_still_offered(self, sample_sbom: SBOM):  # noqa: F811
        """A scanner may report a severity of its own, so the parser keeps any
        well-formed token. A bookmarked link carrying one no advisory has would
        otherwise leave the select rendering as "All Severities" over an empty
        report, with nothing on the page naming what emptied it."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "critical")])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="moderate")

        assert "moderate" in response.context["scan_panel"]["severity_options"]
        assert _rows(response) == []

    def test_an_unreported_severity_is_not_offered_unprompted(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "critical")])

        response = _report(sample_sbom)

        assert response.context["scan_panel"]["severity_options"] == ["critical"]


class TestPagingKeepsTheFilter:
    """The pager sits outside the filter form and pages packages, so its links
    carry the toolbar's state or following one returns the reader to an
    unfiltered report, which is the state they just left."""

    def test_the_pager_links_carry_the_search(self, sample_sbom: SBOM):  # noqa: F811
        findings = [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:03d}", "high") for n in range(PAGE_SIZE + 5)]
        _run(sample_sbom, findings)

        response = _report(sample_sbom, scan_submitted="1", scan_search="pkg-0")

        assert "scan_search=pkg-0" in response.context["scan_query_string"]
        assert "scan_submitted=1" in response.context["scan_query_string"]

    def test_it_carries_the_suppressed_choice_too(self, sample_sbom: SBOM):  # noqa: F811
        """Unticking the box is a choice the marker carries, so a pager link
        that dropped it would quietly show the suppressed rows again."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom, scan_submitted="1")

        assert "scan_suppressed" not in response.context["scan_query_string"]
        assert "scan_submitted=1" in response.context["scan_query_string"]

    def test_an_unfiltered_report_keeps_its_links_clean(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        assert _report(sample_sbom).context["scan_query_string"] == "scan_submitted=1&scan_suppressed=1"

    def test_the_filter_query_does_not_duplicate_the_page_parameter(self, sample_sbom: SBOM):  # noqa: F811
        """The shared pager supplies the page number separately from its filters."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom, scan_submitted="1", scan_search="openssl", scan_page="3")

        assert "scan_page" not in response.context["scan_query_string"]

    def test_the_rendered_pager_holds_the_filter(self, sample_sbom: SBOM):  # noqa: F811
        findings = [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:03d}", "high") for n in range(PAGE_SIZE + 5)]
        _run(sample_sbom, findings)

        body = _report(sample_sbom, scan_submitted="1", scan_severity="high").content.decode()

        assert "page=2&amp;scan_submitted=1&amp;scan_severity=high" in body


class TestTheStateAndKevFilters:
    """The report was asked for four filters: search, severity, VEX state and
    KEV. The first two landed with the toolbar; these are the other two."""

    def test_kev_only_keeps_the_exploited_advisories(self, sample_sbom: SBOM, monkeypatch):  # noqa: F811
        """The predicate read a `kev` key the merged advisories never carried,
        so this filter matched nothing at all and emptied the report."""
        from sbomify.apps.vulnerability_scanning import kev

        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl", "high"), _finding("CVE-2026-0002", "zlib", "high")],
        )
        monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2026-0001"}))

        response = _report(sample_sbom, scan_submitted="1", scan_kev="1")

        assert [entry["package"] for entry in _rows(response)] == ["openssl"]

    def test_an_alias_counts_as_exploited_too(self, sample_sbom: SBOM, monkeypatch):  # noqa: F811
        """Merging folds every id an advisory answers to into one entry, which
        is why the mark is stamped after the fold rather than per provider."""
        from sbomify.apps.vulnerability_scanning import kev

        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high", aliases=["GHSA-aaaa-bbbb-cccc"])])
        monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"ghsa-aaaa-bbbb-cccc"}))

        response = _report(sample_sbom, scan_submitted="1", scan_kev="1")

        assert len(_rows(response)) == 1

    def test_the_control_counts_the_whole_scan(self, sample_sbom: SBOM, monkeypatch):  # noqa: F811
        from sbomify.apps.vulnerability_scanning import kev

        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl", "high"), _finding("CVE-2026-0002", "zlib", "high")],
        )
        monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2026-0001"}))

        response = _report(sample_sbom, scan_submitted="1", scan_kev="1")

        assert response.context["scan_panel"]["kev_total"] == 1
        assert "scan_kev" in response.content.decode()

    def test_kev_filter_is_hidden_when_the_catalog_has_no_matches(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom)

        assert response.context["scan_panel"]["kev_total"] == 0
        assert "scan_kev" not in response.content.decode()

    def test_the_state_filter_narrows_the_report(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "high", analysis_state="exploitable"),
                _finding("CVE-2026-0002", "zlib", "high"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_state="exploitable")

        assert [entry["package"] for entry in _rows(response)] == ["openssl"]

    def test_an_undecided_advisory_reads_as_open(self, sample_sbom: SBOM):  # noqa: F811
        """No decision is a state the reader can filter by, which is why the
        options come from the same mapping the predicate uses."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom, scan_submitted="1", scan_state="open")

        assert len(_rows(response)) == 1
        assert {option["value"] for option in response.context["scan_panel"]["state_options"]} == {"open"}

    def test_the_state_options_carry_their_labels(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high", analysis_state="not_affected")])

        options = _report(sample_sbom).context["scan_panel"]["state_options"]

        assert {option["value"]: option["label"] for option in options}["not_affected"] == "Not affected"
