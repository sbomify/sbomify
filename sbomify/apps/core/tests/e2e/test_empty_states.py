import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.utils import (
    assert_screenshot,
    get_or_create_baseline_screenshot,
    take_screenshot,
)


@pytest.mark.django_db
@pytest.mark.parametrize("width", [375, 576, 992, 1920])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_empty_lists_share_layout(
    authenticated_page: Page, team_with_business_plan: Any, width: int, theme: str
) -> None:
    """Empty lists fill their surface, even when populated tables have wide columns."""
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 1080})
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}')")
    recipes = []
    for path, title in [
        ("/products/", "No products yet"),
        ("/security-advisories/", "No advisories yet"),
        (f"/workspaces/{team_with_business_plan.key}/vulnerability-scans/", "No scans found"),
    ]:
        page.goto(path)
        page.wait_for_load_state("networkidle")
        expect(page.locator("html")).to_have_class(re.compile(rf"\b{theme}\b"))
        panel = page.locator("[data-empty-state]").filter(has=page.get_by_role("heading", name=title, exact=True))
        expect(panel).to_be_visible()
        geometry = panel.evaluate("""el => {
            const panel = el.getBoundingClientRect();
            const surface = el.parentElement.getBoundingClientRect();
            const icon = el.firstElementChild.getBoundingClientRect();
            const style = getComputedStyle(el);
            return {
                center: panel.x + panel.width / 2,
                surfaceCenter: surface.x + surface.width / 2,
                iconCenter: icon.x + icon.width / 2,
                width: panel.width,
                surfaceWidth: surface.width,
                recipe: [style.paddingTop, style.paddingBottom, icon.width, icon.height],
                scrollWidth: document.documentElement.scrollWidth
            };
        }""")
        assert abs(geometry["center"] - geometry["surfaceCenter"]) < 2
        assert abs(geometry["iconCenter"] - geometry["surfaceCenter"]) < 2
        assert abs(geometry["width"] - geometry["surfaceWidth"]) < 3
        assert geometry["scrollWidth"] <= width
        recipes.append(geometry["recipe"])
        name = f"test_empty_list_{title.lower().replace(' ', '_')}_{theme}_{width}"
        baseline = get_or_create_baseline_screenshot(page, name, width)
        current = take_screenshot(page, name, width)
        assert_screenshot(baseline, current)
        page.set_viewport_size({"width": width, "height": 1080})
    assert recipes[0] == recipes[1] == recipes[2]
