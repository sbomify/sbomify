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
    hover_and_click,
    mock_vuln_trends,
    navigate_to_components,
    pace,
    start_on_dashboard,
    type_text,
)

COMPONENT_NAME = "SOC 2 Type II Compliance"
DOCUMENT_VERSION = "2024"
DOCUMENT_DESCRIPTION = "Annual SOC 2 Type II audit report covering security, availability, and confidentiality controls"

# Minimal valid PDF so the upload looks realistic.
MINIMAL_PDF = (
    b"%PDF-1.0\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF\n"
)


def _create_global_document_component(page: Page) -> None:
    """Open Add Component modal, set type to Document + global, and submit."""
    page.evaluate("window.dispatchEvent(new CustomEvent('open-add-component-modal'))")
    pace(page, 600)

    modal_form = page.locator("#addComponentForm")
    modal_form.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    # Fill name
    name_input = page.locator("#componentName")
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, COMPONENT_NAME)
    pace(page, 500)

    # Select Document type
    type_select = page.locator("#componentType")
    hover_and_click(page, type_select)
    pace(page, 200)
    type_select.select_option("document")
    pace(page, 600)

    # Check "Workspace-wide component"
    global_checkbox = page.locator("#componentIsGlobal")
    hover_and_click(page, global_checkbox)
    pace(page, 600)

    # Submit
    submit_btn = modal_form.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 1000)


def _click_into_component(page: Page, name: str) -> None:
    """Click a table row containing the given component name."""
    row = page.locator("tr", has=page.locator(f"span:text-is('{name}')"))
    row.first.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    hover_and_click(page, row.first)
    page.wait_for_load_state("networkidle")
    pace(page, 1000)


def _upload_document(page: Page, pdf_path: str) -> None:
    """Fill the upload form and submit."""
    # Fill version
    version_input = page.locator("#document-version")
    version_input.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, version_input)
    pace(page, 200)
    type_text(version_input, DOCUMENT_VERSION)
    pace(page, 500)

    # Select Document Type: Compliance
    type_select = page.locator("#document-type")
    type_select.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, type_select)
    pace(page, 200)
    type_select.select_option("compliance")
    pace(page, 600)

    # Select Compliance Subcategory: SOC 2
    subcat_select = page.locator("select[name='compliance_subcategory']")
    subcat_select.wait_for(state="visible", timeout=5_000)
    subcat_select.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, subcat_select)
    pace(page, 200)
    subcat_select.select_option("soc2")
    pace(page, 600)

    # Fill description
    desc_input = page.locator("#document-description")
    desc_input.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, desc_input)
    pace(page, 200)
    type_text(desc_input, DOCUMENT_DESCRIPTION, delay=40)
    pace(page, 500)

    # Upload file via the hidden input
    file_input = page.locator("input[type='file']")
    file_input.set_input_files(pdf_path)
    pace(page, 800)

    # Click "Save Document"
    save_btn = page.locator("button:has-text('Save Document')")
    save_btn.wait_for(state="visible", timeout=5_000)
    save_btn.scroll_into_view_if_needed()
    pace(page, 400)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 1500)


@pytest.mark.django_db(transaction=True)
def document_upload(recording_page: Page) -> None:
    page = recording_page

    mock_vuln_trends(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Components ───────────────────────────────────────
    navigate_to_components(page)

    # ── 2. Create a global Document component ───────────────────────────
    _create_global_document_component(page)

    # ── 3. Click into the component ─────────────────────────────────────
    _click_into_component(page, COMPONENT_NAME)

    # ── 4. Upload SOC 2 compliance document ─────────────────────────────
    pdf_path = Path(tempfile.gettempdir()) / "SOC2_Type_II_Audit_Report_2024.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)

    _upload_document(page, str(pdf_path))

    # Clean up temp file
    pdf_path.unlink(missing_ok=True)

    # Final pause to show the completed upload
    pace(page, 2000)
