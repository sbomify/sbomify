"""Plugins layout and saved configuration through the real HTMX form."""

from unittest.mock import patch

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
from sbomify.apps.teams.models import Team

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestPluginsPageSnapshot:
    """Shared summary cards and category sections at desktop and mobile widths."""

    def test_plugins_page_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/plugins/")
        authenticated_page.wait_for_load_state("networkidle")
        authenticated_page.wait_for_selector("#plugin-settings-form")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.fixture
def configurable_plugin(team_with_business_plan: Team) -> RegisteredPlugin:
    plugin = RegisteredPlugin.objects.create(
        name="ui-config-example",
        display_name="Configurable assessment",
        description="Choose how this assessment runs.",
        category="compliance",
        version="1.0.0",
        plugin_class_path="sbomify.apps.plugins.builtins.osv.OSVPlugin",
        config_schema=[
            {"key": "mode", "label": "Mode", "type": "select", "choices": [{"value": "strict", "label": "Strict"}]},
            {"key": "timeout", "label": "Timeout", "type": "number"},
            {"key": "note", "label": "Note", "type": "text"},
            {"key": "verbose", "label": "Verbose output", "type": "boolean"},
            {"key": "server", "label": "Hidden server", "type": "select", "choices": [], "hide_if_no_choices": True},
        ],
    )
    TeamPluginSettings.objects.update_or_create(
        team=team_with_business_plan, defaults={"enabled_plugins": [], "plugin_configs": {}}
    )
    return plugin


@pytest.mark.django_db
@pytest.mark.parametrize("width", [375, 1280])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_plugin_configuration_saves_and_refreshes_summary(
    authenticated_page: Page, configurable_plugin: RegisteredPlugin, width: int, theme: str
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 800})
    page.goto("/plugins/")
    enabled = page.get_by_role("checkbox", name="Enable Configurable assessment", exact=True)
    mode = page.get_by_label("Mode", exact=True)
    summary = page.locator("#plugins-summary dl").filter(has_text="Enabled plugins").locator("dd")
    expect(enabled).not_to_be_checked()
    expect(mode).to_be_hidden()
    expect(summary).to_have_text("0")

    # A row click enables its own control; editing nested fields must not toggle it.
    page.get_by_text(configurable_plugin.description, exact=True).click()
    expect(enabled).to_be_checked()
    mode.select_option("strict")
    page.get_by_label("Timeout", exact=True).fill("45")
    page.get_by_label("Note", exact=True).fill("Review uploads")
    page.get_by_label("Verbose output", exact=True).check()
    expect(enabled).to_be_checked()
    expect(page.get_by_label("Hidden server", exact=True)).to_have_count(0)
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")

    page.get_by_role("button", name="Save changes", exact=True).first.click()
    expect(summary).to_have_text("1")
    page.reload()
    expect(enabled).to_be_checked()
    expect(mode).to_have_value("strict")
    expect(page.get_by_label("Timeout", exact=True)).to_have_value("45")
    expect(page.get_by_label("Note", exact=True)).to_have_value("Review uploads")
    expect(page.get_by_label("Verbose output", exact=True)).to_be_checked()

    enabled.focus()
    page.keyboard.press("Space")
    expect(enabled).not_to_be_checked()
    expect(mode).to_be_hidden()
    page.get_by_role("button", name="Save changes", exact=True).last.click()
    expect(summary).to_have_text("0")
    page.reload()
    expect(enabled).not_to_be_checked()


@pytest.mark.django_db
def test_plugin_upgrade_link_and_disabled_control(authenticated_page: Page, team_with_business_plan: Team) -> None:
    team_with_business_plan.billing_plan = "community"
    team_with_business_plan.save(update_fields=["billing_plan"])
    page = authenticated_page
    with patch("sbomify.apps.billing.config.is_billing_enabled", return_value=True):
        page.goto("/plugins/")
        control = page.get_by_role("checkbox", name="Enable Dependency Track", exact=True)
        expect(control).to_be_disabled()
        control.locator("..").locator("p").first.click()
        expect(control).not_to_be_checked()
        upgrade = control.locator("..").get_by_role("link", name="View plans", exact=True)
        plan_url = reverse("billing:select_plan", args=[team_with_business_plan.key])
        expect(upgrade).to_have_attribute("href", plan_url)
        upgrade.click()
        expect(page).to_have_url(plan_url)


@pytest.mark.django_db
def test_plugins_empty_state(authenticated_page: Page) -> None:
    RegisteredPlugin.objects.update(is_enabled=False)
    page = authenticated_page
    page.goto("/plugins/")
    expect(page.get_by_text("No plugins available", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    expect(page.locator("#plugins-summary dl").filter(has_text="Available plugins").locator("dd")).to_have_text("0")
