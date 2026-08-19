"""Record the VEX usage screencast.

Drives: Dashboard → Components → click into a component that has an
SBOM already attached → open Upload artifact from the header's ⋮ menu →
pick the VEX artifact type → drop a CycloneDX VEX file → watch the
dry-run preview → apply it → reload → see the row land in the
component's VEX Documents card.

Infrastructure note: the screencast compose stack does not run an S3
service, so a real upload would fail at the ``put_object`` call. We
monkeypatch ``S3Client.upload_data_as_file`` to a no-op for the
duration of the recording so the upload-file endpoint succeeds
end-to-end and writes the SBOM record; the recording then reloads
explicitly to land on the post-upload state.
"""

import json

import pytest
from playwright.sync_api import Page

from conftest import (
    click_into_row,
    hover_and_click,
    narrate,
    navigate_to_components,
    pace,
    settle,
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

    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=400)

    # ── 1. Navigate to Components ────────────────────────────────────────
    narrate(page, "why_vex")
    navigate_to_components(page)

    # ── 2. Click into the seeded component ───────────────────────────────
    narrate(page, "component")
    click_into_row(page, COMPONENT_NAME)

    # ── 3. Open the upload modal from the header's ⋮ menu ────────────────
    # Uploading moved off the page body into a modal behind the component
    # header's meatball menu, so the dropzone does not exist on screen
    # until "Upload artifact…" is picked.
    narrate(page, "upload_menu")
    more_actions = page.get_by_role("button", name="Component actions")
    more_actions.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    hover_and_click(page, more_actions)
    pace(page, 600)
    hover_and_click(page, page.get_by_role("menuitem", name="Upload artifact"))
    pace(page, 1000)

    # ── 4. Pick the VEX artifact type ────────────────────────────────────
    narrate(page, "pick_type")
    type_select = page.locator("#upload-bom-type")
    type_select.wait_for(state="visible", timeout=10_000)
    pace(page, 1000)
    type_select.select_option("vex")
    pace(page, 1200)

    # ── 5. Drop the VEX file; a dry-run preview shows what would change ──
    # The dropzone proxies to a hidden <input type="file"> via $refs.
    # Setting files on the input directly mirrors what a real drop does.
    # A VEX file gets a dry-run preview before anything is stored — the
    # counts card is the feature the FAQ wants on screen.
    narrate(page, "preview")
    file_input = page.locator("#upload-sbom input[type='file']")
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
    page.locator("text=nothing stored yet").first.wait_for(state="visible", timeout=10_000)
    narrate(page, "preview_detail")
    settle(page)

    # ── 5b. Apply it for real ────────────────────────────────────────────
    narrate(page, "apply")
    apply_btn = page.locator("button:has-text('Apply this VEX')")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=15_000,
    ):
        hover_and_click(page, apply_btn)

    # ── 6. Reload to show the new VEX document ───────────────────────────
    # An explicit reload lands on the post-upload state without depending
    # on the toast → setTimeout → reload chain.
    pace(page, 1500)
    page.reload()
    page.wait_for_load_state("networkidle")
    pace(page, 2500)

    # ── 7. Show the VEX row in the Artifacts & security table ────────────
    # VEX artifacts are rows of the unified artifacts table (Type column,
    # violet badge), latest-per-type on the component card.
    heading = page.locator("h4:has-text('artifacts')").first
    heading.wait_for(state="visible", timeout=15_000)
    heading.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 1500)

    # The type badge is one c-badges.dynamic whose colour comes from a
    # data-variant the row's Alpine binds, so there is no per-colour class to
    # match on any more.
    vex_badge = page.locator("span[data-variant='violet']:text-is('VEX')").first
    vex_badge.wait_for(state="visible", timeout=15_000)
    vex_badge.hover()
    pace(page, 2000)

    # ── 8. Click through to the VEX artifact page ────────────────────────
    narrate(page, "outro")
    vex_row_link = page.locator("tr:has(span[data-variant='violet']) a").first
    hover_and_click(page, vex_row_link)
    page.wait_for_load_state("networkidle")
    settle(page)
