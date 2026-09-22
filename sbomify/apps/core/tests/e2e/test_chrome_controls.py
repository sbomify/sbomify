"""Header menus keep keyboard, theme and notification behaviour at both sizes."""

import re
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chrome_menus(authenticated_page: Page, width: int, theme: str) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    records: list[dict[str, Any]] = [
        {
            "id": "invitation",
            "type": "pending_invitation",
            "message": "You have a workspace invitation.",
            "severity": "info",
            "action_url": "/teams/",
            "created_at": "2020-01-01T12:00:00Z",
        },
        {
            "id": "access",
            "type": "access_request_pending",
            "message": "A customer requested access to your Trust Center.",
            "severity": "warning",
            "action_url": "/teams/",
            "created_at": "2020-01-01T12:00:00Z",
        },
        {
            "id": "plain-text",
            "type": "alert",
            "message": "Literal <img src=x onerror=alert(1)> text",
            "severity": "error",
            "action_url": "javascript:alert(1)",
            "created_at": "2020-01-01T12:00:00Z",
        },
    ]
    failing = False

    def notifications(route: Route) -> None:
        route.fulfill(status=503 if failing else 200, json=[] if failing else records)

    def clear(route: Route) -> None:
        assert route.request.method == "POST"
        assert route.request.headers.get("x-csrftoken")
        records.clear()
        route.fulfill(json={"success": True})

    page.route("**/api/v1/notifications/", notifications)
    page.route("**/api/v1/notifications/clear/", clear)
    page.goto("/dashboard")
    account = page.get_by_role("button", name="Your account", exact=True)
    account.focus()
    page.keyboard.press("ArrowDown")
    menu = page.get_by_role("menu", name="User options")
    expect(menu.get_by_role("menuitem", name="My account settings")).to_be_focused()
    expect(menu.get_by_role("menuitem", name="API tokens")).to_have_attribute("href", re.compile("/settings/tokens$"))
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="API tokens")).to_be_focused()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(account).to_be_focused()
    account.click()
    expect(menu.get_by_role("menuitemradio", name=theme.title(), exact=True)).to_have_attribute("aria-checked", "true")
    selected_theme = "Dark" if theme == "light" else "Light"
    menu.get_by_role("menuitemradio", name=selected_theme, exact=True).click()
    expect(page.locator("html")).to_have_class(re.compile(selected_theme.lower()))
    expect(menu.get_by_role("menuitemradio", name=selected_theme, exact=True)).to_have_attribute("aria-checked", "true")
    menu.get_by_role("menuitemradio", name=theme.title(), exact=True).click()
    page.keyboard.press("Escape")

    create = page.get_by_role("button", name="Create new item")
    create.focus()
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("menuitem", name="Product", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(create).to_be_focused()

    bell = page.get_by_role("button", name="View notifications")
    expect(page.locator("#notifications-badge")).to_be_visible()
    expect(page.locator("[data-notification-count]")).to_have_text("3 new notifications")
    bell.click()
    panel = page.get_by_role("dialog", name="Notifications", exact=True)
    expect(panel).to_be_focused()
    expect(panel.get_by_role("link", name="Respond", exact=True)).to_be_visible()
    expect(panel.get_by_role("link", name="Review", exact=True)).to_be_visible()
    expect(panel.locator("li")).to_have_count(3)
    expect(panel.locator("img")).to_have_count(0)
    expect(panel.get_by_text("Literal <img src=x onerror=alert(1)> text", exact=True)).to_be_visible()
    expect(panel.get_by_role("link", name="View", exact=True)).to_have_count(0)
    assert panel.evaluate(
        "el => el.getBoundingClientRect().left >= 0 && el.getBoundingClientRect().right <= innerWidth"
    )
    panel.get_by_role("button", name="Clear all").click()
    expect(panel.get_by_text("You're all caught up", exact=True)).to_be_visible()
    expect(page.locator("#notifications-badge")).to_be_hidden()
    expect(panel.get_by_role("button", name="Clear all")).to_be_hidden()
    page.keyboard.press("Escape")
    expect(bell).to_be_focused()
    failing = True
    bell.click()
    expect(panel.get_by_text("Couldn't load notifications", exact=True)).to_be_visible()
    expect(panel.get_by_text("You're all caught up", exact=True)).to_be_hidden()
    failing = False
    panel.get_by_role("button", name="Try again").click()
    expect(panel.get_by_text("You're all caught up", exact=True)).to_be_visible()
    expect(panel.get_by_text("Couldn't load notifications", exact=True)).to_be_hidden()
    account.click()
    expect(panel).to_be_hidden()
    assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
