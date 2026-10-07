"""Sorting keeps shared table geometry, scroll position and keyboard focus stable."""

import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from sbomify.apps.core.models import Component, Product, ReleaseArtifact
from sbomify.apps.core.tests.e2e.test_security_advisories import advisories as _advisories_fixture
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.security_advisories.models import SecurityAdvisory

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
advisories = _advisories_fixture


def geometry(table: Locator) -> list[float]:
    """Column positions, each against the reference that scrolling must not move it from.

    An ordinary column is measured against the table: it travels with the table
    when the viewport scrolls sideways, so its offset there is the invariant. A
    pinned column is measured against the scroll viewport instead, because
    holding still against the viewport while the table slides under it is the
    whole point of pinning. Measuring a pinned cell against the table would
    record the scroll offset and report a column that is working as designed as
    a column that moved.
    """
    return table.evaluate("""table => {
        const bounds = table.getBoundingClientRect();
        const viewport = (table.closest('[data-table-viewport]') || table).getBoundingClientRect();
        return [bounds.width, ...Array.from(table.querySelectorAll('th')).flatMap(cell => {
            const rect = cell.getBoundingClientRect();
            if (!rect.width) return [];
            const pinned = getComputedStyle(cell).position === 'sticky'
                && getComputedStyle(cell).right !== 'auto';
            const origin = pinned ? viewport.left : bounds.left;
            return [rect.left - origin, rect.width, rect.height];
        })];
    }""")


def reader_position(table: Locator) -> list[float]:
    return table.evaluate("""table => {
        const position = [];
        for (let node = table.parentElement; node; node = node.parentElement) {
            position.push(node.scrollLeft, node.scrollTop);
        }
        return position;
    }""")


def sort_with_keyboard(table: Locator, column: str, expected_geometry: list[float], server: bool = False) -> None:
    control = table.locator(f'[data-table-sort="{column}"]')
    # Focus may deliberately scroll the requested header into view. Sorting
    # itself must leave the reader exactly where that header was activated.
    control.focus()
    before_position = reader_position(table)
    direction = "desc" if control.get_attribute("data-sort") == "asc" else "asc"
    control.press("Enter")
    expect(control).to_have_attribute("data-sort", direction)
    if server:
        expect(table.locator("xpath=ancestor::*[contains(@class, 'htmx-settling')]")).to_have_count(0)
    expect(control).to_be_focused()
    expect(control.locator("..")).to_have_attribute("aria-sort", "ascending" if direction == "asc" else "descending")
    assert geometry(table) == pytest.approx(expected_geometry, abs=0.1)
    assert reader_position(table) == pytest.approx(before_position, abs=1)


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_inventory_sorting_preserves_columns_and_position(
    authenticated_page: Page, dashboard: dict[str, Any], width: int, theme: str
) -> None:
    page = authenticated_page
    workspace = dashboard["products"][0].team
    for index in range(12):
        Product.objects.create(
            team=workspace,
            name=f"Extra product {index:02}" if index < 11 else "Zebra " + "Long product name " * 12,
        )
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("/products/")
    table = page.get_by_role("table", name="Products", exact=True)
    expect(table.locator("tbody tr")).to_have_count(10)
    original = geometry(table)
    first_name = table.locator("tbody tr").first.locator("td").first.inner_text()
    sort_with_keyboard(table, "name", original, server=True)
    assert table.locator("tbody tr").first.locator("td").first.inner_text() != first_name
    for column in ("release_count", "vulnerabilities", "created_at", "name"):
        sort_with_keyboard(table, column, original, server=True)
        sort_with_keyboard(table, column, original, server=True)
    page.get_by_role("link", name="Next page", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(7)
    assert geometry(table) == pytest.approx(original, abs=0.1)

    for kind in ("Components", "Releases"):
        page.get_by_role("navigation", name="Product inventory").get_by_role(
            "link", name=re.compile(f"^{kind}")
        ).click()
        table = page.get_by_role("table", name=kind, exact=True)
        expect(table).to_be_visible()
        expect(table.locator("[data-table-sort]").first).to_have_attribute("data-sort", "asc")
        original = geometry(table)
        for column in ("name", "vulnerabilities", "created_at"):
            sort_with_keyboard(table, column, original, server=True)
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    assert not errors


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
def test_artifact_columns_contain_long_values_and_keep_badges_readable(
    authenticated_page: Page, sbom_component_details: Component, width: int
) -> None:
    page = authenticated_page
    version = "1.0.0-" + "long-build-identifier" * 5
    SBOM.objects.filter(component=sbom_component_details).update(version=version)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/component/{sbom_component_details.id}/")
    table = page.get_by_role("table", name="Artifacts", exact=True)
    expect(table.locator("tbody tr")).to_have_count(1)
    original = geometry(table)
    for column in ("name", "created_at"):
        sort_with_keyboard(table, column, original)
    badges = table.locator("tbody [data-level]")
    expect(badges).to_have_count(4)
    rows = badges.evaluate_all("elements => new Set(elements.map(el => el.getBoundingClientRect().top)).size")
    assert rows <= 2, "Severity badges should not stack into a tall single column"
    if width >= 768:
        cell = table.locator("tbody tr").first.locator("td").nth(2)
        expect(cell.locator("span")).to_have_attribute("title", version)
        expect(cell.locator("div").first).to_have_css("overflow", "hidden")
        assert cell.locator("div").first.evaluate("el => el.scrollWidth > el.clientWidth")
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_advisory_sorting_preserves_columns_and_position(
    authenticated_page: Page, advisories: list[SecurityAdvisory], width: int, theme: str
) -> None:
    page = authenticated_page
    advisories[0].title = "Zebra " + "A much longer advisory title " * 5
    advisories[0].severity = "critical"
    advisories[0].save(update_fields=["title", "severity"])
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/security-advisories/")
    table = page.get_by_role("table", name="Security advisories", exact=True)
    expect(table.locator("tbody tr")).to_have_count(10)
    original = geometry(table)
    first_name = table.locator("tbody tr").first.locator("td").nth(1).inner_text()
    sort_with_keyboard(table, "title", original)
    sort_with_keyboard(table, "title", original)
    assert table.locator("tbody tr").first.locator("td").nth(1).inner_text() != first_name
    for column in ("severity", "status"):
        sort_with_keyboard(table, column, original)
        sort_with_keyboard(table, column, original)
    page.get_by_role("button", name="Next page", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(2)
    assert geometry(table) == pytest.approx(original, abs=0.1)
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
def test_release_picker_sorts_independently_of_the_release_table(
    authenticated_page: Page, product_details: Product, sbom_factory: Callable[..., SBOM], width: int
) -> None:
    page = authenticated_page
    release = product_details.releases.get(name="v1.0.0")
    original = SBOM.objects.get(component__in=product_details.components.all())
    ReleaseArtifact.objects.create(release=release, sbom=original)
    for index, name in enumerate(("Alpha artifact", "Zulu artifact"), start=2):
        sbom_factory(original.component, name=name, version=f"{index}.0.0")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/product/{product_details.id}/release/{release.id}/")
    main = page.get_by_role("table", name="Release artifacts", exact=True)
    expect(main.locator("tbody tr")).to_have_count(1)
    sort_with_keyboard(main, "created_at", geometry(main))
    page.get_by_role("button", name="Add artifact", exact=False).click()
    picker = page.get_by_role("table", name="Available artifacts", exact=True)
    expect(picker.locator("tbody tr")).to_have_count(2)
    sort_with_keyboard(picker, "name", geometry(picker))
    expect(picker.locator("tbody tr").first).to_contain_text("Zulu artifact")
    expect(main.locator('[data-table-sort="created_at"]')).to_have_attribute("data-sort", "asc")
    expect(main.locator('[data-table-sort="name"]')).to_have_attribute("data-sort", "none")
    picker.get_by_role("checkbox", name="Select Zulu artifact", exact=True).check()
    sort_with_keyboard(picker, "name", geometry(picker))
    expect(picker.locator("tbody tr").first).to_contain_text("Alpha artifact")
    expect(picker.get_by_role("checkbox", name="Select Zulu artifact", exact=True)).to_be_checked()
