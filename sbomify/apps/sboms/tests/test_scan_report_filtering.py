"""Narrowing the full scan report without flattening it.

Reported by a pilot customer, who asked for two things: a way to filter, and a
flat list rather than the package grouping. They do not get the same answer.

Finding-level work has two homes now, the component panel and the assessment
card, and both search, filter and triage. What this report has that neither has
is the grouping, which answers "what do I need to upgrade". So the filters
narrow the advisories inside each package and drop the packages left with
nothing, and a severity filter reads as "which packages have a critical".
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk import RunReason
from sbomify.apps.sboms.views.sbom_vulnerabilities import MAX_ADVISORIES_PER_PACKAGE, PACKAGES_PER_PAGE

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


def _packages(response) -> list[dict]:
    data = response.context["vulnerabilities"]
    return data["results"][0]["packages"] if data else []


class TestTheFiltersNarrowIt:
    def test_severity_keeps_only_packages_holding_one(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "critical"),
                _finding("CVE-2026-0002", "zlib", "low"),
                _finding("CVE-2026-0003", "curl", "low"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert [entry["package"]["name"] for entry in _packages(response)] == ["openssl"]

    def test_search_matches_the_package_name(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl"), _finding("CVE-2026-0002", "zlib")],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_search="zlib")

        assert [entry["package"]["name"] for entry in _packages(response)] == ["zlib"]

    def test_search_matches_the_advisory_id(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl"), _finding("CVE-2026-0002", "zlib")],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_search="CVE-2026-0002")

        assert [entry["package"]["name"] for entry in _packages(response)] == ["zlib"]

    def test_a_package_keeps_only_its_matching_advisories(self, sample_sbom: SBOM):  # noqa: F811
        """The grouping survives the filter; the group gets smaller."""
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "critical"),
                _finding("CVE-2026-0002", "openssl", "low"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        entry = _packages(response)[0]
        assert [row["id"] for row in entry["vulnerabilities"]] == ["CVE-2026-0001"]

    def test_a_filter_matching_nothing_says_so(self, sample_sbom: SBOM):  # noqa: F811
        """An empty report reads as a clean scan, which is a different thing."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "low")])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert _packages(response) == []
        assert "No matches found" in response.content.decode()

    def test_an_unfiltered_report_is_unchanged(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(4)])

        response = _report(sample_sbom)

        assert len(_packages(response)) == 4


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

        assert [entry["package"]["name"] for entry in _packages(response)] == ["zlib"]

    def test_leaving_it_ticked_shows_them(self, sample_sbom: SBOM):  # noqa: F811
        _run(
            sample_sbom,
            [
                _finding("CVE-2026-0001", "openssl", "high", analysis_state="not_affected"),
                _finding("CVE-2026-0002", "zlib", "high"),
            ],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_suppressed="1")

        assert {entry["package"]["name"] for entry in _packages(response)} == {"openssl", "zlib"}

    def test_the_toolbar_counts_it_as_narrowed(self, sample_sbom: SBOM):  # noqa: F811
        """So the Clear control is offered and the empty state reads correctly."""
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom, scan_submitted="1")

        assert response.context["scan_is_narrowed"] is True

    def test_an_untouched_page_is_not_narrowed(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-0001", "openssl", "high")])

        response = _report(sample_sbom)

        assert response.context["scan_is_narrowed"] is False


class TestTheRowStillDescribesTheWholePackage:
    def test_the_counts_are_not_recomputed_from_the_filtered_subset(self, sample_sbom: SBOM):  # noqa: F811
        """A row saying "1 of 40" under a critical filter is the useful reading.
        One saying "1 of 1" hides the other thirty-nine, which is what the
        reader is deciding about."""
        findings = [_finding("CVE-2026-0001", "openssl", "critical")]
        findings += [_finding(f"CVE-2026-{n:04d}", "openssl", "low") for n in range(2, 40)]
        _run(sample_sbom, findings)

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        entry = _packages(response)[0]
        assert len(entry["vulnerabilities"]) == 1
        assert entry["open_count"] == 39


class TestTheBoundsStillHold:
    def test_filtering_does_not_lift_the_package_cap(self, sample_sbom: SBOM):  # noqa: F811
        """Both caps exist because this page had no bound at all before it was
        paged. A filter must not become a way around them."""
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}", "high") for n in range(60)])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="high")

        assert len(_packages(response)) == PACKAGES_PER_PAGE

    def test_filtering_does_not_lift_the_per_package_cap(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "openssl", "high") for n in range(40)])

        response = _report(sample_sbom, scan_submitted="1", scan_severity="high")

        entry = _packages(response)[0]
        assert len(entry["vulnerabilities"]) == MAX_ADVISORIES_PER_PACKAGE


class TestTheToolbarOffersWhatIsThere:
    def test_the_severities_come_from_the_whole_scan(self, sample_sbom: SBOM):  # noqa: F811
        """Built before filtering, so choosing one severity does not empty the
        dropdown that chose it."""
        _run(
            sample_sbom,
            [_finding("CVE-2026-0001", "openssl", "critical"), _finding("CVE-2026-0002", "zlib", "low")],
        )

        response = _report(sample_sbom, scan_submitted="1", scan_severity="critical")

        assert response.context["scan_severity_options"] == ["critical", "low"]
