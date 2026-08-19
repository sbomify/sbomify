"""Record the document upload screencast.

Drives: Dashboard → create a global Document component for SOC 2 Type II →
upload a compliance document → set version, type, subcategory, description →
show the uploaded document in the table.
"""

import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import Page

from conftest import (
    MINIMAL_PDF,
    create_global_document_component,
    hover_and_click,
    install_dict_backed_s3,
    narrate,
    navigate_to_components,
    pace,
    settle,
    start_on_dashboard,
    type_text,
)

COMPONENT_NAME = "SOC 2 Type II Compliance"
DOCUMENT_FILENAME = "SOC2_Type_II_Audit_Report_2024.pdf"
# The API stores the filename with its extension stripped.
DOCUMENT_NAME = DOCUMENT_FILENAME.rsplit(".", 1)[0]
DOCUMENT_VERSION = "2024"
DOCUMENT_DESCRIPTION = "Annual SOC 2 Type II audit report covering security, availability, and confidentiality controls"


def _upload_document(page: Page, pdf_path: str) -> None:
    """Fill the upload form and submit."""
    # Fill version
    narrate(page, "version")
    version_input = page.locator("#document-version")
    version_input.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, version_input)
    # Alpine seeds this box with "1.0", and typing appends to it.
    type_text(version_input, DOCUMENT_VERSION, clear=True)
    pace(page, 300)

    # Select Document Type: Compliance
    narrate(page, "classify")
    type_select = page.locator("#document-type")
    type_select.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, type_select)
    pace(page, 200)
    type_select.select_option("compliance")
    pace(page, 600)

    # Select Compliance Subcategory: SOC 2
    subcat_select = page.locator("#document-subcategory-compliance")
    subcat_select.wait_for(state="visible", timeout=5_000)
    subcat_select.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, subcat_select)
    pace(page, 200)
    subcat_select.select_option("soc2")
    pace(page, 600)

    # Fill description
    narrate(page, "describe")
    desc_input = page.locator("#document-description")
    desc_input.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, desc_input)
    type_text(desc_input, DOCUMENT_DESCRIPTION, delay=40)
    pace(page, 300)

    # Upload file via the hidden input
    narrate(page, "upload")
    file_input = page.locator("input[type='file']")
    file_input.set_input_files(pdf_path)
    pace(page, 800)

    # Click "Save Document"
    save_btn = page.locator("button:has-text('Save Document')")
    save_btn.wait_for(state="visible", timeout=5_000)
    save_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 400)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")

    # The Documents card refreshes off a broadcast, and this environment serves
    # no websockets, so the row never arrives on its own — reload to land on
    # the post-upload state, the same fallback the other recordings use.
    pace(page, 1200)
    page.reload()
    page.wait_for_load_state("networkidle")

    # Assert the row actually lands. Without this the recording happily films
    # a stuck "Uploading and processing document…" spinner over an empty
    # Documents table and still reports a pass, which is exactly what it did.
    # The stored name is the filename with its extension stripped.
    page.locator(f"text={DOCUMENT_NAME}").first.wait_for(state="visible", timeout=15_000)
    pace(page, 1500)


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Back S3 with a dict so the document upload can succeed end-to-end.

    The screencast compose stack runs no object store, so the real
    ``upload_document`` fails with "Could not connect to the endpoint URL"
    against ``test-s3.localhost``, the API returns an error, and the card sits
    on "Uploading and processing document…" for the rest of the recording
    while the Documents table below it reads "No documents found". The
    recording still passed, because nothing asserted the row ever arrived.
    """
    install_dict_backed_s3(monkeypatch)


@pytest.mark.django_db(transaction=True)
def document_upload(recording_page: Page, s3_short_circuit: None) -> None:
    page = recording_page

    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=400)

    # ── 1. Navigate to Components ───────────────────────────────────────
    navigate_to_components(page)

    # ── 2. Create a global Document component ───────────────────────────
    narrate(page, "component")
    create_global_document_component(page, COMPONENT_NAME)

    # ── 3. The new component's own page is where creating it lands ──────
    # Creation is a page now and submits through to the created component,
    # so there is no list to come back to and no row to click.

    # ── 4. Upload SOC 2 compliance document ─────────────────────────────
    pdf_path = Path(tempfile.gettempdir()) / DOCUMENT_FILENAME
    pdf_path.write_bytes(MINIMAL_PDF)

    _upload_document(page, str(pdf_path))

    # Clean up temp file
    pdf_path.unlink(missing_ok=True)

    # Closing line plays over the finished document row.
    narrate(page, "outro")
    settle(page)
