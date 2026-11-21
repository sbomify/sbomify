"""Record the document upload screencast.

Drives: Dashboard → Components → Create component (New component page) →
workspace-wide Document component for a SOC 2 Type II report → Upload
document dialog: version, type, subcategory, description, file → the
document listed on the component.

Infrastructure note: the screencast stack runs no S3 service, so the
document bucket write is short-circuited (``s3_short_circuit``). Everything
above the object store, the upload endpoint and the documents table, runs for
real.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    MINIMAL_PDF,
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_components,
    pace,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.core.object_store import StorageClient

COMPONENT_NAME = "SOC 2 Type II Report"
DOCUMENT_FILENAME = "SOC2_Type_II_Audit_Report_2026.pdf"
DOCUMENT_VERSION = "2026"
DOCUMENT_DESCRIPTION = "Annual SOC 2 Type II audit covering security, availability and confidentiality"


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the document bucket write; the stack has no S3 service."""
    monkeypatch.setattr(StorageClient, "upload_document", lambda self, content: f"{DOCUMENT_FILENAME}")


@pytest.mark.django_db(transaction=True)
def document_upload(recording_page: Page, pied_piper_with_sboms: dict, s3_short_circuit: None) -> None:
    page = recording_page

    mock_vuln_trends(page)
    # The opening line plays over the dashboard and the walk to Components.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=600)

    # ── 1. A workspace-wide Document component ───────────────────────────
    navigate_to_components(page)
    narrate(page, "documents_live_component")
    hover_and_click(page, page.get_by_role("link", name="Create component").first)
    page.wait_for_url("**/components/new/**")
    page.wait_for_load_state("networkidle")

    name_input = page.locator("input#name")
    hover_and_click(page, name_input)
    type_text(name_input, COMPONENT_NAME, delay=60)
    pace(page, 300)

    narrate(page, "pick_document_type")
    hover_and_click(page, page.locator("label", has=page.locator("input[name='component_type'][value='document']")))
    is_global = page.locator("#is_global")
    is_global.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    narrate(page, "make_workspace_wide")
    hover_and_click(page, is_global)
    pace(page, 500)
    hover_and_click(page, page.get_by_role("button", name="Create component"))
    page.wait_for_url("**/component/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 400)

    # ── 2. Upload the document ────────────────────────────────────────────
    upload_btn = page.locator("#documents-table-region").get_by_role("button", name="Upload document")
    if not upload_btn.count():
        upload_btn = page.locator("#documents-table-region").get_by_role("link", name="Upload document")
    upload_btn.first.wait_for(state="visible", timeout=15_000)
    narrate(page, "component_ready_upload")
    hover_and_click(page, upload_btn.first)

    modal = page.locator("#upload-document")
    version_input = page.locator("#document-version")
    version_input.wait_for(state="visible", timeout=10_000)
    pace(page, 300)

    narrate(page, "give_version_choose")
    hover_and_click(page, version_input)
    version_input.fill("")
    type_text(version_input, DOCUMENT_VERSION, delay=90)
    pace(page, 300)

    type_select = page.locator("#document-type")
    hover_and_click(page, type_select)
    type_select.select_option("compliance")
    pace(page, 500)

    subcat_select = page.locator("#document-subcategory-compliance")
    subcat_select.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, subcat_select)
    subcat_select.select_option("soc2-type2")
    pace(page, 500)

    desc_input = page.locator("#document-description")
    hover_and_click(page, desc_input)
    type_text(desc_input, DOCUMENT_DESCRIPTION, delay=30)
    pace(page, 300)

    narrate(page, "drop_file_pdf")
    modal.locator("input[type='file']").set_input_files(
        files=[{"name": DOCUMENT_FILENAME, "mimeType": "application/pdf", "buffer": MINIMAL_PDF}]
    )
    save_btn = page.get_by_role("button", name="Save document")
    save_btn.wait_for(state="visible", timeout=5_000)
    pace(page, 800)
    with page.expect_response(
        lambda r: "/api/v1/documents" in r.url and r.request.method == "POST" and r.status in (200, 201),
        timeout=15_000,
    ):
        hover_and_click(page, save_btn)
    pace(page, 800)

    # The table normally refreshes when the upload's WebSocket broadcast
    # lands, but the recording's live server is WSGI so no socket connects.
    # Drop the #upload-artifact hash the empty-state button set, or the
    # dialog opens again on load.
    narrate(page, "report_stored_component")
    page.goto(page.url.split("#")[0])
    page.wait_for_load_state("networkidle")
    table = page.locator("#documents-table-region table")
    table.wait_for(state="visible", timeout=15_000)
    page.wait_for_load_state("networkidle")
    table.locator("tbody tr").first.hover()

    narrate(page, "show_trust_center")
