"""Record the product creation screencast.

Drives: Dashboard → Components → New component page (×2) → Products → New
product page → assign both components → Product details: lifecycle dates,
links, identifiers.
"""

import re

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    narrate,
    navigate_to_components,
    navigate_to_products,
    pace,
    rewrite_localhost_urls,
    settle,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)

COMPONENTS = ["Compression Core Library", "Web Dashboard"]

PRODUCT_NAME = "Pied Piper Compression Engine"
PRODUCT_DESCRIPTION = "Middle-out compression platform for enterprise data"

LIFECYCLE_DATES = [
    ("#date-releasedate", "2026-03-15"),
    ("#date-endofsupport", "2028-03-15"),
    ("#date-endoflife", "2029-03-15"),
]

LINKS = [
    ("website", "Pied Piper", "https://piedpiper.example.com"),
    ("repository", "Source code", "https://github.com/piedpiper/compression-engine"),
]

IDENTIFIERS = [
    ("cpe", "cpe:2.3:a:piedpiper:compression_engine:*:*:*:*:*:*:*:*"),
    ("purl", "pkg:github/piedpiper/compression-engine"),
]


def _type_into(page: Page, locator, text: str, delay: int = 50) -> None:
    hover_and_click(page, locator)
    locator.fill("")
    type_text(locator, text, delay=delay)
    pace(page, 250)


def _create_component(page: Page, name: str) -> None:
    """Open the New component page from the list and create a BOM component."""
    hover_and_click(page, page.get_by_role("link", name="Create component").first)
    page.wait_for_url("**/components/new/**")
    page.wait_for_load_state("networkidle")
    _type_into(page, page.locator("input#name"), name)
    hover_and_click(page, page.get_by_role("button", name="Create component"))
    page.wait_for_url("**/component/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 500)


def _open_detail_tab(page: Page, label: str, panel_id: str) -> None:
    tab = page.get_by_role("tab", name=label)
    hover_and_click(page, tab)
    page.locator(f"#{panel_id}").wait_for(state="visible", timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 400)


def _add_link(page: Page, link_type: str, title: str, url: str) -> None:
    card = page.locator("#product-links-card")
    hover_and_click(page, card.get_by_role("button", name="Add link").first)
    form = page.locator("#add-link-form")
    form.wait_for(state="visible", timeout=5_000)
    page.locator("#add-link-type").select_option(link_type)
    pace(page, 300)
    _type_into(page, page.locator("#add-link-title"), title)
    _type_into(page, page.locator("#add-link-url"), url, delay=35)
    hover_and_click(page, page.locator("button[type='submit'][form='add-link-form']"))
    page.locator("#product-links-card").get_by_text(title, exact=True).wait_for(state="visible", timeout=10_000)
    pace(page, 500)


def _add_identifier(page: Page, identifier_type: str, value: str) -> None:
    card = page.locator("#product-identifiers-card")
    hover_and_click(page, card.get_by_role("button", name="Add Identifier").first)
    page.locator("#add-identifier-form").wait_for(state="visible", timeout=5_000)
    page.locator("#add-identifier-type").select_option(identifier_type)
    pace(page, 300)
    _type_into(page, page.locator("#add-identifier-value"), value, delay=35)
    hover_and_click(page, page.locator("button[type='submit'][form='add-identifier-form']"))
    page.locator("#product-identifiers-card").get_by_text(value).first.wait_for(state="visible", timeout=10_000)
    pace(page, 500)


@pytest.mark.django_db(transaction=True)
def product_creation(recording_page: Page) -> None:
    page = recording_page

    # The opening line plays over the splash and the dashboard load, so the
    # video does not open on silence.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=300)
    rewrite_localhost_urls(page)

    # ── 1. Components ─────────────────────────────────────────────────────
    narrate(page, "product_built_components")
    navigate_to_components(page)
    _create_component(page, COMPONENTS[0])
    narrate(page, "name_all_component")
    navigate_to_components(page)
    _create_component(page, COMPONENTS[1])

    # ── 2. The product ────────────────────────────────────────────────────
    narrate(page, "open_products_create")
    navigate_to_products(page)
    hover_and_click(page, page.get_by_role("link", name="Create product").first)
    page.wait_for_url("**/products/new/**")
    page.wait_for_load_state("networkidle")
    narrate(page, "product_name_description")
    _type_into(page, page.locator("input#name"), PRODUCT_NAME)
    _type_into(page, page.locator("textarea[name='description']"), PRODUCT_DESCRIPTION, delay=35)
    hover_and_click(page, page.get_by_role("button", name="Create product"))
    page.wait_for_url("**/product/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 400)

    # ── 3. Assign components ──────────────────────────────────────────────
    narrate(page, "assign_components_make")
    for name in COMPONENTS:
        open_btn = page.locator("#product-components").get_by_role("button", name=re.compile(r"Assign component")).first
        open_btn.wait_for(state="visible", timeout=15_000)
        hover_and_click(page, open_btn)
        select = page.locator("#product-component-choice")
        select.wait_for(state="visible", timeout=10_000)
        pace(page, 300)
        select.select_option(label=name)
        pace(page, 400)
        hover_and_click(page, page.locator("button[type='submit'][form='assign-product-component']"))
        page.locator("#product-components").get_by_role("link", name=name, exact=True).wait_for(
            state="visible", timeout=15_000
        )
        page.wait_for_load_state("networkidle")
        pace(page, 500)

    # ── 4. Product details: lifecycle ─────────────────────────────────────
    details = page.locator("#product-details-heading")
    narrate(page, "product_details_holds")
    smooth_scroll(page, details, 600)
    lifecycle = page.locator("#product-lifecycle-card")
    lifecycle.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, lifecycle.get_by_role("button", name="Set dates"))
    pace(page, 400)
    for selector, value in LIFECYCLE_DATES:
        field = page.locator(selector)
        hover_and_click(page, field)
        field.fill(value)
        page.keyboard.press("Tab")
        pace(page, 400)
    hover_and_click(page, lifecycle.get_by_role("button", name="Save"))
    page.locator("#product-lifecycle-card").get_by_role("button", name="Edit").wait_for(state="visible", timeout=10_000)
    pace(page, 500)

    # ── 5. Links ──────────────────────────────────────────────────────────
    narrate(page, "links_point_people")
    _open_detail_tab(page, "Links", "product-links-card")
    _add_link(page, *LINKS[0])
    narrate(page, "each_link_has")
    _add_link(page, *LINKS[1])

    # ── 6. Identifiers ────────────────────────────────────────────────────
    narrate(page, "identifiers_such_cpe")
    _open_detail_tab(page, "Identifiers", "product-identifiers-card")
    _add_identifier(page, *IDENTIFIERS[0])
    narrate(page, "purl_names_package")
    _add_identifier(page, *IDENTIFIERS[1])

    narrate(page, "product_set_up")
    smooth_scroll(page, page.locator("#product-identifiers-card"), 400)
    settle(page)
    pace(page, 400)
