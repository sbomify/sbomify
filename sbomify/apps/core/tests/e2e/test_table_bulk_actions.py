"""Drive the gallery's bulk delete table: select, confirm, post, in a real browser."""

from pathlib import Path

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.test_design_system_view import _debug_urlconf_fixture

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("debug_gallery")]
debug_gallery = _debug_urlconf_fixture(True)


def _open_demo(page: Page):
    page.goto(reverse("core:design_system"))
    shell = page.locator("[x-data='tableSelection']").filter(has=page.locator("#ds-bulk-search"))
    shell.scroll_into_view_if_needed()
    return shell


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_bulk_delete_is_confirmed_before_it_posts(authenticated_page: Page, theme: str, tmp_path: Path) -> None:
    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    shell = _open_demo(page)
    bar = shell.locator("[data-bulk-bar]")
    select_all = shell.get_by_role("checkbox", name="Select all components")

    expect(bar).to_be_hidden()

    shell.get_by_role("checkbox", name="Select acme-gateway-core").click()
    expect(bar).to_be_visible()
    expect(bar).to_contain_text("1 component selected")
    assert select_all.evaluate("el => el.indeterminate")
    expect(select_all).not_to_be_checked()

    # Shift-click selects the run since the last row clicked.
    shell.get_by_role("checkbox", name="Select acme-billing-service").click(modifiers=["Shift"])
    expect(bar).to_contain_text("4 components selected")
    expect(shell.get_by_role("checkbox", name="Select acme-vault-core")).to_be_checked()
    page.screenshot(path=str(tmp_path / f"bulk-selected-{theme}.png"))

    # Select all skips the disabled row, and then reads as checked.
    select_all.click()
    expect(bar).to_contain_text("7 components selected")
    expect(select_all).to_be_checked()
    assert not select_all.evaluate("el => el.indeterminate")
    expect(shell.get_by_role("checkbox", name="Select acme-audit-log")).not_to_be_checked()

    bar.get_by_role("button", name="Delete").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Delete 7 components?")
    expect(dialog.locator("li").filter(has_text="acme-gateway-core")).to_be_visible()
    expect(dialog).to_contain_text("and 2 more")
    page.screenshot(path=str(tmp_path / f"bulk-confirm-{theme}.png"))

    # Cancelling posts nothing and keeps the selection.
    posts: list[str] = []
    page.on("request", lambda request: posts.append(request.post_data or "") if request.method == "POST" else None)
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    assert posts == []
    expect(bar).to_contain_text("7 components selected")

    bar.get_by_role("button", name="Delete").click()
    with page.expect_response(lambda response: response.request.method == "POST") as response_info:
        dialog.get_by_role("button", name="Delete 7 components").click()
    response = response_info.value
    assert response.ok
    assert response.request.post_data.count("ids=") == 7
    assert "demo-bulk-5" not in response.request.post_data
    expect(dialog).to_be_hidden()
    expect(bar).to_be_hidden()
    expect(select_all).not_to_be_checked()


def test_selectable_table_stacks_on_a_phone(authenticated_page: Page, tmp_path: Path) -> None:
    page = authenticated_page
    page.set_viewport_size({"width": 375, "height": 800})
    shell = _open_demo(page)
    select_all = shell.get_by_role("checkbox", name="Select all components")
    expect(select_all).to_be_visible()
    box = shell.get_by_role("checkbox", name="Select acme-gateway-core")
    box.click()
    expect(shell.locator("[data-bulk-bar]")).to_contain_text("1 component selected")
    # The box sits beside the row's name rather than above it.
    name = shell.locator("td", has_text="acme-gateway-core").last
    box_top = box.bounding_box()["y"]
    name_box = name.bounding_box()
    assert abs(box_top - name_box["y"]) < name_box["height"]
    assert shell.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    page.screenshot(path=str(tmp_path / "bulk-phone.png"))


def test_rows_hidden_by_search_leave_the_selection(authenticated_page: Page) -> None:
    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 900})
    shell = _open_demo(page)
    bar = shell.locator("[data-bulk-bar]")
    shell.get_by_role("checkbox", name="Select all components").click()
    expect(bar).to_contain_text("7 components selected")

    page.locator("#ds-bulk-search").fill("gateway")
    expect(bar).to_contain_text("2 components selected")
    page.locator("#ds-bulk-search").fill("")
    # Clearing the search shows the rows again but does not reselect them.
    expect(bar).to_contain_text("2 components selected")


def test_rows_hidden_by_a_class_or_an_ancestor_leave_the_selection(authenticated_page: Page) -> None:
    page = authenticated_page
    shell = _open_demo(page)
    bar = shell.locator("[data-bulk-bar]")
    shell.get_by_role("checkbox", name="Select all components").click()
    expect(bar).to_contain_text("7 components selected")

    shell.locator("tr", has_text="acme-vault-core").evaluate("row => row.classList.add('hidden')")
    expect(bar).to_contain_text("6 components selected")
    shell.locator("tr", has_text="acme-billing-service").evaluate("row => row.setAttribute('hidden', '')")
    expect(bar).to_contain_text("5 components selected")

    # A hidden ancestor outside the observed table is caught when the dialog opens.
    shell.locator("tbody").evaluate(
        "body => { const wrap = body.closest('[data-table-viewport]'); wrap.style.cssText = 'display: none'; }"
    )
    bar.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("alertdialog")).to_be_hidden()
    expect(bar).to_be_hidden()


def test_the_dialog_closes_when_its_rows_disappear(authenticated_page: Page) -> None:
    page = authenticated_page
    shell = _open_demo(page)
    bar = shell.locator("[data-bulk-bar]")
    shell.get_by_role("checkbox", name="Select acme-gateway-core").click()
    shell.get_by_role("checkbox", name="Select acme-vault-core").click()
    bar.get_by_role("button", name="Delete").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Delete 2 components?")

    posts: list[str] = []
    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
    shell.locator("tr", has_text="acme-vault-core").evaluate("row => row.remove()")
    expect(dialog).to_be_hidden()
    expect(bar).to_contain_text("1 component selected")
    assert posts == []
