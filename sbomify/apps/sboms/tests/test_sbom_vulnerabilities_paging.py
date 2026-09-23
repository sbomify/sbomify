"""The full scan report holds one page of packages, not all of them.

This page is where the component panel's "View full scan report" link goes, so
capping the panel without capping this would only move the timeout: both render
a card per advisory, and a BSP-class SBOM carries thousands. The panel measured
5.1 s and 8.5 MB for 2,390 findings; this page renders strictly more per
finding.

Ordering is part of the fix rather than a separate nicety. Once the list is
paged, its order decides what page one holds, and provider order would put a
critical on page 40 because that is where the scanner happened to report it.
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


def _finding(advisory: str, package: str, severity: str = "medium") -> dict:
    return {
        "id": advisory,
        "severity": severity,
        "component": {"name": package, "version": "1.0", "ecosystem": "deb"},
    }


def _client(sbom: SBOM) -> Client:
    client = Client()
    team = sbom.component.team
    setup_test_session(client, team, team.members.first())
    return client


def _packages(response) -> list[dict]:
    return response.context["vulnerabilities"]["results"][0]["packages"]


def test_a_large_scan_renders_one_page_of_packages(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert len(_packages(response)) == PACKAGES_PER_PAGE
    assert response.context["page_obj"].paginator.count == 60
    assert "CVE-2026-0059" not in response.content.decode()


def test_the_second_page_continues_the_list(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}), {"page": "2"}
    )

    names = [p["package"]["name"] for p in _packages(response)]
    assert names == [f"pkg-{n:04d}" for n in range(25, 50)]
    assert response.context["page_obj"].number == 2


def test_the_worst_package_is_on_the_first_page(sample_sbom: SBOM):  # noqa: F811
    """Provider order would have buried it, which is the trap paging introduces."""
    findings = [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}", severity="low") for n in range(60)]
    findings.append(_finding("CVE-2026-9999", "zzz-last-reported", severity="critical"))
    _run(sample_sbom, findings)

    response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert _packages(response)[0]["package"]["name"] == "zzz-last-reported"


def test_a_small_scan_still_shows_everything_with_no_pager(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding("CVE-2026-1", "openssl"), _finding("CVE-2026-2", "zlib")])

    response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

    assert len(_packages(response)) == 2
    assert response.context["page_obj"].has_other_pages() is False
    assert "Package pagination" not in response.content.decode()


def test_a_page_past_the_end_lands_on_the_last_one(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}), {"page": "99"}
    )

    assert response.status_code == 200
    assert response.context["page_obj"].number == 3
    assert _packages(response)


def test_a_nonsense_page_reads_as_the_first(sample_sbom: SBOM):  # noqa: F811
    _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", f"pkg-{n:04d}") for n in range(60)])

    response = _client(sample_sbom).get(
        reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}), {"page": "banana"}
    )

    assert response.status_code == 200
    assert response.context["page_obj"].number == 1


class TestOnePackageCannotRebuildTheOversizedPage:
    """Paging the packages bounds the groups, not the cards.

    The cards are advisories. A kernel or a libc in a BSP image carries hundreds
    on its own, so twenty-five packages each holding four hundred advisories
    recreates exactly the response this page was paginated to avoid.
    """

    def test_one_packages_advisories_are_capped(self, sample_sbom: SBOM):  # noqa: F811
        findings = [_finding(f"CVE-2026-{n:04d}", "linux-yocto") for n in range(400)]
        _run(sample_sbom, findings)

        response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

        package = _packages(response)[0]
        assert len(package["vulnerabilities"]) == MAX_ADVISORIES_PER_PACKAGE
        assert package["hidden_count"] == 400 - MAX_ADVISORIES_PER_PACKAGE

    def test_the_row_still_summarises_the_whole_package(self, sample_sbom: SBOM):  # noqa: F811
        """Capped after the counts, so the header does not shrink with the list."""
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "linux-yocto") for n in range(400)])

        response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

        assert _packages(response)[0]["open_count"] == 400
        assert "400" in response.content.decode()

    def test_the_page_says_what_it_left_out(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding(f"CVE-2026-{n:04d}", "linux-yocto") for n in range(400)])

        response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

        assert f"Showing the {MAX_ADVISORIES_PER_PACKAGE} most severe of 400" in response.content.decode()

    def test_a_small_package_is_not_capped_and_says_nothing(self, sample_sbom: SBOM):  # noqa: F811
        _run(sample_sbom, [_finding("CVE-2026-1", "openssl"), _finding("CVE-2026-2", "openssl")])

        response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

        package = _packages(response)[0]
        assert len(package["vulnerabilities"]) == 2
        assert package["hidden_count"] == 0
        assert "most severe of" not in response.content.decode()

    def test_the_response_is_bounded_whatever_the_scan_holds(self, sample_sbom: SBOM):  # noqa: F811
        """The ceiling is PACKAGES_PER_PAGE x MAX_ADVISORIES_PER_PACKAGE, not the scan."""
        findings = [_finding(f"CVE-2026-{p:02d}{n:03d}", f"pkg-{p:02d}") for p in range(40) for n in range(200)]
        _run(sample_sbom, findings)

        response = _client(sample_sbom).get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sample_sbom.id}))

        cards = sum(len(p["vulnerabilities"]) for p in _packages(response))
        assert cards <= PACKAGES_PER_PAGE * MAX_ADVISORIES_PER_PACKAGE
        assert len(response.content) < 2 * 1024 * 1024, f"{len(response.content)} bytes for 8,000 findings"
