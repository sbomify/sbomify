import re

import pytest
from playwright.sync_api import Page, Route, expect


@pytest.mark.django_db
@pytest.mark.parametrize("collapsed", [False, True])
@pytest.mark.parametrize("viewport_width", [1920, 375])
def test_sidebar_initial_render(authenticated_page: Page, collapsed: bool, viewport_width: int) -> None:
    """The fixed desktop rail ignores old saved widths, even before Alpine loads."""
    page = authenticated_page
    page.set_viewport_size({"width": viewport_width, "height": 1080})
    page.add_init_script(
        "if (localStorage.getItem('sidebar-collapsed') === null) {"
        f"localStorage.setItem('sidebar-collapsed', '{str(collapsed).lower()}');"
        "}"
    )

    def block_scripts(route: Route) -> None:
        if route.request.resource_type == "script":
            route.abort()
        else:
            route.continue_()

    page.route("**/*", block_scripts)
    expected_width = 240
    expected_offset = expected_width if viewport_width == 1920 else 0
    for path, label in [("/products/", "Products"), ("/components/", "Components"), ("/releases/", "Releases")]:
        page.goto(path)
        expect(page.locator("body")).to_have_css("opacity", "1")
        expect(page.locator("#sidebar")).to_have_css("width", f"{expected_width}px")
        expect(page.locator("header[role=banner]")).to_have_css("left", f"{expected_offset}px")
        expect(page.locator("#main-content")).to_have_css("padding-left", f"{expected_offset}px")
        expect(page.locator("#sidebar nav a:visible")).to_have_count(7 if viewport_width == 1920 else 0)
        expect(page.locator("#sidebar nav a[aria-current=page]")).to_have_attribute("aria-label", label)
        product_label = page.locator("#sidebar nav a").filter(has_text="Products").locator("span")
        if viewport_width != 1920:
            expect(product_label).to_be_hidden()
        else:
            expect(product_label).to_be_visible()
        sidebar_box = page.locator("#sidebar").bounding_box()
        if viewport_width == 1920:
            assert sidebar_box is not None and sidebar_box["x"] == 0
        else:
            expect(page.locator("#sidebar")).to_be_hidden()

    initial_sidebar = page.locator("#sidebar").screenshot() if viewport_width == 1920 else None
    page.unroute("**/*", block_scripts)
    page.reload()
    expect(page.locator("#sidebar [x-cloak]")).to_have_count(0)
    expect(page.locator("#sidebar")).to_have_css("width", f"{expected_width}px")
    if viewport_width == 1920:
        assert page.locator("#sidebar").screenshot() == initial_sidebar
        page.get_by_role("link", name="Products", exact=True).click()
        expect(page.locator("#sidebar")).to_have_css("width", "240px")
    else:
        page.get_by_role("button", name="Toggle sidebar navigation").click()
        expect(page.locator("#sidebar")).to_have_css("translate", "0px")

    for label in ("Releases", "Components", "Products"):
        sidebar = page.locator("#sidebar")
        expect(sidebar.locator("[x-cloak]")).to_have_count(0)
        if viewport_width != 1920 and not sidebar.is_visible():
            page.get_by_role("button", name="Toggle sidebar navigation").click()
        sidebar.get_by_role("link", name=label, exact=True).click()
        expect(page).to_have_url(re.compile(f"/{label.lower()}/$"))
        expect(sidebar.locator("[aria-current=page]")).to_have_attribute("aria-label", label)
        if viewport_width != 1920:
            expect(sidebar).to_be_hidden()
