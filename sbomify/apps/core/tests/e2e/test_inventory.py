"""The inventory keeps filters, pagination and disclosures working across HTMX swaps."""

import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import Product

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_inventory_navigation_and_filters(
    authenticated_page: Page, dashboard: dict[str, Any], width: int, theme: str
) -> None:
    page = authenticated_page
    workspace = dashboard["products"][0].team
    for n in range(7):
        Product.objects.create(
            team=workspace, name="Extra " + "Long product name " * 12 if n == 0 else f"Extra Product {n}"
        )
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto("/products/")
    table = page.get_by_role("table", name="Products", exact=True)
    expect(table.locator("tbody tr")).to_have_count(10)
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    # Tab navigation is an in-place update, including the settle phase when a
    # boosted HTMX link would otherwise scroll its replacement into view.
    navigation = page.get_by_role("navigation", name="Product inventory")
    for kind in ("Releases", "Components", "Products"):
        scroll_before = page.evaluate("window.scrollY")
        navigation.get_by_role("link", name=re.compile(f"^{kind}")).click()
        expect(page.get_by_role("table", name=kind, exact=True)).to_be_visible()
        expect(page.locator("#inventory-content")).not_to_have_class(re.compile("htmx-settling"))
        assert page.evaluate("window.scrollY") == scroll_before
        assert navigation.evaluate(
            "el => { const row = el.closest('[x-data=scrollableTabs]'); "
            "return row.getBoundingClientRect().top - row.previousElementSibling.getBoundingClientRect().bottom; }"
        ) == pytest.approx(24)
        expect(navigation.get_by_role("link", name=re.compile(f"^{kind}"))).to_have_attribute("aria-current", "page")
    # Filtering and paging must retain the live controls, not recreate the page.
    filters = page.locator("#inventory-content-filters").element_handle()
    navigation_element = navigation.element_handle()
    page.get_by_role("link", name="Next page", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(2)
    expect(page).to_have_url(re.compile("page=2"))
    page.get_by_label("Rows", exact=True).select_option("25")
    expect(table.locator("tbody tr")).to_have_count(12)
    page.get_by_role("searchbox", name="Search products", exact=True).fill("Test Product 0")
    expect(table.locator("tbody tr")).to_have_count(1)
    expect(table.get_by_role("link", name="Test Product 0", exact=True)).to_be_visible()
    expect(page).to_have_url(re.compile(r"search=Test(?:%20|\+)Product(?:%20|\+)0"))
    expect(page.get_by_role("searchbox", name="Search products", exact=True)).to_be_focused()
    assert filters and filters.evaluate("el => el.isConnected")
    assert navigation_element and navigation_element.evaluate("el => el.isConnected")
    page.get_by_label("Filter by visibility").select_option("private")
    expect(table.get_by_text("No matching products")).to_be_visible()
    table.get_by_role("link", name="Clear filters").click()
    expect(table.locator("tbody tr")).to_have_count(10)
    table.get_by_role("link", name="Product", exact=True).click()
    expect(page).to_have_url(re.compile("direction=desc"))
    expect(table.locator("th").first).to_have_attribute("aria-sort", "descending")
    trigger = page.get_by_role("button", name=re.compile("Vulnerability breakdown:")).first
    trigger.click()
    panel = page.get_by_role("dialog", name="Vulnerability breakdown", exact=True)
    expect(panel).to_be_visible()
    expect(panel).to_be_focused()
    assert panel.evaluate(
        "el => el.getBoundingClientRect().left >= 0 && el.getBoundingClientRect().right <= innerWidth"
    )
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(trigger).to_be_focused()
    page.get_by_role("navigation", name="Product inventory").get_by_role("link", name=re.compile("^Components")).click()
    components = page.get_by_role("table", name="Components", exact=True)
    expect(components).to_be_visible()
    product = dashboard["products"][0]
    page.get_by_label("Filter by product").select_option(product.id)
    release_tab = page.get_by_role("navigation", name="Product inventory").get_by_role("link", name=re.compile("^Releases"))
    expect(release_tab).to_have_attribute("href", re.compile(f"product={product.id}"))
    page.get_by_label("Filter by product").select_option("unassigned")
    expect(components).to_contain_text("Unassigned")
    expect(release_tab).to_have_attribute("href", re.compile(r"[?&]product=(&|$)"))
    page.get_by_role("navigation", name="Product inventory").get_by_role("link", name=re.compile("^Releases")).click()
    expect(page.get_by_role("table", name="Releases", exact=True)).to_be_visible()
    page.get_by_role("link", name="Create release", exact=True).click()
    expect(page.get_by_role("heading", name="New release", exact=True)).to_be_visible()
    page.go_back(wait_until="networkidle")
    expect(page.get_by_role("table", name="Releases", exact=True)).to_be_visible()
    expect(page.locator("#sidebar")).to_have_count(1)
    # Browser history restores the right inventory fragment, not another app shell.
    page.go_back()
    expect(page.get_by_role("table", name="Components", exact=True)).to_be_visible()
    expect(page.locator("#inventory-content")).to_have_count(1)
    expect(page.locator("#sidebar")).to_have_count(1)
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_inventory_result_swaps_keep_sort_refresh_and_history(
    authenticated_page: Page, dashboard: dict[str, Any], kind: str
) -> None:
    page = authenticated_page
    page.goto(f"/products/?view={kind}")
    table = page.get_by_role("table", name=kind.title(), exact=True)
    search = page.get_by_role("searchbox", name=f"Search {kind}", exact=True)
    search_element = search.element_handle()
    table.locator("thead a").first.click()
    expect(table.locator("th").first).to_have_attribute("aria-sort", "descending")
    search.fill("Test")
    expect(page).to_have_url(re.compile("search=Test"))
    expect(page).to_have_url(re.compile("direction=desc"))
    expect(table.locator("th").first).to_have_attribute("aria-sort", "descending")
    assert search_element and search_element.evaluate("el => el.isConnected")
    expect(search).to_be_focused()
    filtered_url = page.url
    # The enclosing refresh URL must follow result-only navigation too.
    with page.expect_response(lambda response: response.url == filtered_url):
        page.evaluate("document.body.dispatchEvent(new Event('refresh-inventory'))")
    expect(page.locator("#inventory-content")).not_to_have_class(re.compile("htmx-settling"))
    expect(search).to_have_value("Test")
    expect(table.locator("th").first).to_have_attribute("aria-sort", "descending")
    page.go_back()
    expect(search).to_have_value("")
    expect(table.locator("th").first).to_have_attribute("aria-sort", "descending")
    page.go_forward()
    expect(search).to_have_value("Test")
    expect(table.locator("th").first).to_have_attribute("aria-sort", "descending")
    expect(page.locator("#sidebar")).to_have_count(1)
