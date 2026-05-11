"""Render-based dark-mode test for the shared email template.

The static assertions in ``onboarding/tests/test_onboarding.py``
(``TestEmailBaseDarkModeDefences``) check that the rendered HTML
*contains* the dark-mode defences. Those guards are necessary but
not sufficient — they don't actually evaluate ``@media
(prefers-color-scheme: dark)``, so they can't catch:

  - A selector mistake that leaves the dark-mode block syntactically
    present but functionally inert (e.g. typo'd class name).
  - A rule that fires but resolves to the wrong logo URL.
  - A future change that swaps the SVG src attributes by accident.

This test renders ``onboarding/emails/welcome.html.j2`` through
Django, loads it into a real Chromium via Playwright's CDP fixture,
emulates each ``prefers-color-scheme`` value in turn, and asserts the
computed-style ``display`` on each ``<img>`` matches expectation. If
the wrong logo is the one rendered, the test fails — closing the
gap that surfaced the user-reported Gmail Android bug in the first
place.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Generator, Literal

import pytest
from django.template.loader import render_to_string
from playwright.sync_api import Browser, BrowserContext

ColorScheme = Literal["dark", "light", "no-preference", "null"]

EMAIL_CONTEXT = {
    "user": SimpleNamespace(first_name="Jonathan", username="jonathan"),
    "base_url": "http://localhost",
    "app_base_url": "http://localhost",
}


def _make_context(browser: Browser, color_scheme: ColorScheme) -> BrowserContext:
    """Create an isolated Chromium context with the given prefers-color-scheme."""
    return browser.new_context(
        color_scheme=color_scheme,
        viewport={"width": 800, "height": 1200},
    )


def _resolve_logo_state(context: BrowserContext, email_html: str) -> dict[str, str]:
    """Load the email into a page and return the CSS-resolved display value for each logo."""
    page = context.new_page()
    try:
        page.set_content(email_html, wait_until="domcontentloaded")
        return {
            "light_display": page.locator(".logo .logo-light").evaluate("el => getComputedStyle(el).display"),
            "dark_display": page.locator(".logo .logo-dark").evaluate("el => getComputedStyle(el).display"),
            "light_src": page.locator(".logo .logo-light").get_attribute("src") or "",
            "dark_src": page.locator(".logo .logo-dark").get_attribute("src") or "",
        }
    finally:
        page.close()


@pytest.fixture
def email_html() -> str:
    return render_to_string("onboarding/emails/welcome.html.j2", EMAIL_CONTEXT)


@pytest.fixture
def light_context(browser: Browser) -> Generator[BrowserContext, Any, None]:
    ctx = _make_context(browser, "light")
    yield ctx
    ctx.close()


@pytest.fixture
def dark_context(browser: Browser) -> Generator[BrowserContext, Any, None]:
    ctx = _make_context(browser, "dark")
    yield ctx
    ctx.close()


def test_light_mode_shows_black_wordmark(light_context: BrowserContext, email_html: str) -> None:
    """Under prefers-color-scheme: light, the black-wordmark SVG must be the visible one."""
    state = _resolve_logo_state(light_context, email_html)
    assert state["light_display"] != "none", (
        f"sbomify-black.svg should be visible in light mode, got display={state['light_display']!r}"
    )
    assert state["dark_display"] == "none", (
        f"sbomify-white.svg should be hidden in light mode, got display={state['dark_display']!r}"
    )
    assert "sbomify-black.svg" in state["light_src"]


def test_dark_mode_shows_white_wordmark(dark_context: BrowserContext, email_html: str) -> None:
    """Under prefers-color-scheme: dark, the white-wordmark SVG must be the visible one.

    This is the exact failure surfaced in the user-reported Gmail Android screenshot
    — pre-fix, the black wordmark stayed visible against the now-dark background.
    """
    state = _resolve_logo_state(dark_context, email_html)
    assert state["dark_display"] != "none", (
        f"sbomify-white.svg should be visible in dark mode, got display={state['dark_display']!r}"
    )
    assert state["light_display"] == "none", (
        f"sbomify-black.svg should be hidden in dark mode, got display={state['light_display']!r}"
    )
    assert "sbomify-white.svg" in state["dark_src"]


def test_dark_mode_container_styles_apply(dark_context: BrowserContext, email_html: str) -> None:
    """Under prefers-color-scheme: dark, the email container should resolve to the
    dark palette (not the light defaults). Guards against future regressions where
    someone removes the body / container rules from the dark-mode media block."""
    page = dark_context.new_page()
    try:
        page.set_content(email_html, wait_until="domcontentloaded")
        body_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        container_bg = page.locator(".email-container").evaluate("el => getComputedStyle(el).backgroundColor")
    finally:
        page.close()

    # Both backgrounds should be in the dark palette — emails fall back to the
    # light defaults (#f8fafc body, #ffffff container) if the dark-mode block
    # is missing. Compare against the light fallback to catch regressions.
    light_body_fallback = "rgb(248, 250, 252)"
    light_container_fallback = "rgb(255, 255, 255)"
    assert body_bg != light_body_fallback, (
        f"body background still on light fallback ({body_bg}) in dark mode — dark-mode rules missing?"
    )
    assert container_bg != light_container_fallback, (
        f"email-container still white ({container_bg}) in dark mode — dark-mode rules missing?"
    )
