"""Hold real content requests so skeletons, replacement and action feedback are observable."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from django.urls import reverse
from playwright.sync_api import Locator, Page, Route, expect

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.test_design_system_view import _debug_urlconf_fixture
from sbomify.apps.teams.models import Team

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
pytestmark = pytest.mark.django_db
debug_gallery = _debug_urlconf_fixture(True)


def assert_content_placeholder(region: Locator) -> None:
    expect(region.locator("[data-content-loading]").first).to_be_visible()
    expect(region.locator(".tw-brand-loader")).to_have_count(0)
    # Composed page skeletons must expose only the outer loading announcement.
    expect(region.get_by_role("status")).to_have_count(1)
    expect(region.get_by_role("button")).to_have_count(0)
    assert region.evaluate("el => el.scrollWidth <= el.clientWidth + 1")


@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_page_and_summary_skeletons_are_replaced_independently(
    authenticated_page: Page, team_with_business_plan: Team, width: int, theme: str, tmp_path: Path
) -> None:
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    requests: dict[str, Route] = {}
    page.route(f"**{reverse('plugins:plugins_summary')}", lambda route: requests.update(summary=route))
    page.route(
        f"**{reverse('plugins:team_plugin_settings', args=[team_with_business_plan.key])}",
        lambda route: requests.update(content=route),
    )
    page.goto(reverse("plugins:plugins_page"), wait_until="domcontentloaded")
    summary = page.locator("#plugins-summary")
    content = page.locator("#plugins-page-content")
    expect(content).to_have_class(re.compile("htmx-request"))
    expect(summary).to_have_class(re.compile("htmx-request"))
    expect(page.get_by_role("heading", name="Plugins", exact=True)).to_be_visible()
    assert_content_placeholder(summary)
    assert_content_placeholder(content)

    shape = content.locator('[class*="motion-safe:animate-"]').first
    expect(shape).to_have_css("animation-name", "none")
    page.emulate_media(reduced_motion="no-preference")
    expect(shape).to_have_css("animation-name", "shimmer")
    page.emulate_media(reduced_motion="reduce")
    expect(shape).to_have_css("animation-name", "none")
    page.screenshot(path=str(tmp_path / f"loading-page-{theme}-{width}.png"), full_page=True)

    card_height = summary.locator("dl").first.evaluate("el => el.getBoundingClientRect().height")
    requests["summary"].continue_()
    expect(summary.locator("[data-content-loading]")).to_have_count(0)
    assert summary.locator("dl").first.evaluate("el => el.getBoundingClientRect().height") == pytest.approx(card_height)
    assert_content_placeholder(content)
    requests["content"].continue_()
    expect(content.locator("[data-content-loading]")).to_have_count(0)
    expect(page.locator("#plugin-settings-form")).to_be_visible()
    save = page.get_by_role("button", name="Save changes", exact=True).first
    save.click()
    expect(page.locator("#plugin-settings-spinner .tw-brand-loader")).to_be_visible()
    expect(save).to_be_disabled()
    expect(content.locator("[data-content-loading]")).to_have_count(0)
    assert requests["content"].request.method == "POST"
    requests["content"].fulfill(status=204)
    expect(save).to_be_enabled()
    expect(page.locator("#plugin-settings-spinner")).to_be_hidden()


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("kind", ["bom", "document"])
def test_artifact_skeletons_work_in_app_and_public_stylesheets(
    authenticated_page: Page,
    component_factory: Callable[..., Component],
    team_with_business_plan: Team,
    public: bool,
    kind: str,
    tmp_path: Path,
) -> None:
    page = authenticated_page
    team_with_business_plan.is_public = True
    team_with_business_plan.save(update_fields=["is_public"])
    component = component_factory("Loading example", kind, visibility="public")
    table_name = "sboms" if kind == "bom" else "documents"
    suffix = "_public" if public else ""
    pending: list[Route] = []
    page.route(
        f"**{reverse(f'{table_name}:{table_name}_table{suffix}', args=[component.pk])}",
        lambda route: pending.append(route),
    )
    page.set_viewport_size({"width": 375, "height": 900})
    page.goto(reverse(f"core:component_details{suffix}", args=[component.pk]), wait_until="domcontentloaded")
    region = page.locator(f"#{table_name}-table-region")
    expect(region).to_have_class(re.compile("htmx-request"))
    assert_content_placeholder(region)
    shapes = region.locator('[class*="motion-safe:animate-"]')
    assert shapes.evaluate_all(
        "nodes => nodes.every(el => { const s = getComputedStyle(el); "
        "return s.backgroundImage !== 'none' && s.marginTop === '0px' && s.marginBottom === '0px' "
        "&& el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0; })"
    )
    region.screenshot(path=str(tmp_path / f"loading-table-{kind}-{public}.png"))
    assert len(pending) == 1
    pending[0].continue_()
    expect(region.locator("[data-content-loading]")).to_have_count(0)
    expect(region).to_be_visible()
    expect(page.locator(f"#{table_name}-table-container")).to_have_count(1)


def test_search_skeleton_keeps_focus_and_clears_on_failure(authenticated_page: Page) -> None:
    page = authenticated_page
    pending: list[Route] = []
    page.route("**/search/?*", lambda route: pending.append(route))
    page.goto("/products/")
    search = page.get_by_role("combobox", name="Search products, components and pages")
    page.keyboard.press("Control+k")
    with page.expect_request("**/search/?*"):
        search.fill("example")
    panel = page.locator("#navbar-search-dropdown")
    expect(panel.locator("[data-content-loading]")).to_be_visible()
    expect(panel.locator(".tw-brand-loader")).to_have_count(0)
    expect(search).to_be_focused()
    assert len(pending) == 1
    pending[0].fulfill(status=503)
    expect(panel.locator("[data-content-loading]")).to_be_hidden()
    expect(panel.get_by_text("Search is unavailable", exact=True)).to_be_visible()
    expect(search).to_be_focused()


@pytest.mark.usefixtures("debug_gallery")
def test_gallery_shows_all_content_shapes_and_small_action_loaders(authenticated_page: Page) -> None:
    page = authenticated_page
    page.goto("/design-system/")
    for label in ("Card content", "Lists and dropdowns", "Charts", "Small actions", "Skeleton primitives"):
        expect(page.get_by_role("heading", name=label, exact=True)).to_be_attached()
    action = page.get_by_role("button", name=re.compile("Saving"))
    expect(action.locator(".tw-brand-loader")).to_have_count(1)
    expect(action).to_be_disabled()
    expect(action.locator("[data-content-loading]")).to_have_count(0)
    expect(page.locator("[data-content-loading] .tw-brand-loader")).to_have_count(0)
