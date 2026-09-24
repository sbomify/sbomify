"""Narrow screens keep controls reachable without moving the whole page sideways."""

from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.vulnerability_scanning.findings import sync_findings

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


def assert_fits_width(element: Locator) -> None:
    assert element.evaluate(
        "el => { const r = el.getBoundingClientRect(); "
        "return r.left >= 0 && r.right <= document.documentElement.clientWidth; }"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_detail_layout(authenticated_page: Page, sbom_component_details: Any, width: int, theme: str) -> None:
    component = sbom_component_details
    component.name = "enterprise-gateway-" + "a" * 60
    component.save(update_fields=["name"])
    run = AssessmentRun.objects.get(sbom__component=component)
    run.result["findings"] = [
        {
            "id": f"CVE-2026-1000{index}",
            "severity": severity,
            "component": {"name": "example-package", "version": "1.0.0"},
        }
        for index, severity in enumerate(("critical", "high", "high", "medium", "medium", "medium", "low"))
    ]
    run.save(update_fields=["result"])
    sync_findings(run)
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 740})
    page.goto(f"/component/{component.id}/")
    title = page.get_by_role("heading", level=1)
    expect(title).to_contain_text(component.name)
    assert_fits_width(title)
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")
    title.get_by_role("button").click()
    assert_fits_width(title.get_by_role("textbox"))
    title.get_by_role("button", name="Cancel", exact=True).click()
    search = page.get_by_role("searchbox", name="Search vulnerabilities", exact=True)
    search.scroll_into_view_if_needed()
    assert_fits_width(search)
    for select in page.locator("#component-vulnerabilities-table select").all():
        assert_fits_width(select)
    search.fill("no-such-vulnerability")
    expect(page.locator("#component-vulnerabilities-table")).to_contain_text("No vulnerabilities")
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")
    page.goto(f"/components/{component.id}/sboms/{run.sbom_id}/")
    report_link = page.get_by_role("link", name="Vulnerabilities", exact=True)
    expect(report_link).to_be_visible()
    assert_fits_width(report_link)
    assert_fits_width(page.get_by_role("button", name="Your account", exact=True))
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")


@pytest.mark.django_db
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_chrome_and_short_screen_menu(authenticated_page: Page, theme: str) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": 320, "height": 740})
    page.goto("/dashboard")
    for name in ("Toggle sidebar navigation", "Create new item", "View notifications", "Your account"):
        button = page.get_by_role("button", name=name, exact=True)
        bounds = button.bounding_box()
        assert bounds and bounds["width"] >= 44 and bounds["height"] >= 44
        assert_fits_width(button)
    page.set_viewport_size({"width": 667, "height": 320})
    account = page.get_by_role("button", name="Your account", exact=True)
    account.click()
    menu = page.get_by_role("menu", name="User options")
    expect(menu).to_be_visible()
    assert menu.evaluate("el => el.getBoundingClientRect().bottom <= innerHeight")
    sign_out = menu.get_by_role("menuitem", name="Sign out", exact=True)
    sign_out.scroll_into_view_if_needed()
    expect(sign_out).to_be_in_viewport()
    assert sign_out.evaluate("el => el.getBoundingClientRect().bottom <= innerHeight")
    page.keyboard.press("Escape")
    expect(account).to_be_focused()


@pytest.mark.django_db
@pytest.mark.parametrize("viewport", [{"width": 320, "height": 568}, {"width": 667, "height": 320}])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_modal_actions_remain_reachable(
    authenticated_page: Page, viewport: dict[str, int], theme: str
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size(viewport)
    page.goto("/workspaces/")
    page.get_by_role("button", name="Add workspace").click()
    dialog = page.get_by_role("dialog", name="Add Workspace", exact=True)
    expect(dialog).to_be_visible()
    for control in dialog.get_by_role("button").all():
        assert_fits_width(control)
        expect(control).to_be_in_viewport()
    field = dialog.get_by_role("textbox").first
    field.fill("Mobile review workspace")
    expect(field).to_be_in_viewport()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
