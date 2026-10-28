"""Record the navbar search (spotlight) screencast.

Drives: Dashboard → Ctrl+K opens the search palette with suggested pages →
arrow keys and Enter jump to a page → search "api key" lands on the API
tokens tab → search an asset by name and open the component.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    caption,
    clear_caption,
    hover_and_click,
    mock_vuln_trends,
    pace,
    start_on_dashboard,
    type_text,
)


def _open_palette(page: Page) -> None:
    page.keyboard.press("Control+k")
    page.locator("#navbar-search-dropdown").wait_for(state="visible", timeout=5_000)


def _option(page: Page, name: str):
    return page.locator("#navbar-search-list").get_by_role("option", name=name, exact=True)


@pytest.mark.django_db(transaction=True)
def spotlight_search(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page
    mock_vuln_trends(page)

    start_on_dashboard(page, pause_ms=800)
    caption(page, "Here is how to get around sbomify with search. It finds pages, actions and your own products.")

    # ── Open with the keyboard shortcut ──────────────────────────────────
    caption(page, "Press Control K, or Command K on a Mac, to open search from any page.", block=False)
    search = page.locator("#navbar-search-input")
    search_box = search.bounding_box()
    if search_box:
        page.mouse.move(search_box["x"] + search_box["width"] - 30, search_box["y"] + search_box["height"] / 2)
    pace(page, 1200)
    _open_palette(page)
    pace(page, 1000)
    caption(page, "Before you type, it suggests common pages and example searches.")

    # ── Jump with the arrow keys ─────────────────────────────────────────
    caption(page, "Use the arrow keys to pick one, and Enter to open it.", block=False)
    pace(page, 1200)
    page.keyboard.press("ArrowDown")
    caption(page, "Components is selected, so Enter opens the component list.")
    page.keyboard.press("Enter")
    page.wait_for_url(lambda url: "/components" in url, timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)

    # ── Search by what you mean ──────────────────────────────────────────
    _open_palette(page)
    caption(page, "Search also knows other words for things. Type api key, and it finds API tokens.", block=False)
    type_text(search, "api key", delay=120)
    tokens = _option(page, "API tokens")
    tokens.wait_for(state="visible", timeout=10_000)
    caption(page, "Click a result to open it.", block=False)
    hover_and_click(page, tokens)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="API tokens").first.wait_for(state="visible", timeout=10_000)
    pace(page, 800)
    caption(page, "That opened the API tokens tab in Settings.")

    # ── Find an asset by name ────────────────────────────────────────────
    _open_palette(page)
    caption(page, "It also finds your products and components by name.", block=False)
    type_text(search, "web dash", delay=120)
    asset = _option(page, "Web Dashboard")
    asset.wait_for(state="visible", timeout=10_000)
    caption(page, "Web Dashboard shows up under Products and components.")
    clear_caption(page)
    hover_and_click(page, asset)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Web Dashboard").first.wait_for(state="visible", timeout=10_000)
    pace(page, 800)
    caption(page, "One search, and you are on the component page.")
    pace(page, 600)
