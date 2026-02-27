"""Record the product creation screencast.

Drives: Dashboard → create 4 components → create a global SOC 2 document
component → create 2 projects (assigning components to each immediately) →
create product → assign both projects → add identifiers → add links →
edit lifecycle dates.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    click_into_row,
    hover_and_click,
    navigate_to_components,
    navigate_to_products,
    navigate_to_projects,
    pace,
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

PROJECTS = {
    "Pied Piper Frontend": ["Web Dashboard"],
    "Pied Piper Backend": ["Compression Core Library", "REST API Service", "Data Pipeline Worker"],
}

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
# Helpers — components & projects
# ---------------------------------------------------------------------------


def _create_component(page: Page, name: str) -> None:
    """Open the Add Component modal, fill the name, and submit."""
    page.evaluate("window.dispatchEvent(new CustomEvent('open-add-component-modal'))")
    pace(page, 600)

    modal_form = page.locator("#addComponentForm")
    modal_form.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    name_input = page.locator("#componentName")
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, name)
    pace(page, 500)

    submit_btn = modal_form.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 800)


def _create_document_component(page: Page, name: str) -> None:
    """Open Add Component modal, set type to Document + global, and submit."""
    page.evaluate("window.dispatchEvent(new CustomEvent('open-add-component-modal'))")
    pace(page, 600)

    modal_form = page.locator("#addComponentForm")
    modal_form.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    name_input = page.locator("#componentName")
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, name)
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

    submit_btn = modal_form.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 800)


def _create_project(page: Page, name: str) -> None:
    """Open the Add Project modal, fill the name, and submit."""
    page.evaluate("window.dispatchEvent(new CustomEvent('open-add-project-modal'))")
    pace(page, 600)

    modal_form = page.locator("#addProjectForm")
    modal_form.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    name_input = page.locator("#projectName")
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, name)
    pace(page, 500)

    submit_btn = modal_form.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 800)


def _assign_items(page: Page, names: list[str]) -> None:
    """Assign items from the Available panel by clicking their Add buttons."""
    for name in names:
        add_btn = page.locator(f"button[aria-label='Add {name} to assigned']")
        add_btn.wait_for(state="visible", timeout=10_000)
        add_btn.scroll_into_view_if_needed()
        pace(page, 300)
        hover_and_click(page, add_btn)
        pace(page, 800)


# ---------------------------------------------------------------------------
# Helpers — product details (identifiers, links, lifecycle)
# ---------------------------------------------------------------------------


def _add_identifier(page: Page, identifier_type: str, value: str) -> None:
    """Open the Add Identifier modal, fill it, and submit."""
    add_btn = page.locator("#product-identifiers-card button:has-text('Add Identifier')")
    add_btn.scroll_into_view_if_needed()
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
    pace(page, 200)
    type_text(value_input, value)
    pace(page, 400)

    submit_btn = modal.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.locator("#product-identifiers-card").wait_for(state="visible", timeout=10_000)
    pace(page, 800)


def _add_link(page: Page, link_type: str, title: str, url: str) -> None:
    """Open the Add Link modal, fill it, and submit."""
    add_btn = page.locator("#product-links-card button:has-text('Add Link')")
    add_btn.scroll_into_view_if_needed()
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
    pace(page, 200)
    type_text(title_input, title)
    pace(page, 400)

    url_input = page.locator("#add-link-url")
    hover_and_click(page, url_input)
    pace(page, 200)
    type_text(url_input, url)
    pace(page, 400)

    submit_btn = modal.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.locator("#product-links-card").wait_for(state="visible", timeout=10_000)
    pace(page, 800)


def _edit_lifecycle(page: Page) -> None:
    """Click Edit on the lifecycle card, set dates via Alpine, and save."""
    lifecycle_card = page.locator("#product-lifecycle-card")
    lifecycle_card.scroll_into_view_if_needed()
    pace(page, 400)

    edit_btn = lifecycle_card.locator("button:has-text('Edit')")
    hover_and_click(page, edit_btn)
    pace(page, 600)

    lifecycle_card.locator("form").wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    date_inputs = lifecycle_card.locator(".tw-date-input")

    for i, (binding, date_value) in enumerate(LIFECYCLE_DATES.items()):
        date_input = date_inputs.nth(i)
        date_input.scroll_into_view_if_needed()
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
    save_btn.scroll_into_view_if_needed()
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

    start_on_dashboard(page)

    # ── 1. Create Components ──────────────────────────────────────────────
    navigate_to_components(page)

    for component_name in COMPONENTS:
        _create_component(page, component_name)

    # ── 2. Create a global Document component ────────────────────────────
    _create_document_component(page, DOCUMENT_COMPONENT_NAME)

    # ── 3. Create Projects and assign components immediately ─────────────
    navigate_to_projects(page)

    for project_name, component_names in PROJECTS.items():
        _create_project(page, project_name)
        click_into_row(page, project_name)
        _assign_items(page, component_names)
        navigate_to_projects(page)

    # ── 4. Create Product ─────────────────────────────────────────────────
    navigate_to_products(page)

    page.evaluate("window.dispatchEvent(new CustomEvent('open-add-product-modal'))")
    pace(page, 600)

    modal_form = page.locator("#addProductForm")
    modal_form.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    name_input = page.locator("#productName")
    hover_and_click(page, name_input)
    pace(page, 200)
    type_text(name_input, PRODUCT_NAME)
    pace(page, 500)

    desc_input = page.locator("#productDescription")
    hover_and_click(page, desc_input)
    pace(page, 200)
    type_text(desc_input, PRODUCT_DESCRIPTION)
    pace(page, 500)

    submit_btn = modal_form.locator("button[type='submit']")
    hover_and_click(page, submit_btn)

    page.wait_for_load_state("networkidle")
    pace(page, 1000)

    # ── 5. Click into the product and assign projects ─────────────────────
    click_into_row(page, PRODUCT_NAME)

    _assign_items(page, list(PROJECTS.keys()))

    # ── 6. Add Identifiers ────────────────────────────────────────────────
    identifiers_card = page.locator("#product-identifiers-card")
    identifiers_card.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    for id_type, id_value in IDENTIFIERS:
        _add_identifier(page, id_type, id_value)

    # ── 7. Add Links ──────────────────────────────────────────────────────
    links_card = page.locator("#product-links-card")
    links_card.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    for link_type, link_title, link_url in LINKS:
        _add_link(page, link_type, link_title, link_url)

    # ── 8. Edit Lifecycle ─────────────────────────────────────────────────
    lifecycle_card = page.locator("#product-lifecycle-card")
    lifecycle_card.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    _edit_lifecycle(page)

    # Final pause to let the viewer see the completed product
    pace(page, 2000)
