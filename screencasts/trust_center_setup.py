"""Record the trust center setup screencast.

Drives: Dashboard → Settings → Trust Center tab → enable trust center →
upload a Company NDA → configure custom domain → navigate to Components →
create a component → demonstrate public / private / gated visibility.
"""

import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import Page

from conftest import (
    dismiss_toasts,
    hover_and_click,
    navigate_to_components,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_urls,
    start_on_dashboard,
    type_text,
)

# Minimal valid PDF for the fake NDA upload.
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

COMPONENT_NAME = "Compression Core Library"


# ---------------------------------------------------------------------------
# Main screencast
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def trust_center_setup(recording_page: Page) -> None:
    page = recording_page

    start_on_dashboard(page)

    # ── 1. Navigate to Settings → Trust Center tab ────────────────────────
    navigate_to_trust_center_tab(page)

    # ── 2. Enable Trust Center ────────────────────────────────────────────
    toggle = page.locator("#workspace-visibility-toggle")
    toggle.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    hover_and_click(page, toggle)

    # The form auto-submits and reloads with active_tab=trust-center
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 2000)

    # ── 3. Upload Company NDA ─────────────────────────────────────────────
    nda_label = page.locator("label[for='company_nda_file']")
    nda_label.scroll_into_view_if_needed()
    pace(page, 800)

    pdf_path = Path(tempfile.gettempdir()) / "Pied_Piper_Mutual_NDA_2025.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)

    file_input = page.locator("#company_nda_file")
    file_input.set_input_files(str(pdf_path))
    pace(page, 1000)

    upload_btn = page.locator("button:has-text('Upload NDA')")
    upload_btn.scroll_into_view_if_needed()
    pace(page, 500)
    hover_and_click(page, upload_btn)

    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    rewrite_localhost_urls(page)
    pace(page, 2000)

    pdf_path.unlink(missing_ok=True)

    # ── 4. Configure custom domain ────────────────────────────────────────
    # The custom domain section loads via HTMX after the page reload
    domain_input = page.locator("#custom-domain-input")
    domain_input.wait_for(state="visible", timeout=15_000)
    domain_input.scroll_into_view_if_needed()
    pace(page, 800)

    hover_and_click(page, domain_input)
    pace(page, 400)
    type_text(domain_input, "trust.piedpiper.com")
    pace(page, 800)

    # ── 5. Save domain ────────────────────────────────────────────────────
    save_btn = page.locator("button:has-text('Save Domain')")
    save_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    rewrite_localhost_urls(page)
    pace(page, 2000)

    # ── 6. Create a component to demonstrate visibility ───────────────────
    navigate_to_components(page)

    page.evaluate("window.dispatchEvent(new CustomEvent('open-add-component-modal'))")
    pace(page, 600)

    modal_form = page.locator("#addComponentForm")
    modal_form.wait_for(state="visible", timeout=5_000)
    pace(page, 500)

    name_input = page.locator("#componentName")
    hover_and_click(page, name_input)
    pace(page, 300)
    type_text(name_input, COMPONENT_NAME)
    pace(page, 600)

    submit_btn = modal_form.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 1000)

    # Click into the component
    row = page.locator("tr", has=page.locator(f"span:text-is('{COMPONENT_NAME}')"))
    row.first.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    hover_and_click(page, row.first)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 7. Demonstrate visibility options ─────────────────────────────────
    # Dismiss any lingering toasts so the dropdown is fully visible
    dismiss_toasts(page)

    visibility_select = page.locator("select[name='visibility']")
    visibility_select.wait_for(state="visible", timeout=10_000)
    visibility_select.scroll_into_view_if_needed()
    pace(page, 1000)

    # Set to Public
    hover_and_click(page, visibility_select)
    pace(page, 400)
    visibility_select.select_option("public")
    page.wait_for_load_state("networkidle")
    pace(page, 1000)
    dismiss_toasts(page)
    pace(page, 800)

    # Set to Gated
    hover_and_click(page, visibility_select)
    pace(page, 400)
    visibility_select.select_option("gated")
    page.wait_for_load_state("networkidle")
    pace(page, 1000)
    dismiss_toasts(page)
    pace(page, 800)

    # Set back to Private
    hover_and_click(page, visibility_select)
    pace(page, 400)
    visibility_select.select_option("private")
    page.wait_for_load_state("networkidle")
    pace(page, 1000)
    dismiss_toasts(page)
    pace(page, 2000)
