"""The local sign-out landing page waits for an explicit sign-in action."""

from pathlib import Path

import pytest
from django.urls import reverse
from playwright.sync_api import Browser, expect


@pytest.mark.django_db
@pytest.mark.parametrize("width", [576, 1920])
def test_signed_out_page(browser: Browser, browser_base_url: str, width: int, tmp_path: Path) -> None:
    """The signed-out message and sign-in link remain visible after a reload."""
    context = browser.new_context(base_url=browser_base_url, viewport={"width": width, "height": 900})
    try:
        page = context.new_page()
        page.goto(reverse("core:signed_out"))
        expect(page.get_by_role("heading", name="You are signed out", exact=True)).to_be_visible()
        sign_in = page.get_by_role("link", name="Sign in", exact=True)
        expect(sign_in).to_be_visible()
        expect(sign_in).to_have_attribute("href", reverse("core:keycloak_login"))
        page.reload()
        expect(page).to_have_url(browser_base_url + reverse("core:signed_out"))
        expect(sign_in).to_be_visible()
        page.screenshot(path=tmp_path / f"signed-out-{width}.png")
    finally:
        context.close()
