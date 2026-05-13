"""Record the VEX usage screencast.

Drives: Dashboard → Components → click into a component that has an
SBOM already attached → expand the "Upload SBOM File" card → drop a
CycloneDX VEX file → reload the page → see the new VEX badge
rendered next to the SBOM badge in the BOMs table.

Two infrastructure notes:

1. **bom_type routing.** Today the in-app uploader POSTs to
   ``/api/v1/sboms/upload-file/<id>`` without a ``bom_type`` query
   parameter, so the endpoint defaults to ``sbom``. The endpoint
   itself *does* accept ``bom_type=vex`` for CycloneDX uploads — we
   wrap ``window.fetch`` via an init script so the screencast can
   record the VEX upload flow with the existing UI. The companion
   FAQ (``how-do-i-use-vex``) keeps the API and CI examples for
   users who need to upload VEX today.
2. **S3 short-circuit.** The screencast compose stack does not run
   an S3 service, so a real upload would fail at the ``put_object``
   call. We monkeypatch ``S3Client.upload_data_as_file`` to a no-op
   for the duration of the recording so the upload-file endpoint
   succeeds end-to-end and writes the SBOM record. The recording
   then triggers an explicit ``page.reload()`` to land on the
   post-upload BOMs table — relying on the in-app
   ``sbom-uploaded`` → setTimeout → reload chain proved unreliable
   when ``window.fetch`` is wrapped above.
"""

import json

import pytest
from playwright.sync_api import Page

from conftest import (
    click_into_row,
    hover_and_click,
    navigate_to_components,
    pace,
    start_on_dashboard,
)
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team

COMPONENT_NAME = "Pied Piper Compression Core"


VEX_FILE_BYTES = json.dumps(
    {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:11111111-2222-3333-4444-555555555555",
        "version": 1,
        "metadata": {
            "timestamp": "2026-04-29T00:00:00Z",
            "component": {
                "type": "application",
                "name": "com.piedpiper/compression-core",
                "version": "2.1.0",
            },
        },
        "vulnerabilities": [
            {
                "id": "CVE-2024-12345",
                "source": {"name": "NVD"},
                "ratings": [{"severity": "high"}],
                "affects": [{"ref": "pkg:pypi/requests@2.32.3"}],
                "analysis": {
                    "state": "not_affected",
                    "justification": "code_not_reachable",
                    "detail": (
                        "We use requests only for outbound HTTPS to a fixed "
                        "allowlist of internal hosts. The vulnerable XML "
                        "parser path is never exercised."
                    ),
                },
            }
        ],
    },
    indent=2,
).encode("utf-8")


@pytest.fixture
def component_with_sbom(deletable_team: Team) -> dict:
    """Seed a component with one CycloneDX SBOM but no VEX yet.

    The screencast uploads the VEX through the UI, so the starting
    state is one BOM (the SBOM). After the upload + auto-reload, the
    BOMs table renders both rows.
    """
    component = Component.objects.create(team=deletable_team, name=COMPONENT_NAME)

    sbom = SBOM.objects.create(
        name="com.piedpiper/compression-core",
        version="2.1.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="compression-core-2.1.0.cdx.json",
        source="api",
        bom_type="sbom",
        component=component,
    )

    return {"component": component, "sbom": sbom}


def _patch_uploads_as_vex(page: Page) -> None:
    """Wrap window.fetch so upload-file requests carry bom_type=vex.

    The default endpoint behaviour is bom_type=sbom; injecting the
    query string at the fetch layer lets the recording show the VEX
    upload flow with the existing UI. We patch fetch via init script
    rather than ``page.route(continue_)`` because URL rewriting at
    the route layer leaves the FE waiting on the redirected response
    in a way that does not unblock the upload spinner.
    """
    page.add_init_script(
        """
        (() => {
            const originalFetch = window.fetch.bind(window);
            window.fetch = function patchedFetch(input, init) {
                let url = typeof input === 'string' ? input : input.url;
                if (url && url.includes('/api/v1/sboms/upload-file/') && !url.includes('bom_type=')) {
                    const sep = url.includes('?') ? '&' : '?';
                    url = url + sep + 'bom_type=vex';
                    if (typeof input === 'string') {
                        input = url;
                    } else {
                        input = new Request(url, input);
                    }
                }
                return originalFetch(input, init);
            };
        })();
        """
    )


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op the S3 put so the upload-file endpoint can succeed end-to-end.

    The test compose stack does not run an S3 service. Real uploads
    fail at the boto put_object call, the endpoint returns 400, and
    the page never reloads. Patching the upload sink lets the SBOM
    record write succeed and the front-end ``sbom-uploaded`` event
    fire, which is what the screencast needs to show.
    """
    monkeypatch.setattr(S3Client, "upload_data_as_file", lambda *args, **kwargs: None)


@pytest.mark.django_db(transaction=True)
def vex_upload(recording_page: Page, component_with_sbom: dict, s3_short_circuit: None) -> None:
    page = recording_page

    _patch_uploads_as_vex(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Components ────────────────────────────────────────
    navigate_to_components(page)

    # ── 2. Click into the seeded component ───────────────────────────────
    click_into_row(page, COMPONENT_NAME)

    # ── 3. Expand the upload card ────────────────────────────────────────
    # The "Upload SBOM File" card collapses by default when at least one
    # SBOM already exists on the component. Clicking the header expands
    # it and reveals the dropzone with the helper text mentioning every
    # BOM type the endpoint accepts.
    upload_header = page.locator("#upload-sbom button").first
    upload_header.wait_for(state="visible", timeout=15_000)
    upload_header.scroll_into_view_if_needed()
    pace(page, 1500)
    hover_and_click(page, upload_header)
    pace(page, 1500)

    # ── 4. Pause on the helper text so viewers see VEX is supported ─────
    helper_text = page.locator("#upload-sbom").locator("text=SBOM, VEX, CBOM").first
    helper_text.wait_for(state="visible", timeout=10_000)
    helper_text.scroll_into_view_if_needed()
    pace(page, 2500)

    # ── 5. Drop the VEX file into the hidden file input ─────────────────
    # The dropzone proxies to a hidden <input type="file"> via $refs.
    # Setting files on the input directly mirrors what a real drop does
    # — Alpine's @change handler runs the same upload path either way,
    # and the hidden-file approach is reliable in record mode.
    file_input = page.locator("#upload-sbom input[type='file']")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=15_000,
    ):
        file_input.set_input_files(
            files=[
                {
                    "name": "compression-core-2.1.0.vex.cdx.json",
                    "mimeType": "application/json",
                    "buffer": VEX_FILE_BYTES,
                }
            ]
        )

    # ── 6. Reload to show the new VEX in the BOMs table ─────────────────
    # The frontend is supposed to reload after a successful upload, but
    # the auto-reload listener does not fire reliably under the
    # init-script fetch wrap we use here. Force a reload so the
    # recording lands on the post-upload state without depending on the
    # toast → setTimeout chain.
    pace(page, 1500)
    page.reload()
    page.wait_for_load_state("networkidle")
    pace(page, 2500)

    # ── 7. Show the VEX badge alongside the SBOM badge ──────────────────
    vex_badge = page.locator("span.tw-badge-warning:text-is('VEX')").first
    vex_badge.wait_for(state="visible", timeout=15_000)
    vex_badge.scroll_into_view_if_needed()
    pace(page, 1500)
    vex_badge.hover()
    pace(page, 1500)

    sbom_badge = page.locator("span.tw-badge-info:text-is('SBOM')").first
    sbom_badge.wait_for(state="visible", timeout=10_000)
    sbom_badge.scroll_into_view_if_needed()
    pace(page, 400)
    sbom_badge.hover()
    pace(page, 1500)

    # ── 8. Click into the VEX detail page ────────────────────────────────
    vex_row_link = page.locator("tr", has=vex_badge).locator("a").first
    vex_row_link.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    hover_and_click(page, vex_row_link)
    page.wait_for_load_state("networkidle")
    pace(page, 2500)
