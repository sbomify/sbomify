"""Header menus keep keyboard, theme and notification behaviour at both sizes."""

import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect


@pytest.mark.django_db
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("motion", ["reduce", "no-preference"])
def test_header_resizes_without_crowding_controls(
    authenticated_page: Page, theme: str, motion: str, tmp_path: Path
) -> None:
    page = authenticated_page
    page.emulate_media(reduced_motion=motion)
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.route("**/api/v1/notifications/", lambda route: route.fulfill(json=[]))
    page.goto("/products/")
    header = page.get_by_role("banner")
    search = header.get_by_role("combobox")

    for width in (320, 375, 639, 640, 768, 1024, 1280):
        page.set_viewport_size({"width": width, "height": 640})
        mobile = width < 640
        expect(header).to_have_css("height", "120px" if mobile else "64px")
        expect(search).to_have_css("font-size", "16px" if mobile else "14px")
        assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
        assert header.evaluate("el => el.scrollWidth <= el.clientWidth")
        assert page.locator("#main-content > div").evaluate(
            "el => el.getBoundingClientRect().top + parseFloat(getComputedStyle(el).paddingTop) "
            "- document.querySelector('[role=banner]').getBoundingClientRect().bottom"
        ) == pytest.approx(24 if mobile else 32)
        if mobile:
            controls = header.locator("button[aria-controls], a[aria-label='sbomify home']")
            boxes = controls.evaluate_all("els => els.map(el => el.getBoundingClientRect().toJSON())")
            assert len(boxes) == 5
            assert all(box["width"] >= 44 and box["height"] >= 44 for box in boxes)
            assert all(current["left"] - previous["right"] >= 4 for previous, current in zip(boxes, boxes[1:]))
            bounds = search.bounding_box()
            assert bounds is not None
            assert bounds["x"] == 16
            assert bounds["width"] == header.evaluate("el => el.clientWidth - 32")
            assert bounds["y"] >= max(box["bottom"] for box in boxes) + 8
            assert bounds["y"] + bounds["height"] <= 112
        if width in (375, 1280):
            page.screenshot(path=str(tmp_path / f"header-{theme}-{width}.png"))

    # A short phone viewport still leaves the suggested pages scrollable and reachable.
    page.set_viewport_size({"width": 320, "height": 360})
    search.focus()
    panel = page.locator("#navbar-search-dropdown")
    expect(panel.get_by_role("option", name="Products", exact=True)).to_be_visible()
    search.press("ArrowUp")
    expect(panel.get_by_role("option", name="api key", exact=True)).to_be_in_viewport(ratio=1)
    assert panel.evaluate("el => el.getBoundingClientRect().bottom <= innerHeight")
    search.press("Escape")
    expect(search).to_be_focused()
    for label, role, name in (
        ("Create new item", "menu", "Create options"),
        ("View notifications", "dialog", "Notifications"),
        ("Your account", "menu", "User options"),
    ):
        trigger = header.get_by_role("button", name=label)
        trigger.click()
        menu = page.get_by_role(role, name=name, exact=True)
        expect(menu).to_be_visible()
        assert menu.evaluate("""el => {
            const box = el.getBoundingClientRect();
            return box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight;
        }""")
        menu.press("Escape")
        expect(trigger).to_be_focused()


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
        {
            "id": "invalid-url",
            "type": "alert",
            "message": "A notification with an invalid action is still readable.",
            "severity": "info",
            "action_url": "http://[",
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
    expect(page.locator("[data-notification-count]")).to_have_text("4 new notifications")
    bell.click()
    panel = page.get_by_role("dialog", name="Notifications", exact=True)
    expect(panel).to_be_focused()
    expect(panel.get_by_role("link", name="Respond", exact=True)).to_be_visible()
    expect(panel.get_by_role("link", name="Review", exact=True)).to_be_visible()
    expect(panel.locator("li")).to_have_count(4)
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


@pytest.mark.django_db
def test_notification_refresh_ignores_an_older_response(authenticated_page: Page) -> None:
    page = authenticated_page
    page.add_init_script("""(() => {
        const originalFetch = window.fetch;
        let first = true;
        window.fetch = (input, options) => {
            if (input === '/api/v1/notifications/' && first) {
                first = false;
                return new Promise(resolve => {
                    window.finishOldNotifications = () => resolve(new Response(JSON.stringify([{
                        id: 'old', type: 'alert', message: 'Old response', severity: 'info',
                        created_at: '2020-01-01T12:00:00Z'
                    }]), {headers: {'Content-Type': 'application/json'}}));
                });
            }
            return originalFetch(input, options);
        };
    })();""")
    page.route("**/api/v1/notifications/", lambda route: route.fulfill(json=[]))
    page.goto("/dashboard")
    page.wait_for_function("typeof window.finishOldNotifications === 'function'")
    page.get_by_role("button", name="View notifications").click()
    panel = page.get_by_role("dialog", name="Notifications", exact=True)
    expect(panel.get_by_text("You're all caught up", exact=True)).to_be_visible()
    page.evaluate("async () => { window.finishOldNotifications(); await new Promise(requestAnimationFrame); }")
    expect(panel.locator("li")).to_have_count(0)
    expect(panel.get_by_text("You're all caught up", exact=True)).to_be_visible()


@pytest.mark.django_db
def test_clearing_notifications_reports_failure_and_keeps_the_list(authenticated_page: Page) -> None:
    page = authenticated_page
    records = [{
        "id": "example", "type": "alert", "message": "Example notification", "severity": "info",
        "created_at": "2020-01-01T12:00:00Z",
    }]
    page.route("**/api/v1/notifications/", lambda route: route.fulfill(json=records))
    page.route("**/api/v1/notifications/clear/", lambda route: route.fulfill(status=503))
    page.goto("/dashboard")
    page.get_by_role("button", name="View notifications").click()
    panel = page.get_by_role("dialog", name="Notifications", exact=True)
    clear = panel.get_by_role("button", name="Clear all")
    clear.click()
    expect(page.get_by_text("Could not clear notifications. Try again.", exact=True)).to_be_visible()
    expect(panel.get_by_text("Example notification", exact=True)).to_be_visible()
    expect(clear).to_be_enabled()
    expect(page.locator("[data-notification-count]")).to_have_text("1 new notification")
