"""Visibility choices share one menu and change only after an accepted request."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from django.urls import reverse
from playwright.sync_api import Page, Route, expect

from sbomify.apps.core.models import Component, Product
from sbomify.apps.teams.models import Team

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("component_type", ["bom", "document"])
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_component_visibility_menu(
    authenticated_page: Page,
    component_factory: Callable[..., Component],
    component_type: str,
    width: int,
    theme: str,
    tmp_path: Path,
) -> None:
    component = component_factory("Visibility example", component_type, visibility="gated")
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 750})
    page.goto(reverse("core:component_details", args=[component.pk]))
    trigger = page.get_by_role("button", name="Component visibility", exact=True)
    menu = page.get_by_role("menu", name="Component visibility", exact=True)
    trigger.focus()
    page.keyboard.press("ArrowDown")
    gated = menu.get_by_role("menuitemradio", name=re.compile(r"^Gated\b"))
    expect(gated).to_be_focused()
    expect(gated).to_have_attribute("aria-checked", "true")
    expect(menu.get_by_text("Public listing. Downloads need approval.")).to_be_visible()
    page.keyboard.press("ArrowUp")
    expect(menu.get_by_role("menuitemradio", name=re.compile(r"^Public\b"))).to_be_focused()
    component.refresh_from_db()
    assert component.visibility == "gated"
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(trigger).to_be_focused()
    trigger.click()
    expect(menu).to_be_visible()
    page.screenshot(path=str(tmp_path / f"visibility-{component_type}-{theme}-{width}.png"), animations="disabled")
    assert menu.evaluate(
        "el => el.getBoundingClientRect().left >= 8 && "
        "el.getBoundingClientRect().right <= document.documentElement.clientWidth - 8"
    )
    page.keyboard.press("Home")
    expect(menu.get_by_role("menuitemradio", name=re.compile(r"^Private\b"))).to_be_focused()
    page.keyboard.press("Enter")
    expect(trigger).to_contain_text("Private")
    expect(trigger).to_be_enabled()
    component.refresh_from_db()
    assert component.visibility == "private"
    page.get_by_role("button", name="Component actions", exact=True).click()
    expect(page.get_by_role("menuitem", name="Copy public URL", exact=True)).to_be_hidden()
    page.keyboard.press("Escape")
    trigger.click()
    menu.get_by_role("menuitemradio", name=re.compile(r"^Public\b")).click()
    expect(trigger).to_contain_text("Public")
    component.refresh_from_db()
    assert component.visibility == "public"
    page.get_by_role("button", name="Component actions", exact=True).click()
    expect(page.get_by_role("menuitem", name="Copy public URL", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    trigger.click()
    gated.click()
    expect(trigger).to_contain_text("Gated")
    component.refresh_from_db()
    assert component.visibility == "gated"
    page.reload()
    expect(trigger).to_contain_text("Gated")
    assert not errors


@pytest.mark.parametrize("width", [1280, 375])
def test_product_uses_the_same_visibility_menu(
    authenticated_page: Page,
    product_factory: Callable[..., Product],
    component_factory: Callable[..., Component],
    sbom_factory: Callable,
    width: int,
) -> None:
    product = product_factory("Visibility product", is_public=False)
    component = component_factory("Downloadable component", product=product)
    sbom_factory(component)
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 750})
    page.goto(reverse("core:product_details", args=[product.pk]))
    header = page.locator("[data-page-header]")
    trigger = header.get_by_role("button", name="Product visibility", exact=True)
    actions = header.get_by_role("button", name="Product actions", exact=True)
    expect(trigger).to_be_visible()
    expect(actions).to_be_visible()
    trigger_bounds, actions_bounds = trigger.bounding_box(), actions.bounding_box()
    assert trigger_bounds and actions_bounds
    assert abs(trigger_bounds["y"] - actions_bounds["y"]) < 1
    assert 0 < actions_bounds["x"] - (trigger_bounds["x"] + trigger_bounds["width"]) <= 16
    trigger.click()
    menu = page.get_by_role("menu", name="Product visibility", exact=True)
    expect(menu.get_by_role("menuitemradio")).to_have_count(2)
    expect(menu.get_by_role("menuitemradio", name=re.compile(r"^Private\b"))).to_have_attribute("aria-checked", "true")
    menu.get_by_role("menuitemradio", name=re.compile(r"^Public\b")).click()
    expect(trigger).to_contain_text("Public")
    product.refresh_from_db()
    assert product.is_public
    page.reload()
    expect(trigger).to_contain_text("Public")


@pytest.mark.parametrize("failure", ["rejected", "network"])
def test_visibility_failure_keeps_saved_choice(
    authenticated_page: Page, component_factory: Callable[..., Component], failure: str
) -> None:
    component = component_factory("Visibility failure", "document", visibility="gated")
    page = authenticated_page
    pending: list[Route] = []
    page.route(
        f"**{reverse('core:toggle_public_status', args=['component', component.pk])}",
        lambda route: pending.append(route),
    )
    page.goto(reverse("core:component_details", args=[component.pk]))
    trigger = page.get_by_role("button", name="Component visibility", exact=True)
    menu = page.get_by_role("menu", name="Component visibility", exact=True)
    trigger.click()
    menu.get_by_role("menuitemradio", name=re.compile(r"^Private\b")).click()
    expect(trigger).to_be_disabled()
    expect(trigger).to_contain_text("Gated")
    assert len(pending) == 1
    assert "visibility=private" in (pending[0].request.post_data or "")
    assert "csrfmiddlewaretoken=" in (pending[0].request.post_data or "")
    if failure == "network":
        pending[0].abort("failed")
    else:
        pending[0].fulfill(status=200, json={})
    expect(trigger).to_be_enabled()
    expect(trigger).to_contain_text("Gated")
    trigger.click()
    expect(menu.get_by_role("menuitemradio", name=re.compile(r"^Gated\b"))).to_have_attribute("aria-checked", "true")
    menu.get_by_role("menuitemradio", name=re.compile(r"^Gated\b")).click()
    expect(menu).to_be_hidden()
    assert len(pending) == 1
    component.refresh_from_db()
    assert component.visibility == "gated"


def test_unavailable_gated_option_explains_plan(
    authenticated_page: Page, component_factory: Callable[..., Component], team_with_business_plan: Team
) -> None:
    component = component_factory("Visibility plan", "document", visibility="public")
    team_with_business_plan.billing_plan = "community"
    team_with_business_plan.save(update_fields=["billing_plan"])
    page = authenticated_page
    page.goto(reverse("core:component_details", args=[component.pk]))
    trigger = page.get_by_role("button", name="Component visibility", exact=True)
    trigger.click()
    menu = page.get_by_role("menu", name="Component visibility", exact=True)
    gated = menu.get_by_role("menuitemradio", name=re.compile(r"^Gated\b"))
    expect(gated).to_be_disabled()
    expect(gated).to_contain_text("Available on Business and Enterprise plans.")
    page.keyboard.press("End")
    expect(menu.get_by_role("menuitemradio", name=re.compile(r"^Public\b"))).to_be_focused()
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    component.refresh_from_db()
    assert component.visibility == "public"
