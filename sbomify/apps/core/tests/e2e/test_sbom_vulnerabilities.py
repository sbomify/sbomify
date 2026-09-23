"""Snapshot and interaction coverage for flat vulnerability reports."""

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
    """One row per vulnerability and affected package, with triage and references."""

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
    """A completed run with no findings: the stats strip plus "No vulnerabilities found"."""

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


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("view", ["component", "report", "plugin"])
def test_finding_controls_and_triage(authenticated_page, sbom_with_findings, monkeypatch, width, view):
    """The same controls search the whole scan and keep triage wired after swaps."""
    from copy import deepcopy

    from django.urls import reverse
    from playwright.sync_api import expect

    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.vulnerability_scanning import kev

    sbom = sbom_with_findings
    run = AssessmentRun.objects.get(sbom=sbom, plugin_name="dependency_track")
    findings = run.result["findings"]
    for index in range(4, 16):
        finding = deepcopy(findings[-1])
        finding["id"] = f"CVE-2024-{index:04d}"
        finding["title"] = f"Parser issue {index}"
        findings.append(finding)
    findings[-1]["analysis_state"] = "in_triage"
    run.save(update_fields=["result"])
    monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2024-0001"}))

    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if view == "component":
        page.goto(reverse("core:component_details", args=[sbom.component_id]))
        panel = page.locator("#component-vulnerabilities-table")
    elif view == "report":
        page.goto(reverse("sboms:sbom_vulnerabilities", args=[sbom.id]))
        panel = page.locator("#scan-vulnerabilities")
    else:
        page.goto(reverse("core:component_item", args=[sbom.component_id, "sboms", sbom.id]))
        page.locator(f"#run-trigger-{run.id}").click()
        panel = page.locator(f"#findings-{run.id}")

    expect(panel.get_by_role("combobox", name="Rows per page")).to_be_visible()
    panel.get_by_role("combobox", name="Rows per page").select_option("5")
    expect(panel.get_by_text("Showing 1 to 5 of 15 vulnerabilities", exact=True)).to_be_visible()
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    panel.get_by_role("link", name="Next page", exact=True).click()
    expect(panel.get_by_text("Showing 6 to 10 of 15 vulnerabilities", exact=True)).to_be_visible()
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    panel.get_by_role("combobox", name="Rows per page").select_option("10")
    expect(panel.get_by_text("Showing 1 to 10 of 15 vulnerabilities", exact=True)).to_be_visible()
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    if view == "component" and width == 1280:
        search = panel.get_by_role("searchbox", name="Search vulnerabilities")
        search.fill("Parser issue")
        search.press("Home")
        expect(panel.get_by_text("Showing 1 to 10 of 12 vulnerabilities", exact=True)).to_be_visible()
        expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
        expect(search).to_be_focused()
        assert search.evaluate("input => input.selectionStart") == 0
    panel.get_by_role("searchbox", name="Search vulnerabilities").fill("Parser issue 15")
    expect(panel.get_by_text("Showing 1 to 1 of 1 vulnerabilities", exact=True)).to_be_visible()
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    expect(panel.get_by_role("button", name="Triage", exact=True)).to_have_count(1)
    panel.get_by_role("button", name="Triage", exact=True).click()
    modal = page.locator("#triage-modal")
    expect(modal).to_be_visible()
    expect(modal.get_by_role("heading")).to_contain_text("CVE-2024-0015")
    expect(modal.locator("#triage-scope")).to_have_value("package")
    expect(modal.locator("#triage-state")).to_have_value("in_triage")
    expect(modal.locator("#triage-scope option:checked")).to_contain_text("pkg:pypi/urllib3@2.0.7")
    modal.get_by_role("button", name="Cancel", exact=True).click()
    panel.get_by_role("link", name="Clear filters").click()
    expect(panel.get_by_role("searchbox", name="Search vulnerabilities")).to_have_value("")
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    panel.get_by_role("combobox", name="Filter by severity").select_option("critical")
    expect(panel.get_by_text("Showing 1 to 1 of 1 vulnerabilities", exact=True)).to_be_visible()
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    panel.get_by_role("link", name="Clear filters").click()
    expect(panel.get_by_role("combobox", name="Filter by severity")).to_have_value("all")
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    panel.get_by_role("checkbox", name="Known exploited (1)").check()
    expect(panel.get_by_text("Showing 1 to 1 of 1 vulnerabilities", exact=True)).to_be_visible()
    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)
    expect(panel.get_by_role("button", name="Triage", exact=True)).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert errors == []


@pytest.mark.django_db
def test_full_report_saves_package_triage(authenticated_page, sbom_with_findings, mocker):
    """The report submits through the existing API and writes a separate VEX artifact."""
    import json

    from django.urls import reverse
    from playwright.sync_api import expect

    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    upload = mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_sbom", return_value="triage.json")
    mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=None)
    mocker.patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply")
    sbom = sbom_with_findings
    original_filename = sbom.sbom_filename
    page = authenticated_page
    page.goto(reverse("sboms:sbom_vulnerabilities", args=[sbom.id]))
    page.locator("#scan-vulnerabilities").get_by_role("button", name="Triage", exact=True).first.click()
    modal = page.locator("#triage-modal")
    modal.locator("#triage-state").select_option("in_triage")
    modal.locator("#triage-detail").fill("Reviewing the parser's exposure.")
    with page.expect_response(
        lambda response: response.url.endswith("/triage") and response.request.method == "POST"
    ) as response:
        modal.get_by_role("button", name="Save decision", exact=True).click()
    assert response.value.status == 200
    expect(modal).not_to_be_visible()
    assert SBOM.objects.filter(component_id=sbom.component_id, source=TRIAGE_SOURCE).count() == 1
    document = json.loads(upload.call_args.args[0])
    decision = document["vulnerabilities"][0]
    assert decision["id"] == "CVE-2024-0001"
    assert decision["analysis"]["state"] == "in_triage"
    assert decision["affects"][0]["ref"] == "pkg:pypi/requests@2.31.0"
    sbom.refresh_from_db()
    assert sbom.sbom_filename == original_filename
