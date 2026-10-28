"""Record the release creation screencast.

Drives: Dashboard → Products → the product → its auto-created "latest"
release → Product actions → Create release (New release page) → name,
version, description → the new release → Add Artifact → select every SBOM →
Add to Release.

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
    narrate,
    navigate_to_products,
    pace,
    settle,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)

RELEASE_NAME = "Middle-Out Rewrite"
RELEASE_VERSION = "2.0.0"
RELEASE_DESCRIPTION = "Complete rewrite of the compression engine using the middle-out algorithm"


def _type_into(page: Page, locator, text: str, delay: int = 50) -> None:
    hover_and_click(page, locator)
    type_text(locator, text, delay=delay)
    pace(page, 250)


@pytest.mark.django_db(transaction=True)
def release_creation(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page

    mock_vuln_trends(page)
    start_on_dashboard(page, pause_ms=600)
    narrate(page, "intro")
    settle(page)

    # ── 1. The product and its rolling "latest" release ──────────────────
    navigate_to_products(page)
    product_link = page.get_by_role("link", name=PIED_PIPER_PRODUCT_NAME, exact=True).first
    product_link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")

    latest = page.get_by_role("link", name="latest", exact=True).first
    latest.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, latest, 600)
    narrate(page, "every_product_has")
    settle(page)

    # ── 2. Create a release from the product's actions menu ──────────────
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 500)
    narrate(page, "version_ship_create")
    hover_and_click(page, page.get_by_role("button", name="Product actions"))
    pace(page, 400)
    hover_and_click(page, page.get_by_role("menuitem", name="Create release"))
    page.wait_for_url("**/releases/new/**")
    page.wait_for_load_state("networkidle")
    pace(page, 300)

    narrate(page, "product_already_picked")
    _type_into(page, page.locator("#release-name"), RELEASE_NAME)
    _type_into(page, page.locator("#release-version"), RELEASE_VERSION, delay=90)
    _type_into(page, page.locator("#release-description"), RELEASE_DESCRIPTION, delay=30)

    create_btn = page.get_by_role("button", name="Create release")
    smooth_scroll(page, create_btn, 300)
    hover_and_click(page, create_btn)
    page.wait_for_url("**/release/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 500)

    # ── 3. Add artifacts ──────────────────────────────────────────────────
    add_btn = page.get_by_role("button", name="Add Artifact").first
    add_btn.wait_for(state="visible", timeout=10_000)
    narrate(page, "release_starts_empty")
    hover_and_click(page, add_btn)

    page.locator("#modal-artifact-search").wait_for(state="visible", timeout=10_000)
    select_all = page.get_by_role("button", name="Select All Visible")
    select_all.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    narrate(page, "search_filter_list")
    hover_and_click(page, select_all)
    pace(page, 700)

    with page.expect_response(
        lambda r: "/releases/" in r.url and r.request.method == "POST",
        timeout=15_000,
    ):
        hover_and_click(page, page.get_by_role("button", name="Add to Release"))
    page.locator("#modal-artifact-search").wait_for(state="hidden", timeout=20_000)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)
    narrate(page, "release_holds_sbom")
    settle(page)
    pace(page, 600)
