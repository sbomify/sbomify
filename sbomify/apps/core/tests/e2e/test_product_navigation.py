"""Product composition stays interactive after server-driven filters and mutations."""

import re

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import Component, Product

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_product_tables_assignments_and_release_editor(
    authenticated_page: Page, product_details: Product, width: int, theme: str
) -> None:
    product = product_details
    for n in range(10):
        component = Component.objects.create(team=product.team, name=f"Extra component {n:02}")
        product.components.add(component)
    available = Component.objects.create(team=product.team, name="Available component")
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 1000})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"/product/{product.id}/")
    table = page.get_by_role("table", name="Components", exact=True)
    expect(table.locator("tbody tr")).to_have_count(10)
    page.get_by_role("link", name="Next page", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(2)
    page.get_by_label("Rows", exact=True).select_option("25")
    expect(table.locator("tbody tr")).to_have_count(12)
    expect(page.locator("#product-components")).not_to_have_class(re.compile("htmx-settling"))
    page.get_by_role("searchbox", name="Search components", exact=True).evaluate(
        "el => el.scrollIntoView({behavior: 'instant', block: 'center'})"
    )
    page.get_by_role("searchbox", name="Search components", exact=True).fill("Available")
    scroll_before = page.evaluate("window.scrollY")
    expect(table.get_by_text("No matching components", exact=True)).to_be_visible()
    expect(page.locator("#product-components")).not_to_have_class(re.compile("htmx-settling"))
    max_scroll = page.evaluate("Math.max(0, document.documentElement.scrollHeight - innerHeight)")
    assert page.evaluate("window.scrollY") == min(scroll_before, max_scroll)
    expect(page).to_have_url(re.compile("search=Available"))
    # Submit a dialog after an HTMX swap, then use the newly rendered menu.
    page.get_by_role("button", name="Assign component", exact=True).click()
    dialog = page.get_by_role("dialog", name="Assign component", exact=True)
    dialog.get_by_label("Component", exact=False).select_option(available.id)
    dialog.get_by_role("button", name="Assign component", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(table.get_by_role("link", name="Available component", exact=True)).to_be_visible()
    table.get_by_role("button", name="Actions for Available component", exact=True).click()
    page.get_by_role("menuitem", name="Remove from product", exact=True).click()
    removal = page.get_by_role("dialog", name="Remove component from product", exact=True)
    expect(removal).to_contain_text("Available component")
    removal.get_by_role("button", name="Remove component", exact=True).click()
    expect(removal).to_be_hidden()
    expect(table.get_by_text("No matching components", exact=True)).to_be_visible()
    assert not product.components.filter(id=available.id).exists()
    assert Component.objects.filter(id=available.id).exists()
    page.locator("summary").filter(has_text="Product links").click()
    expect(page.locator("#product-links-panel")).to_contain_text("Product Website")
    page.locator("summary").filter(has_text="Product identifiers").click()
    expect(page.locator("#product-identifiers-panel")).to_contain_text("SKU-12345")
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    page.get_by_role("link", name=re.compile("^View all ")).click()
    releases = page.get_by_role("table", name="Releases", exact=True)
    expect(releases).to_be_visible()
    page.get_by_role("link", name="Create release", exact=True).click()
    editor = page.locator("#release-create-page")
    editor.get_by_label("Release name", exact=False).fill("UI test release")
    editor.get_by_label("Version", exact=True).fill("1.2.3")
    editor.get_by_label("Description", exact=True).fill("Release editor check")
    editor.get_by_label("Mark as prerelease", exact=True).check()
    editor.get_by_role("button", name="Create release", exact=True).click()
    expect(page.get_by_role("heading", name="UI test release", exact=True)).to_be_visible()
    page.goto(f"/product/{product.id}/releases/")
    row = releases.locator("tbody tr").filter(has_text="UI test release")
    expect(row).to_contain_text("Prerelease")
    row.get_by_role("button", name="Actions for UI test release", exact=True).click()
    page.get_by_role("menuitem", name="Edit release", exact=True).click()
    editor = page.get_by_role("dialog", name="Edit release", exact=True)
    expect(editor.get_by_label("Version", exact=True)).to_have_value("1.2.3")
    editor.get_by_label("Release name", exact=False).fill("Reviewed build")
    editor.get_by_label("Version", exact=True).fill("")
    editor.get_by_label("Mark as prerelease", exact=True).uncheck()
    editor.get_by_role("button", name="Save release", exact=True).click()
    expect(editor).to_be_hidden()
    row = releases.locator("tbody tr").filter(has_text="Reviewed build")
    expect(row).to_be_visible()
    updated = product.releases.get(name="Reviewed build")
    assert not updated.is_prerelease
    assert not updated.version
    row.get_by_role("button", name="Actions for Reviewed build", exact=True).click()
    page.get_by_role("menuitem", name="Delete release", exact=True).click()
    deletion = page.get_by_role("alertdialog", name="Delete release", exact=True)
    expect(deletion).to_be_visible()
    deletion.get_by_role("button", name="Cancel", exact=True).click()
    expect(deletion).to_be_hidden()
    assert product.releases.filter(id=updated.id).exists()
    page.get_by_role("searchbox", name="Search releases", exact=True).fill("Reviewed")
    expect(releases.locator("tbody tr")).to_have_count(1)
    expect(page).to_have_url(re.compile("search=Reviewed"))
    page.go_back()
    expect(releases.get_by_role("link", name="latest", exact=True)).to_be_visible()
    expect(page.locator("#sidebar")).to_have_count(1)
    expect(page.locator("#product-releases-content")).to_have_count(1)
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    assert not errors
