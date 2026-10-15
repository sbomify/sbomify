"""Interaction coverage for an SBOM's vulnerabilities, as the component page and the workspace list show them.

The per-SBOM report these tests once drove is gone: its URL now redirects to the
workspace Vulnerabilities page filtered to the component and that SBOM. Both
lists read the projected ``Finding`` rows, so every scan here is synced.
"""

import re

import pytest

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.tests.shared_fixtures import register_plugin


@pytest.fixture
def sbom_with_findings(sbom_component_details, mocker):
    """The fixture SBOM plus a second provider run carrying real findings.

    The fixture's own run stores an empty findings list. A second provider
    (distinct plugin_name, so the newest run of each is read) supplies the
    packages, severities, CVSS scores and references the table renders. The
    lists read projected rows, so the run is synced as a scan would be.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    sbom = SBOM.objects.get(component=sbom_component_details)
    # This fixture creates database rows, not an uploaded artifact. Keep the
    # detail page's lazy crypto inventory from waiting on live object storage.
    mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=None)

    register_plugin("dependency_track")
    run = AssessmentRun.objects.create(
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
    sync_findings(run, statements=[])
    return sbom


def _pad_findings(sbom, *, in_triage_last: bool = False):
    """Fifteen findings, so a page of ten leaves a second page to be on."""
    from copy import deepcopy

    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    run = AssessmentRun.objects.get(sbom=sbom, plugin_name="dependency_track")
    findings = run.result["findings"]
    for index in range(4, 16):
        finding = deepcopy(findings[-1])
        finding["id"] = f"CVE-2024-{index:04d}"
        finding["title"] = f"Parser issue {index}"
        findings.append(finding)
    if in_triage_last:
        findings[-1]["analysis_state"] = "in_triage"
    run.save(update_fields=["result"])
    sync_findings(run, statements=[])
    return run


def _open_component_panel(page, sbom):
    from django.urls import reverse

    page.goto(reverse("core:component_details", args=[sbom.component_id]))
    return page.locator("#component-vulnerabilities-table")


def _settled(page):
    from playwright.sync_api import expect

    expect(page.locator(".htmx-request, .htmx-settling")).to_have_count(0)


def _to_second_page_of_ten(page, panel):
    """Ten to a page, on page two: somewhere a reload would not return the reader to."""
    from playwright.sync_api import expect

    expect(panel.locator("#vulnerabilities-page-size")).to_be_visible()
    panel.locator("#vulnerabilities-page-size").select_option("10")
    expect(panel.get_by_text("Showing 1 to 10 of 15", exact=True)).to_be_visible()
    _settled(page)
    panel.get_by_role("link", name="Next page", exact=True).click()
    expect(panel.get_by_text("Showing 11 to 15 of 15", exact=True)).to_be_visible()
    _settled(page)


def _open_row_triage(page, panel, advisory_id: str):
    """Triage lives in each row's actions menu."""
    _row_menu(panel, advisory_id).click()
    page.get_by_role("menuitem", name="Triage", exact=True).click()
    return page.locator("#triage-modal")


def _row_menu(panel, advisory_id: str):
    """A row's actions menu. Its name also says which package it acts on, after the advisory."""
    return panel.get_by_role("button", name=re.compile(rf"^Actions for {re.escape(advisory_id)} in "))


def _first_advisory_on_page(panel) -> str:
    label = panel.locator("tbody").get_by_role("button", name="Actions for ").first.get_attribute("aria-label")
    assert label and label.startswith("Actions for ")
    return label.removeprefix("Actions for ").split(" in ", 1)[0]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 390])
def test_finding_controls_and_triage(authenticated_page, sbom_with_findings, monkeypatch, width):
    """The panel's controls search the whole scan and keep triage wired after swaps."""
    from playwright.sync_api import expect

    from sbomify.apps.vulnerability_scanning import kev

    sbom = sbom_with_findings
    _pad_findings(sbom, in_triage_last=True)
    monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2024-0001"}))

    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    panel = _open_component_panel(page, sbom)

    _to_second_page_of_ten(page, panel)
    search = panel.get_by_role("searchbox", name="Search vulnerabilities")
    if width == 1280:
        search.fill("CVE-2024-001")
        search.press("Home")
        expect(panel.get_by_text("Showing 1 to 6 of 6", exact=True)).to_be_visible()
        _settled(page)
        expect(search).to_be_focused()
        assert search.evaluate("input => input.selectionStart") == 0
    search.fill("CVE-2024-0015")
    expect(panel.get_by_text("Showing 1 to 1 of 1", exact=True)).to_be_visible()
    _settled(page)
    expect(_row_menu(panel, "CVE-2024-0015")).to_have_count(1)
    modal = _open_row_triage(page, panel, "CVE-2024-0015")
    expect(modal).to_be_visible()
    expect(modal.get_by_role("heading")).to_contain_text("CVE-2024-0015")
    expect(modal.locator("#triage-scope")).to_have_value("package")
    expect(modal.locator("#triage-state")).to_have_value("in_triage")
    expect(modal.locator("#triage-scope option:checked")).to_contain_text("pkg:pypi/urllib3@2.0.7")
    modal.get_by_role("button", name="Cancel", exact=True).click()
    search.fill("")
    expect(panel.get_by_text("Showing 1 to 10 of 15", exact=True)).to_be_visible()
    _settled(page)
    panel.get_by_role("combobox", name="Filter by severity").select_option("critical")
    expect(panel.get_by_text("Showing 1 to 1 of 1", exact=True)).to_be_visible()
    _settled(page)
    panel.get_by_role("combobox", name="Filter by severity").select_option("")
    expect(panel.get_by_text("Showing 1 to 10 of 15", exact=True)).to_be_visible()
    _settled(page)
    panel.get_by_role("combobox", name="Filter by urgency").select_option("exploited")
    expect(panel.get_by_text("Showing 1 to 1 of 1", exact=True)).to_be_visible()
    _settled(page)
    expect(_row_menu(panel, "CVE-2024-0001")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert errors == []


@pytest.mark.django_db
def test_old_report_url_lands_on_the_list_and_saves_package_triage(authenticated_page, sbom_with_findings, mocker):
    """The old report's URL opens the workspace list at that SBOM, and triage there writes a separate VEX."""
    import json
    import re

    from django.urls import reverse
    from playwright.sync_api import expect

    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    upload = mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_sbom", return_value="triage.json")
    mocker.patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply")
    sbom = sbom_with_findings
    original_filename = sbom.sbom_filename
    page = authenticated_page
    page.goto(reverse("sboms:sbom_vulnerabilities", args=[sbom.id]))
    expect(page).to_have_url(re.compile(rf"/vulnerability-scans/\?component={sbom.component_id}&version={sbom.id}$"))
    expect(page.locator("#vulnerabilities-version")).to_be_visible()
    results = page.locator("#vulnerabilities-results")
    modal = _open_row_triage(page, results, "CVE-2024-0001")
    expect(modal).to_be_visible()
    modal.locator("#triage-state").select_option("in_triage")
    modal.locator("#triage-detail").fill("Reviewing the parser's exposure.")
    with page.expect_response(
        lambda response: response.url.endswith("/triage") and response.request.method == "POST"
    ) as response:
        modal.get_by_role("button", name="Save decision", exact=True).click()
    assert response.value.status == 200
    assert response.value.url.endswith(f"/components/{sbom.component_id}/triage")
    expect(modal).not_to_be_visible()
    assert SBOM.objects.filter(component_id=sbom.component_id, source=TRIAGE_SOURCE).count() == 1
    document = json.loads(upload.call_args.args[0])
    decision = document["vulnerabilities"][0]
    assert decision["id"] == "CVE-2024-0001"
    assert decision["analysis"]["state"] == "in_triage"
    assert decision["affects"][0]["ref"] == "pkg:pypi/requests@2.31.0"
    sbom.refresh_from_db()
    assert sbom.sbom_filename == original_filename


@pytest.mark.django_db
def test_a_refresh_keeps_a_half_written_triage_justification(authenticated_page, sbom_with_findings, monkeypatch):
    """A refresh arriving mid sentence must not take what was typed."""
    from playwright.sync_api import expect

    from sbomify.apps.vulnerability_scanning import kev

    sbom = sbom_with_findings
    monkeypatch.setattr(kev, "kev_ids_for_serialization", lambda: frozenset({"cve-2024-0001"}))

    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 900})
    panel = _open_component_panel(page, sbom)
    page.wait_for_load_state("networkidle")
    # The control a reader uses, not a synthesised event.
    _open_row_triage(page, panel, "CVE-2024-0001")
    # By id: the visible label reads "Detail (optional)".
    detail = page.locator("#triage-detail")
    expect(detail).to_be_visible()
    detail.fill("Not reachable from any entry point")

    # Observable readiness, not a delay: dispatch and wait for htmx to settle
    # the results region, or the assertions below race the swap.
    page.evaluate(
        """() => {
            window.__refreshSettled = false;
            const settled = (event) => {
                if (event.target.id !== 'component-vulnerabilities-results') return;
                document.body.removeEventListener('htmx:afterSettle', settled);
                window.__refreshSettled = true;
            };
            document.body.addEventListener('htmx:afterSettle', settled);
            document.body.dispatchEvent(new CustomEvent('refresh-assessments'));
        }"""
    )
    page.wait_for_function("window.__refreshSettled === true")

    expect(detail).to_be_visible()
    expect(detail).to_have_value("Not reachable from any entry point")


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 390])
def test_component_upload_previews_and_applies_vex(authenticated_page, sbom_with_findings, mocker, width):
    """Import decisions from the component's upload dialog without replacing the scanned artifact."""
    import json

    from django.urls import reverse
    from playwright.sync_api import expect

    from sbomify.apps.sboms.models import SBOM

    upload = mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_sbom", return_value="uploaded-vex.json")
    mocker.patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply")
    sbom = sbom_with_findings
    original_filename = sbom.sbom_filename
    document = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "Example", "version": "1.0"}},
            "vulnerabilities": [
                {
                    "id": "CVE-2024-0001",
                    "analysis": {"state": "not_affected", "justification": "code_not_reachable"},
                    "affects": [{"ref": "pkg:pypi/requests@2.31.0"}],
                }
            ],
        }
    ).encode()
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(reverse("core:component_details", args=[sbom.component_id]) + "#upload-sbom")
    dialog = page.get_by_role("dialog", name="Upload Artifact", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_label("Artifact type", exact=True).select_option("vex")
    with page.expect_response(lambda response: response.url.endswith("/vex-preview")) as preview:
        dialog.locator('input[type="file"]').set_input_files(
            {
                "name": "decisions.vex.json",
                "mimeType": "application/json",
                "buffer": document,
            }
        )
    assert preview.value.status == 200
    assert preview.value.json()["would_suppress"] == 1
    expect(dialog.get_by_text("Preview: nothing stored yet")).to_be_visible()
    assert not SBOM.objects.filter(component_id=sbom.component_id, bom_type="vex").exists()
    upload.assert_not_called()
    with page.expect_response(lambda response: "/upload-file/" in response.url) as applied:
        dialog.get_by_role("button", name="Apply this VEX", exact=True).click()
    assert applied.value.status == 201
    assert SBOM.objects.filter(component_id=sbom.component_id, bom_type="vex").count() == 1
    assert upload.call_args.args[0] == document
    sbom.refresh_from_db()
    assert sbom.sbom_filename == original_filename


@pytest.fixture
def triage_lands_immediately(mocker):
    """Triage writes a VEX that can be read back, and re-annotates inline.

    Both halves matter. The decision is stored as a VEX artifact, so a panel
    that re-renders without being able to read it back would show the old state
    for a reason that has nothing to do with the refresh. And the re-annotation
    of the stored scan results runs on the queue in production, which a browser
    test has no worker for; running it inline keeps these tests about whether
    the page asks for the new rows, not about queue latency.
    """
    _patch_triage_storage(mocker)

    from sbomify.apps.vulnerability_scanning.tasks import reapply_vex_to_component_scans

    mocker.patch(
        "sbomify.apps.sboms.services.sboms.schedule_vex_reapply",
        side_effect=lambda component_id: reapply_vex_to_component_scans.fn(component_id),
    )


def _patch_triage_storage(mocker):
    """Make a stored VEX artifact readable back, without an object store.

    The re-apply's own completion broadcast is silenced too: the tests deliver
    vex_reapplied to the page themselves, exactly once, when they mean to.
    """
    mocker.patch("sbomify.apps.core.utils.broadcast_to_workspace")
    store: dict[str, bytes] = {}

    def upload(payload, *args, **kwargs):
        store["triage.json"] = payload if isinstance(payload, bytes) else str(payload).encode()
        return "triage.json"

    mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_sbom", side_effect=upload)
    mocker.patch(
        "sbomify.apps.core.object_store.StorageClient.get_sbom_data",
        side_effect=lambda filename, *args, **kwargs: store.get(filename),
    )


@pytest.fixture
def triage_reapply_stays_queued(mocker):
    """Triage stores the VEX, and the re-annotation waits to be run by hand.

    This is production's shape, which the inline fixture above deliberately
    collapses: ``schedule_vex_reapply`` enqueues, the POST returns, and the
    stored scan results are still annotated with the old verdicts. What
    replaces those rows is the ``vex_reapplied`` broadcast arriving later.

    Returns a callable that runs the queued re-annotation, so a test can hold
    the task across the immediate refresh and settle it afterwards.
    """
    _patch_triage_storage(mocker)

    queued: list[str] = []
    mocker.patch(
        "sbomify.apps.sboms.services.sboms.schedule_vex_reapply",
        side_effect=queued.append,
    )

    def run_queued() -> int:
        from sbomify.apps.vulnerability_scanning.tasks import reapply_vex_to_component_scans

        assert queued, "triage enqueued no re-annotation"
        for component_id in queued:
            reapply_vex_to_component_scans.fn(component_id)
        count = len(queued)
        queued.clear()
        return count

    return run_queued


@pytest.mark.django_db(transaction=True)
def test_a_saved_triage_shows_where_it_was_made(authenticated_page, sbom_with_findings, triage_lands_immediately):
    """A decision has to appear in the rows it was made from, without a reload.

    The modal closes on a toast that says the findings re-annotate in the
    background. If nothing then re-renders the list, the row the reader just
    triaged keeps its old state until they reload the page by hand, and the
    decision reads as though it did not take. A not_affected decision
    suppresses the finding, so here it shows as the row leaving the list.

    The reader's place is the other half: the refresh carries the filters and
    the page they are on, so answering one finding does not cost them the list
    they were working through.
    """
    from playwright.sync_api import expect

    sbom = sbom_with_findings
    _pad_findings(sbom)

    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 900})
    panel = _open_component_panel(page, sbom)
    _to_second_page_of_ten(page, panel)

    advisory = _first_advisory_on_page(panel)
    modal = _open_row_triage(page, panel, advisory)
    expect(modal).to_be_visible()
    modal.locator("#triage-state").select_option("not_affected")
    with page.expect_response(
        lambda response: response.url.endswith("/triage") and response.request.method == "POST"
    ) as response:
        modal.get_by_role("button", name="Save decision", exact=True).click()
    assert response.value.status == 200

    # The decision, in the rows it was made from, with no reload in between.
    expect(_row_menu(panel, advisory)).to_have_count(0)
    expect(panel.get_by_text("Showing 11 to 14 of 14", exact=True)).to_be_visible()
    # And still ten to a page, still on page two.
    expect(panel.locator('[aria-current="page"]')).to_have_text("2")
    expect(panel.locator("#vulnerabilities-page-size")).to_have_value("10")


@pytest.mark.django_db(transaction=True)
def test_the_broadcast_refreshes_the_panel_without_losing_the_readers_place(
    authenticated_page, sbom_with_findings, triage_reapply_stays_queued
):
    """The panel's ``@ws:message`` bridge, tested as itself.

    ``test_a_saved_triage_shows_where_it_was_made`` passes with the bridge
    deleted: it runs the re-annotation inline, so the immediate
    ``refresh-assessments`` from the save already shows the decision. The
    bridge is what carries the *later* broadcast --
    ``reapply_vex_to_component_scans`` fires ``vex_reapplied`` when the
    re-annotation lands, which in production is after the POST has returned
    and while the reader is still on the page.

    So this asserts on the refresh itself: that the broadcast causes a fetch,
    that the fetch carries the page the reader had, and that an unrelated
    component's broadcast causes nothing.
    """
    from playwright.sync_api import expect

    sbom = sbom_with_findings
    _pad_findings(sbom)

    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 900})
    panel = _open_component_panel(page, sbom)
    _to_second_page_of_ten(page, panel)

    modal = _open_row_triage(page, panel, _first_advisory_on_page(panel))
    expect(modal).to_be_visible()
    modal.locator("#triage-state").select_option("not_affected")
    with page.expect_response(
        lambda response: response.url.endswith("/triage") and response.request.method == "POST"
    ) as response:
        modal.get_by_role("button", name="Save decision", exact=True).click()
    assert response.value.status == 200
    _settled(page)

    # The queued re-annotation runs, as the worker would, after the POST.
    assert triage_reapply_stays_queued() == 1

    def _broadcast(component_id: str) -> None:
        page.evaluate(
            """(componentId) => {
                window.dispatchEvent(new CustomEvent('ws:message', {
                    detail: { type: 'vex_reapplied', component_id: componentId },
                }));
            }""",
            component_id,
        )

    # The bridge runs while the message dispatches, so its debounce state shows
    # at once whether it scheduled a refresh, with nothing to wait out.
    scheduled = (
        "(el) => { const data = window.Alpine.$data(el);"
        " return 'refreshTimer' in data ? data.refreshTimer : 'no debounce state'; }"
    )
    assert panel.evaluate(scheduled) is None

    # Another component's re-apply schedules nothing: one workspace socket
    # carries every component's broadcasts.
    _broadcast("some-other-component-id")
    assert panel.evaluate(scheduled) is None, "an unrelated component's broadcast scheduled a refresh"

    # This component's does, and when the debounce runs out the refresh asks for
    # the page the reader is on. Recorded in the page and waited on there: the
    # suite freezes the test process's clock, so a client-side wait such as
    # expect_request never times out, and a refresh that never came would hang
    # the run rather than fail it.
    page.evaluate(
        """() => {
            window.__refreshedOnPage2 = false;
            const seen = (event) => {
                if (!event.detail.requestConfig.path.includes('page=2')) return;
                document.body.removeEventListener('htmx:beforeRequest', seen);
                window.__refreshedOnPage2 = true;
            };
            document.body.addEventListener('htmx:beforeRequest', seen);
        }"""
    )
    _broadcast(str(sbom.component_id))
    page.wait_for_function("() => window.__refreshedOnPage2 === true", timeout=10_000)
    _settled(page)

    # And lands them back on it.
    expect(panel.locator('[aria-current="page"]')).to_have_text("2")
    expect(panel.locator("#vulnerabilities-page-size")).to_have_value("10")
