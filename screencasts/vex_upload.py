"""Record the VEX upload screencast.

Drives: Dashboard → Components → a component whose scan found a critical →
actions menu → Upload VEX → drop a CycloneDX VEX → the dry-run preview →
Apply this VEX → the critical leaves the open vulnerabilities, the version row
lists the VEX → filter to "Closed by a decision" to see it with its reason.

Infrastructure notes: the stack runs no S3, so ``upload_data_as_file`` and
``get_file_data`` are backed by a dict. The upload enqueues a re-annotation job
in production; here ``reannotate_component_runs``, the function that job calls,
runs right after the upload. The seeded scan's finding rows are projected with
``sync_findings`` as scan completion would.
"""

import json

import pytest
from django.urls import reverse
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    hover_and_click,
    narrate,
    navigate_to_components,
    pace,
    settle,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team

COMPONENT_NAME = "Pied Piper Compression Core"
CVE = "CVE-2024-12345"
OTHER_CVE = "CVE-2024-33210"

VEX_FILE_BYTES = json.dumps(
    {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:11111111-2222-3333-4444-555555555555",
        "version": 1,
        "metadata": {
            "timestamp": "2026-04-29T00:00:00Z",
            "component": {"type": "application", "name": "com.piedpiper/compression-core", "version": "2.1.0"},
        },
        "vulnerabilities": [
            {
                "id": CVE,
                "source": {"name": "NVD"},
                "ratings": [{"severity": "critical"}],
                "affects": [{"ref": "pkg:pypi/requests@2.32.3"}],
                "analysis": {
                    "state": "not_affected",
                    "justification": "code_not_reachable",
                    "detail": (
                        "We use requests only for outbound HTTPS to a fixed allowlist of internal hosts. "
                        "The vulnerable path is never exercised."
                    ),
                },
            }
        ],
    },
    indent=2,
).encode("utf-8")


@pytest.fixture
def component_with_sbom(deletable_team: Team) -> dict:
    """A component with one scanned SBOM: one critical, one medium, no VEX yet."""
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    component = Component.objects.create(team=deletable_team, name=COMPONENT_NAME)
    sbom = SBOM.objects.create(
        name="com.piedpiper/compression-core",
        version="2.1.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="compression-core-2.1.0.cdx.json",
        source="api",
        bom_type=SBOM.BomType.SBOM,
        component=component,
    )
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result={
            "findings": [
                {
                    "id": CVE,
                    "severity": "critical",
                    "title": "Server-side request forgery in requests",
                    "component": {"name": "requests", "version": "2.32.3", "purl": "pkg:pypi/requests@2.32.3"},
                },
                {
                    "id": OTHER_CVE,
                    "severity": "medium",
                    "title": "Prototype pollution in lodash",
                    "component": {"name": "lodash", "version": "4.17.20", "purl": "pkg:npm/lodash@4.17.20"},
                },
            ],
            "summary": {
                "by_severity": {"critical": 1, "high": 0, "medium": 1, "low": 0},
                "total_findings": 2,
                "suppressed_count": 0,
            },
        },
    )
    sync_findings(run, fresh=True)
    return {"component": component, "sbom": sbom}


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Back S3 with a dict so the VEX can be stored and read back."""
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: StorageClient, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: StorageClient, bucket_name: str, file_path: str) -> bytes | None:
        return store.get((bucket_name, file_path))

    monkeypatch.setattr(StorageClient, "upload_data_as_file", _put)
    monkeypatch.setattr(StorageClient, "get_file_data", _get)


@pytest.mark.django_db(transaction=True)
def vex_upload(recording_page: Page, component_with_sbom: dict, s3_short_circuit: None) -> None:
    from sbomify.apps.vulnerability_scanning.vex import reannotate_component_runs

    page = recording_page
    auto_dismiss_toasts(page)
    component = component_with_sbom["component"]
    component_url = reverse("core:component_details", kwargs={"component_id": component.id})

    start_on_dashboard(page, pause_ms=600)
    narrate(page, "intro")

    # ── 1. The component and its scan ─────────────────────────────────────
    navigate_to_components(page)
    link = page.locator("main").get_by_role("link", name=COMPONENT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    row = page.locator(f"tr:has-text('{CVE}')").first
    row.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, row, 400)
    narrate(page, "component_s_scan")
    settle(page)

    # ── 2. Upload VEX ─────────────────────────────────────────────────────
    actions = page.get_by_role("button", name="Component actions")
    narrate(page, "open_component_s")
    hover_and_click(page, actions)
    pace(page, 400)
    hover_and_click(page, page.get_by_role("menuitem", name="Upload VEX"))
    file_input = page.locator("#upload-sbom input[type='file']")
    file_input.wait_for(state="attached", timeout=10_000)
    page.get_by_text("Drop your VEX file here").first.wait_for(state="visible", timeout=10_000)
    narrate(page, "drop_cyclonedx_vex")
    pace(page, 800)
    with page.expect_response(lambda r: "/vex-preview" in r.url and r.status == 200, timeout=15_000):
        file_input.set_input_files(
            files=[
                {
                    "name": "compression-core-2.1.0.vex.cdx.json",
                    "mimeType": "application/json",
                    "buffer": VEX_FILE_BYTES,
                }
            ]
        )
    preview = page.get_by_text("Preview: nothing stored yet").first
    preview.wait_for(state="visible", timeout=10_000)
    narrate(page, "nothing_stored_yet")
    settle(page)

    # ── 3. Apply ──────────────────────────────────────────────────────────
    apply_btn = page.get_by_role("button", name="Apply this VEX")
    narrate(page, "if_looks_right")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=15_000,
    ):
        hover_and_click(page, apply_btn)
    reannotate_component_runs(component.id)
    pace(page, 800)

    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    other_row = page.locator(f"tr:has-text('{OTHER_CVE}')").first
    other_row.wait_for(state="visible", timeout=15_000)
    page.locator(f"tr:has-text('{CVE}')").first.wait_for(state="hidden", timeout=10_000)
    narrate(page, "critical_has_left")
    settle(page)

    # ── 4. Closed by a decision ───────────────────────────────────────────
    status = page.locator("main select[name='status']").first
    smooth_scroll(page, status, 300)
    narrate(page, "nothing_deleted_filter")
    hover_and_click(page, status)
    status.select_option("decided")
    page.wait_for_load_state("networkidle")
    closed = page.locator(f"tr:has-text('{CVE}')").first
    closed.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, closed, 300)
    closed.hover()
    pace(page, 1200)
