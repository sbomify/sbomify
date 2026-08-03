"""Record the release creation screencast.

Drives: Dashboard → navigate to product → view auto-created "latest" release →
create a new release → fill details → navigate to the new release →
add artifacts via the Add Artifact modal.

Prerequisite: uses the pied_piper_with_sboms ORM fixture which creates the full
Pied Piper hierarchy (product with components) with CycloneDX SBOMs.
The SBOM creation signal auto-creates a "latest" Release on the product.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    hover_and_click,
    mock_vuln_trends,
    navigate_to_products,
    pace,
    start_on_dashboard,
    type_text,
)

RELEASE_NAME = "Middle-Out Rewrite"
RELEASE_VERSION = "2.0.0"
RELEASE_DESCRIPTION = "Complete rewrite of the compression engine using the middle-out algorithm"


# ---------------------------------------------------------------------------
# Main screencast
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def release_creation(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page

    mock_vuln_trends(page)
    start_on_dashboard(page)

    # ── 1. Navigate to the product ────────────────────────────────────────
    navigate_to_products(page)

    # Wait for the products table to load via HTMX, then click the product link
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 2. Show the Latest releases card ──────────────────────────────────
    # The "latest" release was auto-created by the SBOM signal.
    releases_heading = page.locator("h4:has-text('Latest releases')").first
    releases_heading.wait_for(state="visible", timeout=15_000)
    releases_heading.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 1000)
    page.locator("text=latest").first.wait_for(state="visible", timeout=15_000)
    pace(page, 800)

    # ── 3. Create a new release from the header's ⋮ menu ─────────────────
    # The page-level Create Release button moved into the meatball menu.
    more_actions = page.get_by_role("button", name="More actions")
    more_actions.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, more_actions)
    pace(page, 600)
    hover_and_click(page, page.get_by_role("menuitem", name="Create release"))
    pace(page, 600)

    # Wait for the modal to appear
    modal_title = page.locator("text=Create New Release")
    modal_title.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    # Fill release name
    name_input = page.locator("input[placeholder*='January Release']")
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, RELEASE_NAME)
    pace(page, 500)

    # Fill version
    version_input = page.locator("input[placeholder*='v1.0.0']")
    hover_and_click(page, version_input)
    pace(page, 200)
    type_text(version_input, RELEASE_VERSION)
    pace(page, 500)

    # Fill description
    desc_input = page.locator("textarea[x-model='form.description']")
    hover_and_click(page, desc_input)
    pace(page, 200)
    type_text(desc_input, RELEASE_DESCRIPTION)
    pace(page, 500)

    # Click "Create" button in the modal footer (exact match to avoid other create buttons)
    submit_btn = page.get_by_role("button", name="Create", exact=True)
    with page.expect_response(
        lambda r: "/api/v1/releases" in r.url and r.request.method == "POST" and r.status in (200, 201),
        timeout=10_000,
    ):
        hover_and_click(page, submit_btn)
    pace(page, 800)

    # The page normally refreshes when the release_created WebSocket
    # broadcast lands, but the recording's live server is WSGI so no
    # socket ever connects — reload explicitly instead.
    page.reload()
    page.wait_for_load_state("networkidle")
    pace(page, 1200)

    # ── 4. Click into the new release ─────────────────────────────────────
    release_link = page.locator(f"a:has-text('{RELEASE_NAME}')").first
    release_link.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    hover_and_click(page, release_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 5. Add artifacts to the release ───────────────────────────────────
    add_artifact_btn = page.locator("button:has-text('Add Artifact')").first
    add_artifact_btn.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    hover_and_click(page, add_artifact_btn)

    # Wait for the modal and the available artifacts to load
    modal_header = page.locator("text=Add Artifact to Release")
    modal_header.wait_for(state="visible", timeout=10_000)
    pace(page, 1000)

    # Wait for artifacts table to populate (Alpine loads them via API)
    page.locator("#modal-artifact-search").wait_for(state="visible", timeout=10_000)
    pace(page, 1000)

    # Click "Select All Visible" to select all available SBOMs
    select_all_btn = page.locator("button:has-text('Select All Visible')")
    select_all_btn.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, select_all_btn)
    pace(page, 800)

    # Click "Add to Release"
    add_to_release_btn = page.locator("button:has-text('Add to Release')")
    hover_and_click(page, add_to_release_btn)

    # Wait for the modal to close and artifacts to appear in the release
    page.wait_for_load_state("networkidle")
    pace(page, 2000)
