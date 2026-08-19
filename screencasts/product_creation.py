"""Record the product creation screencast.

Drives: Dashboard → create 4 components → create a global SOC 2 document
component → create product → assign all four components → add identifiers
→ add links → edit lifecycle dates.
"""

import re

import pytest
from playwright.sync_api import Page

from conftest import (
    create_global_document_component,
    hover_and_click,
    narrate,
    navigate_to_components,
    navigate_to_products,
    open_new_from_navbar,
    pace,
    settle,
    start_on_dashboard,
    type_text,
)

# ---------------------------------------------------------------------------
# Silicon Valley themed data
# ---------------------------------------------------------------------------

COMPONENTS = [
    "Compression Core Library",
    "Web Dashboard",
    "REST API Service",
    "Data Pipeline Worker",
]

DOCUMENT_COMPONENT_NAME = "SOC 2 Type II Compliance"

PRODUCT_NAME = "Pied Piper Compression Engine"
PRODUCT_DESCRIPTION = "Middle-out compression platform for enterprise data optimization"

IDENTIFIERS = [
    ("cpe", "cpe:2.3:a:piedpiper:compression_engine:*:*:*:*:*:*:*:*"),
    ("purl", "pkg:github/piedpiper/compression-engine"),
]

LINKS = [
    ("website", "Pied Piper Homepage", "https://piedpiper.com"),
    ("repository", "Source Code", "https://github.com/piedpiper/compression-engine"),
    ("documentation", "API Docs", "https://docs.piedpiper.com/api"),
]

LIFECYCLE_DATES = {
    "releaseDate": "2025-03-15",
    "endOfSupport": "2027-03-15",
    "endOfLife": "2028-03-15",
}


# ---------------------------------------------------------------------------
# Helpers — components & product
# ---------------------------------------------------------------------------


def _create_component(page: Page, name: str) -> None:
    """Create a BOM component from the New Component page.

    A submit lands on the new component's own page rather than back on the
    list, so each pass through here starts from wherever the last one ended.
    The navbar menu is reachable from all of them.
    """
    open_new_from_navbar(page, "Component")

    name_input = page.locator("input#name")
    name_input.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, name)
    pace(page, 500)

    # BOM is the default tile; naming it is genuinely all this form needs.
    hover_and_click(page, page.get_by_role("button", name="Create component"))

    page.wait_for_load_state("networkidle")
    pace(page, 800)


def _assign_items(page: Page, names: list[str]) -> None:
    """Assign components one at a time through the Assign Component modal.

    The dual-panel assignment manager is gone; the Components card now
    opens a modal with a single select and an Assign confirm. The confirm
    is matched by exact accessible name so the page's own "Assign
    component" opener cannot shadow it.
    """
    for name in names:
        # A fresh product renders the empty state's "Assign a component";
        # after the first assignment (each one reloads the page) the header's
        # "Assign component" takes over. One anchored regex covers both.
        open_btn = page.get_by_role("button", name=re.compile(r"^Assign (a )?component$"))
        open_btn.wait_for(state="visible", timeout=15_000)
        pace(page, 400)
        hover_and_click(page, open_btn)

        select = page.locator("#pc-assign-select")
        select.wait_for(state="visible", timeout=10_000)
        pace(page, 500)
        select.select_option(label=name)
        pace(page, 600)

        hover_and_click(page, page.get_by_role("button", name="Assign", exact=True))
        page.locator(f"a:has-text('{name}')").first.wait_for(state="visible", timeout=10_000)
        pace(page, 800)


def _expand_about_row(page: Page, row_label: str, card_id: str) -> None:
    """Unfold one "About this product" accordion row and wait for its panel.

    Each row lazy-loads its card via HTMX on first expand, so the card id
    does not exist in the DOM until the row has been clicked.
    """
    row = page.locator(f"button:has-text('{row_label}')").first
    row.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 400)
    hover_and_click(page, row)
    page.locator(f"#{card_id}").wait_for(state="visible", timeout=10_000)
    pace(page, 500)


# ---------------------------------------------------------------------------
# Helpers — product details (identifiers, links, lifecycle)
# ---------------------------------------------------------------------------


def _add_identifier(page: Page, identifier_type: str, value: str) -> None:
    """Open the Add Identifier modal, fill it, and submit."""
    add_btn = page.locator("#product-identifiers-card button:has-text('Add Identifier')")
    add_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, add_btn)
    pace(page, 600)

    modal = page.locator("#add-identifier-form")
    modal.wait_for(state="visible", timeout=5_000)

    type_select = page.locator("#add-identifier-type")
    hover_and_click(page, type_select)
    pace(page, 200)
    type_select.select_option(identifier_type)
    pace(page, 400)

    value_input = page.locator("#add-identifier-value")
    hover_and_click(page, value_input)
    # A CPE string is machine data, not prose — typing it at reading speed
    # just stalls the video under the narration.
    type_text(value_input, value, delay=25)
    pace(page, 300)

    # The confirm sits in the modal footer, outside the <form>, tied to it by
    # a form attribute — so it is not under the form element to be found.
    submit_btn = page.locator("button[form='add-identifier-form']")
    hover_and_click(page, submit_btn)

    page.locator("#product-identifiers-card").wait_for(state="visible", timeout=10_000)
    pace(page, 800)


def _add_link(page: Page, link_type: str, title: str, url: str) -> None:
    """Open the Add Link modal, fill it, and submit."""
    add_btn = page.locator("#product-links-card button:has-text('Add Link')")
    add_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, add_btn)
    pace(page, 600)

    modal = page.locator("#add-link-form")
    modal.wait_for(state="visible", timeout=5_000)

    type_select = page.locator("#add-link-type")
    hover_and_click(page, type_select)
    pace(page, 200)
    type_select.select_option(link_type)
    pace(page, 400)

    title_input = page.locator("#add-link-title")
    hover_and_click(page, title_input)
    type_text(title_input, title, delay=55)

    url_input = page.locator("#add-link-url")
    hover_and_click(page, url_input)
    type_text(url_input, url, delay=25)
    pace(page, 300)

    submit_btn = page.locator("button[form='add-link-form']")
    hover_and_click(page, submit_btn)

    page.locator("#product-links-card").wait_for(state="visible", timeout=10_000)
    pace(page, 800)


def _edit_lifecycle(page: Page) -> None:
    """Click Edit on the lifecycle card, set dates via Alpine, and save."""
    lifecycle_card = page.locator("#product-lifecycle-card")
    lifecycle_card.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 400)

    # The header's "Edit" button only renders once the product already has
    # lifecycle dates; a product created moments ago shows the empty state,
    # whose "Set Dates" button opens the same editor. Match either, and wait
    # for it — the row's panel is HTMX-loaded, so the card element can be
    # visible a beat before its contents arrive.
    edit_btn = lifecycle_card.locator("button:has-text('Set Dates'), button:has-text('Edit')").first
    edit_btn.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, edit_btn)
    pace(page, 600)

    lifecycle_card.locator("form").wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    date_inputs = lifecycle_card.locator(".tw-date-input")

    for i, (binding, date_value) in enumerate(LIFECYCLE_DATES.items()):
        date_input = date_inputs.nth(i)
        date_input.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
        pace(page, 300)

        hover_and_click(page, date_input)
        pace(page, 500)

        page.evaluate(
            """([binding, value]) => {
            const card = document.getElementById('product-lifecycle-card');
            const data = window.Alpine.$data(card);
            data[binding] = value;
        }""",
            [binding, date_value],
        )
        pace(page, 300)

        page.keyboard.press("Escape")
        pace(page, 400)

    save_btn = lifecycle_card.locator("button[type='submit']")
    save_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, save_btn)

    page.locator("#product-lifecycle-card").wait_for(state="visible", timeout=10_000)
    pace(page, 1000)


# ---------------------------------------------------------------------------
# Main screencast
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def product_creation(recording_page: Page) -> None:
    page = recording_page

    # Each narrate() starts a line and returns immediately, so the work below
    # it happens under the voice.  Lines sit before the action they describe.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=400)

    # ── 1. Create Components ──────────────────────────────────────────────
    narrate(page, "components_intro")
    navigate_to_components(page)

    # Repetitive loops get a line every couple of iterations rather than one
    # per iteration, so the voice keeps moving without narrating each click.
    component_beats = {
        0: "components_first",
        1: "components_rest",
        2: "components_rest_two",
        3: "components_last",
    }
    for index, component_name in enumerate(COMPONENTS):
        if beat := component_beats.get(index):
            narrate(page, beat)
        _create_component(page, component_name)

    # ── 2. Create a global Document component ────────────────────────────
    narrate(page, "document_component")
    create_global_document_component(page, DOCUMENT_COMPONENT_NAME)

    # ── 3. Create Product ─────────────────────────────────────────────────
    narrate(page, "product_intro")
    navigate_to_products(page)

    open_new_from_navbar(page, "Product")

    narrate(page, "product_name")
    name_input = page.locator("input#name")
    name_input.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, name_input)
    type_text(name_input, PRODUCT_NAME)

    narrate(page, "product_description")
    desc_input = page.locator("textarea#description")
    hover_and_click(page, desc_input)
    type_text(desc_input, PRODUCT_DESCRIPTION, delay=45)

    hover_and_click(page, page.get_by_role("button", name="Create product"))

    page.wait_for_load_state("networkidle")

    # ── 4. Assign components ─────────────────────────────────────────────
    # Creating a product lands on the product's own page now, so there is no
    # list to click back into.
    narrate(page, "assign_intro")

    _assign_items(page, COMPONENTS[:2])
    narrate(page, "assign_linkage")
    _assign_items(page, COMPONENTS[2:])

    # ── 5. Add Identifiers (inside the About accordion) ───────────────────
    narrate(page, "identifiers_intro")
    _expand_about_row(page, "Product identifiers", "product-identifiers-card")

    identifier_beats = ["identifier_cpe", "identifier_purl"]
    for beat, (id_type, id_value) in zip(identifier_beats, IDENTIFIERS):
        narrate(page, beat)
        _add_identifier(page, id_type, id_value)

    # ── 6. Add Links ──────────────────────────────────────────────────────
    narrate(page, "links_intro")
    _expand_about_row(page, "Product links", "product-links-card")

    link_beats = {1: "links_rest", 2: "links_third"}
    for index, (link_type, link_title, link_url) in enumerate(LINKS):
        if beat := link_beats.get(index):
            narrate(page, beat)
        _add_link(page, link_type, link_title, link_url)

    # ── 7. Edit Lifecycle ─────────────────────────────────────────────────
    narrate(page, "lifecycle_intro")
    _expand_about_row(page, "Lifecycle", "product-lifecycle-card")

    narrate(page, "lifecycle_why")
    _edit_lifecycle(page)

    # Closing line plays over the finished product page.
    narrate(page, "outro")
    settle(page)
