"""The first document paint must not depend on the application bundle."""

import pytest
from playwright.sync_api import Page, Route, expect

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "preference,system,effective",
    [("light", "dark", "light"), ("dark", "light", "dark"), ("system", "light", "light"), ("system", "dark", "dark")],
)
def test_theme_and_scrollbar_are_ready_before_assets(
    authenticated_page: Page, preference: str, system: str, effective: str
) -> None:
    page = authenticated_page
    page.emulate_media(color_scheme=system)
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{preference}');")
    held: list[Route] = []
    released = False

    def hold_assets(route: Route) -> None:
        if not released and route.request.resource_type in ("stylesheet", "script"):
            held.append(route)
        else:
            route.continue_()

    page.route("**/*", hold_assets)
    page.goto("/products/", wait_until="commit")
    page.wait_for_function(
        "document.documentElement.classList.contains('light') || document.documentElement.classList.contains('dark')"
    )
    initial = page.locator("html").evaluate("""root => ({
        scheme: getComputedStyle(root).colorScheme,
        gutter: getComputedStyle(root).scrollbarGutter,
        theme: root.classList.contains('light') ? 'light' : 'dark',
        transitionsDisabled: root.classList.contains('no-transitions'),
        managerLoaded: !!window.themeManager,
    })""")
    assert not initial["managerLoaded"]
    assert initial["theme"] == effective
    assert initial["scheme"] == effective
    assert initial["gutter"] == "stable"
    assert initial["transitionsDisabled"]

    released = True
    for route in held:
        route.continue_()
    page.unroute("**/*", hold_assets)
    page.wait_for_load_state("load")
    page.wait_for_function("!!window.themeManager")
    expect(page.locator("html")).to_have_css("color-scheme", effective)
    expect(page.locator("html")).to_have_css("scrollbar-gutter", "stable")
    page.wait_for_function("!document.documentElement.classList.contains('no-transitions')")
