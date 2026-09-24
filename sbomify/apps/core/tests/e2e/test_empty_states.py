import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.utils import (
    assert_screenshot,
    get_or_create_baseline_screenshot,
    take_screenshot,
)


pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


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


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_empty_inventory_creation_link(authenticated_page: Page, kind: str) -> None:
    from django.urls import reverse

    page = authenticated_page
    page.goto(f"/products/?view={kind}")
    panel = page.locator("[data-empty-state]").filter(
        has=page.get_by_role("heading", name=f"No {kind} yet", exact=True)
    )
    action = panel.get_by_role("link", name=f"Create {kind[:-1]}", exact=True)
    destination = reverse(f"core:{kind[:-1]}_new")
    expect(action).to_have_attribute("href", destination)
    action.click()
    expect(page).to_have_url(re.compile(re.escape(destination) + "$"))
    expect(page.get_by_role("heading", level=1)).to_be_visible()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [375, 1920])
def test_empty_product_assignment(authenticated_page: Page, empty_product_details: Any, width: int) -> None:
    page = authenticated_page
    product = empty_product_details
    page.set_viewport_size({"width": width, "height": 1080})
    page.goto(f"/product/{product.id}/")
    page.locator("#product-components [data-empty-state]").get_by_role("button", name="Assign component").click()
    dialog = page.get_by_role("dialog", name="Assign component", exact=True)
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["bom", "document"])
@pytest.mark.parametrize("width", [375, 1920])
def test_empty_component_upload_action(authenticated_page: Page, component_factory: Any, kind: str, width: int) -> None:
    component = component_factory(name="Empty upload component", component_type=kind)
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 1080})
    page.goto(f"/component/{component.id}/")
    title = "No artifacts yet" if kind == "bom" else "No documents yet"
    label = "Upload artifact" if kind == "bom" else "Upload document"
    panel = page.locator("[data-empty-state]").filter(has=page.get_by_role("heading", name=title, exact=True))
    panel.get_by_role("link", name=label, exact=True).click()
    expect(page.get_by_role("dialog", name=re.compile(label, re.IGNORECASE))).to_be_visible()
    page.keyboard.press("Escape")
    panel.get_by_role("link", name=label, exact=True).click()
    expect(page.get_by_role("dialog", name=re.compile(label, re.IGNORECASE))).to_be_visible()
