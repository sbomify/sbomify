"""One message path for app, standalone and public pages, including HTMX."""

from urllib.parse import urlparse

import pytest
from django.contrib.messages import constants
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpResponse
from django.test import RequestFactory
from playwright.sync_api import Page, expect

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path", ["/dashboard", "/compliance/cra/", "/support/contact/"])
def test_flash_messages_keep_punctuation_and_render_once(
    authenticated_page: Page, browser_base_url: str, path: str
) -> None:
    message = 'Saved: example | <script>alert("example")</script>'
    storage = CookieStorage(RequestFactory().get(path))
    storage.add(constants.SUCCESS, message)
    response = HttpResponse()
    storage.update(response)
    page = authenticated_page
    page.context.add_cookies(
        [
            {
                "name": "messages",
                "value": response.cookies["messages"].value,
                "domain": urlparse(browser_base_url).hostname,
                "path": "/",
            }
        ]
    )
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(path)
    notification = page.locator("#toast-container").get_by_text(message, exact=True)
    expect(notification).to_have_count(1)
    expect(notification).to_be_visible()
    expect(page.locator("[data-django-messages]")).to_have_count(0)
    assert not errors


@pytest.mark.parametrize("width", [320, 1280])
def test_messages_after_htmx_navigation_are_single_dismissible_and_fit(authenticated_page: Page, width: int) -> None:
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/products/")
    for name in ("Components", "Releases", "Products"):
        tab = page.get_by_role("navigation", name="Product inventory").get_by_role("link", name=name)
        tab.click()
        expect(tab).to_have_attribute("aria-current", "page")
    page.evaluate("""() => document.body.dispatchEvent(new CustomEvent('messages', {
        detail: {value: [{type: 'alert-danger', message: 'Unable to save: ' + 'identifier'.repeat(60)}]}
    }))""")
    toast = page.locator("#toast-container [data-toast]")
    expect(toast).to_have_count(1)
    expect(toast).to_have_attribute("data-variant", "error")
    assert toast.evaluate("el => el.scrollWidth <= el.clientWidth")
    assert toast.evaluate(
        "el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; }"
    )
    toast.get_by_role("button", name="Dismiss", exact=True).click()
    expect(toast).to_have_count(0)
