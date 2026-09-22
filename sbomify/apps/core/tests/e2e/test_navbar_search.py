"""The navigation palette keeps one selection and never scrolls the page behind it."""

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect


@pytest.fixture
def search_results() -> list[dict[str, Any]]:
    # Deliberately interleave sections: keyboard order must follow the visible groups.
    return [
        {
            "title": f"Example {'page' if index % 2 == 0 else 'product'} {index:02}",
            "url": f"/products/?search=example-{index}",
            "section": "navigate" if index % 2 == 0 else "products",
            "section_label": "Go to" if index % 2 == 0 else "Products",
            "icon": "fa-cube",
        }
        for index in range(16)
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_search_keyboard_and_pointer(
    authenticated_page: Page, search_results: list[dict[str, Any]], width: int, theme: str, tmp_path: Path
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 360})
    page.route("**/search/?*", lambda route: route.fulfill(json={"results": search_results}))
    page.goto("/products/")
    search = page.get_by_role("combobox", name="Search products, components and pages")
    panel = page.locator("#navbar-search-dropdown")
    options = panel.get_by_role("option")
    page.keyboard.press("Control+k")
    expect(search).to_be_focused()
    search.fill("example")
    expect(options).to_have_count(16)
    expect(search).to_have_attribute("aria-expanded", "true")
    expect(search).to_have_attribute("aria-activedescendant", "navbar-search-option-0")
    expect(options.nth(0)).to_have_attribute("aria-selected", "true")
    expect(options.nth(1)).to_contain_text("Example page 02")
    assert options.nth(0).evaluate("el => getComputedStyle(el).backgroundColor") != options.nth(1).evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert panel.evaluate(
        "el => el.getBoundingClientRect().left >= 0 && el.getBoundingClientRect().right <= innerWidth"
    )

    panel.screenshot(path=str(tmp_path / f"search-{theme}-{width}.png"))
    page.evaluate("window.scrollTo(0, 100)")
    before_scroll = page.evaluate("window.scrollY")
    assert before_scroll > 0
    search.press("ArrowDown")
    expect(options.nth(1)).to_have_attribute("aria-selected", "true")
    expect(search).to_be_focused()
    search.press("ArrowUp")
    search.press("ArrowUp")
    expect(options.nth(15)).to_have_attribute("aria-selected", "true")
    expect(search).to_have_attribute("aria-activedescendant", "navbar-search-option-15")
    assert page.locator("#navbar-search-list").evaluate("el => el.scrollTop > 0")
    expect(options.nth(15)).to_be_in_viewport(ratio=1)
    assert options.nth(15).evaluate(
        "el => el.getBoundingClientRect().bottom <= "
        "document.getElementById('navbar-search-list').getBoundingClientRect().bottom"
    )
    assert page.evaluate("window.scrollY") == before_scroll
    search.press("ArrowDown")
    expect(options.nth(0)).to_have_attribute("aria-selected", "true")
    page.wait_for_function("document.getElementById('navbar-search-list').scrollTop === 0")

    options.nth(2).hover()
    expect(options.nth(2)).to_have_attribute("aria-selected", "true")
    search.press("ArrowDown")
    expect(options.nth(3)).to_have_attribute("aria-selected", "true")
    expect(panel.locator('[aria-selected="true"]')).to_have_count(1)
    search.press("Escape")
    expect(panel).to_be_hidden()
    expect(search).to_be_focused()
    expect(search).not_to_have_attribute("aria-activedescendant", "navbar-search-option-3")
    page.keyboard.press("Meta+k")
    expect(panel).to_be_visible()
    expect(search).to_be_focused()
    search.press("Tab")
    expect(panel).to_be_hidden()
    page.keyboard.press("Control+k")
    search.press("Escape")
    search.press("ArrowDown")
    expect(options.nth(0)).to_have_attribute("aria-selected", "true")
    search.press("ArrowDown")
    search.press("Enter")
    page.wait_for_url("**/products/?search=example-2")


@pytest.mark.django_db
def test_search_states_and_literal_titles(authenticated_page: Page, search_results: list[dict[str, Any]]) -> None:
    page = authenticated_page
    response: dict[str, Any] = {"results": search_results}
    status = 200

    def respond(route: Route) -> None:
        route.fulfill(status=status, json=response)

    page.route("**/search/?*", respond)
    page.goto("/products/")
    search = page.get_by_role("combobox", name="Search products, components and pages")
    panel = page.locator("#navbar-search-dropdown")
    search.fill("example")
    expect(panel.get_by_role("option")).to_have_count(16)
    status = 503
    search.fill("unavailable")
    expect(panel.get_by_text("Search is unavailable", exact=True)).to_be_visible()
    expect(panel.get_by_role("option")).to_have_count(0)
    search.press("Enter")
    expect(page).to_have_url("/products/")
    status = 200
    response = {"results": []}
    search.press("Tab")
    expect(panel.get_by_role("button", name="Try again")).to_be_focused()
    page.keyboard.press("Enter")
    expect(panel.get_by_text("No results", exact=True)).to_be_visible()
    response = {"results": [{**search_results[0], "title": 'Literal <img src=x onerror=alert(1)> "text"'}]}
    search.fill("literal")
    expect(panel.get_by_role("option")).to_have_count(1)
    expect(panel.get_by_role("option")).to_contain_text('Literal <img src=x onerror=alert(1)> "text"')
    expect(panel.locator("img")).to_have_count(0)
    status = 401
    search.fill("session expired")
    expect(panel.get_by_text("Your session has expired", exact=True)).to_be_visible()
    expect(panel.get_by_role("option")).to_have_count(0)
    search.press("Enter")
    expect(page).to_have_url("/products/")
    search.press("Tab")
    expect(panel.get_by_role("link", name="Sign in", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(search).to_be_focused()


@pytest.mark.django_db
@pytest.mark.parametrize("dismissal", ["escape", "clear", "outside", "replace"])
def test_pending_search_cannot_restore_dismissed_results(
    authenticated_page: Page, search_results: list[dict[str, Any]], dismissal: str
) -> None:
    page = authenticated_page
    pending: list[Route] = []

    def respond(route: Route) -> None:
        if "second+query" in route.request.url:
            route.fulfill(json={"results": []})
        else:
            pending.append(route)

    page.route("**/search/?*", respond)
    page.goto("/products/")
    search = page.get_by_role("combobox", name="Search products, components and pages")
    panel = page.locator("#navbar-search-dropdown")
    with page.expect_request("**/search/?*"):
        search.fill("first query")
    expect(panel.get_by_text("Searching...", exact=True)).to_be_visible()
    if dismissal == "escape":
        search.press("Escape")
    elif dismissal == "clear":
        search.fill("x")
    elif dismissal == "outside":
        page.get_by_role("button", name="Your account", exact=True).click()
    else:
        search.fill("second query")
        expect(panel.get_by_text("No results", exact=True)).to_be_visible()
    pending[0].fulfill(json={"results": search_results})
    # Allow the late response to settle; neither selection nor visibility may return.
    page.wait_for_timeout(300)
    expect(panel.get_by_role("option")).to_have_count(0)
    if dismissal != "replace":
        expect(panel).to_be_hidden()
    else:
        expect(panel.get_by_text("No results", exact=True)).to_be_visible()
