"""Overflow navigation, quiet copy feedback and full-page release creation."""

import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_tabs_arrows_scroll_and_reveal_selected_tab(
    authenticated_page: Page, team_with_business_plan: Any, theme: str
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"/workspaces/{team_with_business_plan.key}/settings/general")
    row = page.locator('[x-ref="scroller"]')
    left = page.get_by_role("button", name="Scroll tabs left")
    right = page.get_by_role("button", name="Scroll tabs right")
    expect(left).to_be_disabled()
    expect(right).to_be_enabled()
    assert row.evaluate("el => getComputedStyle(el).scrollbarWidth") == "none"
    before = page.locator("#main-content").evaluate("el => el.scrollTop")
    right.click()
    expect(left).to_be_enabled()
    assert row.evaluate("el => el.scrollLeft") > 0
    assert page.locator("#main-content").evaluate("el => el.scrollTop") == before
    expect(page).to_have_url(re.compile("/settings/general$"))
    # Native scrolling remains available alongside the arrows.
    row.evaluate("el => el.scrollLeft = el.scrollWidth")
    expect(right).to_be_disabled()
    account = page.get_by_role("navigation", name="Settings sections").get_by_role("link", name="Account", exact=True)
    account.click()
    expect(account).to_have_attribute("aria-current", "page")
    expect(account).to_be_in_viewport(ratio=1)
    page.set_viewport_size({"width": 1280, "height": 900})
    expect(right).to_be_hidden()
    page.set_viewport_size({"width": 320, "height": 740})
    expect(account).to_be_in_viewport(ratio=1)
    # Allow the responsive layout to settle after the viewport changes.
    page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth", timeout=5000)


@pytest.mark.django_db
@pytest.mark.parametrize("width", [320, 1280])
def test_copy_field_preserves_long_value_and_quiet_feedback(
    authenticated_page: Page, team_with_business_plan: Any, width: int
) -> None:
    workspace = team_with_business_plan
    workspace.is_public = True
    workspace.save(update_fields=["is_public"])
    page = authenticated_page
    page.add_init_script("""window.copiedValues = [];
        Object.defineProperty(navigator, 'clipboard', {value: {
            writeText: async value => { window.copiedValues.push(value); }
        }});""")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/workspaces/{workspace.key}/settings/trust-center")
    field = page.get_by_role("textbox", name="public URL", exact=True)
    value = field.input_value()
    button = field.locator("..").get_by_role("button")
    bounds = button.bounding_box()
    assert bounds is not None
    background = button.evaluate("el => getComputedStyle(el).backgroundColor")
    button.press("Enter")
    expect(button).to_have_attribute("data-copied", "true")
    assert page.evaluate("window.copiedValues") == [value]
    copied_bounds = button.bounding_box()
    assert copied_bounds is not None and copied_bounds["width"] == bounds["width"]
    assert button.evaluate("el => getComputedStyle(el).backgroundColor") == background
    assert field.evaluate("el => el.getBoundingClientRect().right <= document.documentElement.clientWidth")
    expect(field).to_have_value(value)
    field.click()
    assert field.evaluate("el => el.selectionEnd - el.selectionStart") == len(value)
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")


@pytest.mark.django_db
@pytest.mark.parametrize("width", [390, 1280])
def test_product_filters_share_a_row_when_space_allows(authenticated_page: Page, dashboard: Any, width: int) -> None:
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/dashboard")
    sidebar = page.get_by_role("navigation", name="Primary navigation", include_hidden=True)
    original = sidebar.text_content()
    page.goto("/compliance/cra/")
    assert sidebar.text_content() == original
    page.goto("/products/")
    risk = page.get_by_label("Filter by risk").bounding_box()
    visibility = page.get_by_label("Filter by visibility").bounding_box()
    assert risk is not None and visibility is not None
    assert risk["y"] == pytest.approx(visibility["y"])
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")
    page.get_by_role("button", name="Create new item", exact=True).click()
    page.get_by_role("menuitem", name="Add release", exact=True).click()
    expect(page.get_by_role("heading", name="New release", exact=True)).to_be_visible()
    assert page.get_by_label("Product", exact=False).count() > 0


@pytest.mark.django_db
@pytest.mark.parametrize("width", [375, 1280])
def test_new_release_page_snapshot(authenticated_page: Page, dashboard: Any, snapshot: Any, width: int) -> None:
    authenticated_page.goto("/releases/new/")
    authenticated_page.wait_for_load_state("networkidle")
    baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
    current = snapshot.take_screenshot(authenticated_page, width=width)
    snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
