"""The navigation palette keeps one selection and never scrolls the page behind it."""

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.urls import reverse
from playwright.sync_api import Page, Route, expect

from sbomify.apps.core.models import Component


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
    if dismissal == "clear":
        expect(panel.get_by_role("option", name="Products", exact=True)).to_be_visible()
        expect(panel.get_by_role("option", name="Example page 00", exact=True)).to_have_count(0)
        expect(panel).to_be_visible()
        return
    expect(panel.get_by_role("option")).to_have_count(0)
    if dismissal != "replace":
        expect(panel).to_be_hidden()
    else:
        expect(panel.get_by_text("No results", exact=True)).to_be_visible()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_focus_shows_preloaded_pages_and_search_examples(
    authenticated_page: Page, search_results: list[dict[str, Any]], width: int, theme: str, tmp_path: Path
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 750})
    requests: list[str] = []

    def respond(route: Route) -> None:
        requests.append(route.request.url)
        route.fulfill(json={"results": search_results[:1]})

    page.route("**/search/?*", respond)
    page.goto("/products/")
    search = page.get_by_role("combobox", name="Search products, components and pages")
    panel = page.locator("#navbar-search-dropdown")
    search.focus()
    expect(panel).to_be_visible()
    expect(panel.get_by_role("option", name="Products", exact=True)).to_be_visible()
    expect(panel.get_by_role("option", name="versions", exact=True)).to_be_visible()
    expect(panel.get_by_text("Searching...", exact=True)).to_be_hidden()
    expect(search).to_have_value("")
    expect(search).to_have_attribute("aria-activedescendant", "navbar-search-option-0")
    panel.screenshot(path=str(tmp_path / f"suggestions-{theme}-{width}.png"))
    assert requests == []
    search.press("Escape")
    expect(panel).to_be_hidden()
    search.click()
    expect(panel).to_be_visible()
    search.press("ArrowDown")
    expect(panel.get_by_role("option", name="Components", exact=True)).to_have_attribute("aria-selected", "true")
    search.press("Enter")
    page.wait_for_url("**/components/")
    assert requests == []

    page.keyboard.press("Control+k")
    expect(panel).to_be_visible()
    panel.get_by_role("option", name="versions", exact=True).click()
    expect(search).to_be_focused()
    expect(search).to_have_value("versions")
    expect(panel.get_by_role("option")).to_have_count(1)
    assert len(requests) == 1 and "q=versions" in requests[0]
    search.fill("")
    expect(panel.get_by_role("option", name="Products", exact=True)).to_be_visible()
    expect(panel.get_by_text("No results", exact=True)).to_be_hidden()
    assert len(requests) == 1
    search.press("ArrowUp")
    expect(panel.get_by_role("option", name="api key", exact=True)).to_have_attribute("aria-selected", "true")
    search.press("Enter")
    expect(search).to_have_value("api key")
    expect(panel.get_by_role("option")).to_have_count(1)
    assert len(requests) == 2 and "q=api+key" in requests[1]


@pytest.mark.django_db
def test_empty_workspace_dashboard_initializes_search(authenticated_page: Page) -> None:
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("/dashboard")
    expect(page.get_by_role("heading", name="Set up your first repository")).to_be_visible()
    search = page.get_by_role("combobox", name="Search products, components and pages")
    panel = page.locator("#navbar-search-dropdown")
    expect(panel).to_be_hidden()
    search.focus()
    expect(panel.get_by_role("option", name="Products", exact=True)).to_be_visible()
    search.press("Escape")
    expect(panel).to_be_hidden()
    page.get_by_role("tab", name="Terminal", exact=True).click()
    expect(page.locator("#repository-setup-command")).to_be_visible()
    assert errors == []


@pytest.mark.django_db
def test_an_upload_action_leads_to_the_next_step(authenticated_page: Page) -> None:
    """Typing what to upload and pressing Enter lands on a page that says what to do next,
    not on a list with no upload control."""
    page = authenticated_page
    page.goto("/products/")
    search = page.get_by_role("combobox", name="Search products, components and pages")
    panel = page.locator("#navbar-search-dropdown")
    search.focus()
    search.fill("vex")
    expect(panel.get_by_role("option").first).to_contain_text("Upload VEX")
    search.press("Enter")
    page.wait_for_url(re.compile(r"/upload/\?type=vex$"))
    expect(page.get_by_role("heading", name="Upload VEX", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="No components yet", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="New component", exact=True)).to_be_visible()


@pytest.mark.django_db
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 375])
def test_the_upload_picker_filters_and_opens_the_dialog(
    authenticated_page: Page, component_factory: Callable[..., Component], theme: str, width: int
) -> None:
    payments = component_factory("Payments service")
    component_factory("Ledger")
    component_factory("Policies", Component.ComponentType.DOCUMENT)
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(reverse("core:artifact_upload") + "?type=sbom")
    table = page.get_by_role("table", name="Components")
    expect(table.get_by_role("link")).to_have_count(2)
    expect(table).not_to_contain_text("Policies")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if shots := os.environ.get("UPLOAD_PICKER_SHOTS"):
        page.screenshot(path=f"{shots}/upload-picker-{theme}-{width}.png", full_page=True)
    search = page.get_by_role("searchbox", name="Filter components")
    expect(search).to_be_focused()
    search.fill("zzz")
    expect(page.get_by_role("heading", name="No components match", exact=True)).to_be_visible()
    search.fill("pay")
    expect(table.get_by_role("link")).to_have_count(1)
    expect(page.get_by_text("1 component", exact=True)).to_be_visible()
    search.press("Enter")
    page.wait_for_url(re.compile(re.escape(reverse("core:component_details", args=[payments.pk])) + "#upload-sbom$"))
    expect(page.get_by_role("dialog", name=re.compile(r"^Upload"))).to_be_visible()


@pytest.mark.django_db
def test_a_single_candidate_opens_its_dialog_directly(
    authenticated_page: Page, component_factory: Callable[..., Component]
) -> None:
    only = component_factory("Only component")
    page = authenticated_page
    page.goto(reverse("core:artifact_upload") + "?type=sbom")
    page.wait_for_url(re.compile(re.escape(reverse("core:component_details", args=[only.pk])) + "#upload-sbom$"))
    expect(page.get_by_role("dialog", name=re.compile(r"^Upload"))).to_be_visible()
