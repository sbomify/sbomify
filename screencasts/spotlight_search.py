"""Record the navbar search (spotlight) screencast.

Drives: Dashboard → Ctrl+K opens the search palette with suggested pages →
arrow keys and Enter jump to a page → search "api key" lands on the API
tokens tab → search an asset by name and open the component.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends,
    narrate,
    pace,
    settle,
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
    narrate(page, "intro")
    settle(page)

    # ── Open with the keyboard shortcut ──────────────────────────────────
    narrate(page, "press_control_k")
    search = page.locator("#navbar-search-input")
    search_box = search.bounding_box()
    if search_box:
        page.mouse.move(search_box["x"] + search_box["width"] - 30, search_box["y"] + search_box["height"] / 2)
    pace(page, 1200)
    _open_palette(page)
    pace(page, 1000)
    narrate(page, "before_type_suggests")
    settle(page)

    # ── Jump with the arrow keys ─────────────────────────────────────────
    narrate(page, "use_arrow_keys")
    pace(page, 1200)
    page.keyboard.press("ArrowDown")
    narrate(page, "components_selected_enter")
    settle(page)
    page.keyboard.press("Enter")
    page.wait_for_url(lambda url: "/components" in url, timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)

    # ── Search by what you mean ──────────────────────────────────────────
    _open_palette(page)
    narrate(page, "search_also_knows")
    type_text(search, "api key", delay=120)
    tokens = _option(page, "API tokens")
    tokens.wait_for(state="visible", timeout=10_000)
    narrate(page, "click_result_open")
    hover_and_click(page, tokens)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="API tokens").first.wait_for(state="visible", timeout=10_000)
    pace(page, 800)
    narrate(page, "opened_api_tokens")
    settle(page)

    # ── Find an asset by name ────────────────────────────────────────────
    _open_palette(page)
    narrate(page, "also_finds_products")
    type_text(search, "web dash", delay=120)
    asset = _option(page, "Web Dashboard")
    asset.wait_for(state="visible", timeout=10_000)
    narrate(page, "web_dashboard_shows")
    settle(page)
    hover_and_click(page, asset)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Web Dashboard").first.wait_for(state="visible", timeout=10_000)
    pace(page, 800)
    narrate(page, "one_search_component")
    settle(page)
    pace(page, 600)
