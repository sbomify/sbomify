"""Snapshot coverage for the per-SBOM vulnerabilities page.

The page had no e2e referee, so it is added here before the template is
migrated to the component library: the baselines capture the render as it is
today. Two cases, because the page has two shapes that share nothing below the
header: the merged scan-results table, and the "no scan data" notice a run with
no findings falls back to.
"""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.fixture
def sbom_with_findings(sbom_component_details):
    """The fixture SBOM plus a second provider run carrying real findings.

    The fixture's own run stores an empty findings list, so the view merges
    nothing and falls through to the empty state. A second provider (distinct
    plugin_name, so ``distinct("plugin_name")`` keeps both) supplies the
    packages, severities, CVSS scores and references the table renders.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM

    sbom = SBOM.objects.get(component=sbom_component_details)

    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency_track",
        plugin_version="1.0.0",
        plugin_config_hash="e2e",
        category="security",
        status="completed",
        run_reason="on_upload",
        result={
            "summary": {"total_findings": 3, "by_severity": {"critical": 1, "high": 1, "low": 1}},
            "findings": [
                {
                    "id": "CVE-2024-0001",
                    "aliases": ["GHSA-aaaa-bbbb-cccc"],
                    "title": "Remote code execution in the request parser",
                    "description": (
                        "A crafted request header lets an attacker run arbitrary code in the parser process. "
                        "Upgrade to 2.31.1 or later."
                    ),
                    "severity": "critical",
                    "cvss_score": 9.8,
                    "references": [
                        "https://example.com/advisories/CVE-2024-0001",
                        "https://example.com/commits/abc123",
                    ],
                    "source": "dependency_track",
                    "component": {
                        "name": "requests",
                        "version": "2.31.0",
                        "ecosystem": "PyPI",
                        "purl": "pkg:pypi/requests@2.31.0",
                    },
                },
                {
                    "id": "CVE-2024-0002",
                    "aliases": [],
                    "title": "Denial of service on malformed chunked bodies",
                    "description": "A malformed chunked body loops the reader until the worker times out.",
                    "severity": "high",
                    "cvss_score": 7.5,
                    "references": [
                        "https://example.com/advisories/CVE-2024-0002",
                        "https://example.com/issues/42",
                        "https://example.com/patches/9f8e7d",
                        "https://example.com/mailing-list/2024-01",
                    ],
                    "source": "dependency_track",
                    "component": {
                        "name": "requests",
                        "version": "2.31.0",
                        "ecosystem": "PyPI",
                        "purl": "pkg:pypi/requests@2.31.0",
                    },
                },
                {
                    "id": "CVE-2024-0003",
                    "aliases": [],
                    "title": "",
                    "description": "",
                    "severity": "low",
                    "cvss_score": 3.1,
                    "references": [],
                    "source": "dependency_track",
                    "component": {
                        "name": "urllib3",
                        "version": "2.0.7",
                        "ecosystem": "PyPI",
                        "purl": "pkg:pypi/urllib3@2.0.7",
                    },
                },
            ],
        },
    )
    return sbom


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSbomVulnerabilitiesSnapshot:
    """The merged scan-results table: package rows, severity badges, references."""

    def test_sbom_vulnerabilities_snapshot(
        self,
        authenticated_page: Page,
        sbom_with_findings,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/sbom/{sbom_with_findings.id}/vulnerabilities")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSbomVulnerabilitiesEmptySnapshot:
    """A completed run with no findings: the stats strip plus the no-data notice."""

    def test_sbom_vulnerabilities_no_data_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        from sbomify.apps.sboms.models import SBOM

        sbom = SBOM.objects.get(component=sbom_component_details)

        authenticated_page.goto(f"/sbom/{sbom.id}/vulnerabilities")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
