"""Record the artifact upload screencast.

Drives: Dashboard → search "upload sbom" → Upload SBOM page (/upload/?type=sbom)
→ filter the components → pick the component → its upload dialog opens
→ drop a CycloneDX SBOM → the page reloads on the component's artifacts.

Infrastructure note: the screencast stack runs no S3 service, so
``StorageClient.upload_data_as_file`` is a no-op for this recording. The
upload endpoint still parses the file and writes the SBOM record.
"""

import json

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends,
    narrate,
    pace,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.sboms.models import SBOM

TARGET_COMPONENT = "Web Dashboard"

SBOM_FILE_BYTES = json.dumps(
    {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:3e671687-395b-41f5-a30f-a58921a69b79",
        "version": 1,
        "metadata": {
            "timestamp": "2026-10-20T09:00:00Z",
            "component": {
                "type": "application",
                "bom-ref": "pkg:npm/%40piedpiper/web-dashboard@3.2.0",
                "name": "@piedpiper/web-dashboard",
                "version": "3.2.0",
                "purl": "pkg:npm/%40piedpiper/web-dashboard@3.2.0",
            },
        },
        "components": [
            {
                "type": "library",
                "bom-ref": "pkg:npm/react@18.3.1",
                "name": "react",
                "version": "18.3.1",
                "purl": "pkg:npm/react@18.3.1",
                "licenses": [{"license": {"id": "MIT"}}],
            },
            {
                "type": "library",
                "bom-ref": "pkg:npm/axios@1.7.7",
                "name": "axios",
                "version": "1.7.7",
                "purl": "pkg:npm/axios@1.7.7",
                "licenses": [{"license": {"id": "MIT"}}],
            },
            {
                "type": "library",
                "bom-ref": "pkg:npm/lodash@4.17.21",
                "name": "lodash",
                "version": "4.17.21",
                "purl": "pkg:npm/lodash@4.17.21",
                "licenses": [{"license": {"id": "MIT"}}],
            },
        ],
    },
    indent=2,
).encode("utf-8")


@pytest.fixture
def components_mostly_with_sboms(pied_piper_product: dict) -> dict:
    """Every Pied Piper component has an SBOM except the one we upload to."""
    for name, component in pied_piper_product["components"].items():
        if name == TARGET_COMPONENT:
            continue
        slug = name.lower().replace(" ", "-")
        SBOM.objects.create(
            name=f"com.piedpiper/{slug}",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"{slug}.cdx.json",
            source="api",
            component=component,
        )
    return pied_piper_product


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(StorageClient, "upload_data_as_file", lambda *args, **kwargs: None)


@pytest.mark.django_db(transaction=True)
def artifact_upload(recording_page: Page, components_mostly_with_sboms: dict, s3_short_circuit: None) -> None:
    page = recording_page
    mock_vuln_trends(page)

    # The opening line plays over the dashboard loading.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=800)

    # ── Search → Upload SBOM ─────────────────────────────────────────────
    search = page.locator("#navbar-search-input")
    narrate(page, "open_search_control")
    page.keyboard.press("Control+k")
    page.locator("#navbar-search-dropdown").wait_for(state="visible", timeout=5_000)
    pace(page, 500)
    type_text(search, "upload sbom", delay=110)
    option = page.locator("#navbar-search-list").get_by_role("option", name="Upload SBOM", exact=True)
    option.wait_for(state="visible", timeout=10_000)
    pace(page, 500)

    # ── Pick the component ───────────────────────────────────────────────
    narrate(page, "upload_page_lists")
    hover_and_click(page, option)
    page.wait_for_url(lambda url: "/upload/" in url, timeout=10_000)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Upload SBOM").wait_for(state="visible", timeout=10_000)
    page.locator("a[data-upload-target]").first.hover()

    narrate(page, "filter_name_pick")
    filter_input = page.locator("#upload-target-search")
    hover_and_click(page, filter_input)
    type_text(filter_input, "web", delay=140)
    pace(page, 500)
    target = page.locator("a[data-upload-target]", has_text=TARGET_COMPONENT)

    # ── Upload dialog opens on the component page ────────────────────────
    narrate(page, "component_page_opens")
    hover_and_click(page, target)
    page.wait_for_load_state("networkidle")
    dialog = page.locator("#upload-sbom")
    dialog.get_by_text("Drop your SBOM file here").wait_for(state="visible", timeout=15_000)

    narrate(page, "sbomify_takes_cyclonedx")
    dialog.get_by_text("Recommended:").hover()

    narrate(page, "drop_file_click")
    dropzone = dialog.get_by_role("button", name="Upload artifact file by dropping or clicking")
    box = dropzone.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pace(page, 800)
    with page.expect_response(
        lambda r: "/sboms/upload-file/" in r.url and r.request.method == "POST",
        timeout=20_000,
    ) as upload:
        dialog.locator("input[type='file']").set_input_files(
            files=[
                {
                    "name": "web-dashboard-3.2.0.cdx.json",
                    "mimeType": "application/json",
                    "buffer": SBOM_FILE_BYTES,
                }
            ]
        )
    assert upload.value.ok, f"upload failed: {upload.value.status}"

    # The toast says the page reloads, but in this stack the reload never
    # fires, so do it here. Without the #upload-sbom fragment, or the
    # reloaded page would open the dialog again.
    page.get_by_text("SBOM uploaded successfully").first.wait_for(state="visible", timeout=10_000)
    narrate(page, "upload_succeeded")
    page.goto(page.url.split("#")[0])
    page.wait_for_load_state("networkidle")

    version = page.get_by_text("3.2.0").first
    version.wait_for(state="visible", timeout=15_000)
    narrate(page, "sbom_stored_exactly")
    version.hover()

    narrate(page, "vulnerabilities_show_up")
