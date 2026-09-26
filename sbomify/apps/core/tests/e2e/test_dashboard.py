from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect
from pytest_django.fixtures import SettingsWrapper

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.tests.e2e.utils import take_screenshot


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestDashboardSnapshot:
    def test_dashboard_snapshot(
        self,
        authenticated_page: Page,
        overview_dashboard: dict[str, Any],
        snapshot: Any,
        width: int,
    ) -> None:
        authenticated_page.goto("/dashboard")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.fixture
def overview_dashboard(dashboard: dict[str, Any]) -> dict[str, Any]:
    from django.core.cache import cache

    from sbomify.apps.plugins.models import AssessmentRun, VulnerabilityLifecycle
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    run = AssessmentRun.objects.create(
        sbom=dashboard["sboms"][0],
        plugin_name="overview-review",
        category="security",
        status="completed",
        result={
            "findings": [
                {
                    "id": "CVE-2026-10001",
                    "severity": "critical",
                    "component": {"name": "libexample", "version": "1.2.3"},
                },
                {
                    "id": "CVE-2026-10002",
                    "severity": "high",
                    "component": {"name": "example-runtime", "version": "2.0.0"},
                },
            ],
        },
    )
    sync_findings(run)
    VulnerabilityLifecycle.objects.create(
        component=dashboard["sboms"][0].component,
        advisory_id="CVE-2026-10001",
        first_seen_at=timezone.now() - timedelta(days=20),
        last_seen_at=timezone.now(),
    )
    cache.clear()
    return dashboard


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_overview_priority_table_and_mobile_drawer(
    authenticated_page: Page, overview_dashboard: dict[str, Any], width: int, theme: str
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/dashboard")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    priority = page.get_by_role("table", name="Priority vulnerabilities")
    expect(priority.get_by_role("link", name="CVE-2026-10001", exact=True)).to_be_visible()
    exposure = page.get_by_role("table", name="Product exposure")
    expect(exposure).to_be_visible()
    # Hidden dialog mounts must not add empty rows between canvas sections.
    gaps = page.locator("#main-content > div").evaluate("""frame => {
        const rows = Array.from(frame.children)
            .map(child => child.getBoundingClientRect()).filter(rect => rect.height > 0);
        return rows.slice(1).map((row, index) => row.top - rows[index].bottom);
    }""")
    assert len(gaps) >= 4
    assert gaps == pytest.approx([24] * len(gaps))
    trigger = exposure.get_by_role("button", name="Vulnerability breakdown: 2 open").first
    trigger.click()
    panel = page.get_by_role("dialog", name="Vulnerability breakdown", exact=True)
    expect(panel).to_be_visible()
    expect(panel).to_be_focused()
    expect(panel).to_contain_text("2 open vulnerabilities")
    assert panel.evaluate(
        "el => el.getBoundingClientRect().left >= 0 && el.getBoundingClientRect().right <= innerWidth"
    )
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(trigger).to_be_focused()
    expect(priority.locator("th").filter(has_text="Patch SLA")).to_be_visible()
    assert page.locator("html").evaluate("el => el.scrollWidth <= window.innerWidth")
    if width < 1024:
        expect(page.locator("#sidebar")).to_be_hidden()
        page.get_by_role("button", name="Toggle sidebar navigation").click()
        expect(page.get_by_role("link", name="Overview", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#sidebar")).to_be_hidden()
    page.get_by_role("link", name="Add release", exact=False).click()
    expect(page.get_by_role("heading", name="New release", exact=True)).to_be_visible()
    expect(page.get_by_role("combobox", name="Product *", exact=True)).to_contain_text("Test Product 0")


@pytest.mark.django_db
def test_empty_overview_and_trends(authenticated_page: Page) -> None:
    page = authenticated_page
    page.goto("/dashboard")
    expect(page.get_by_role("group", name="Key metrics", exact=True)).to_have_count(0)
    expect(page.get_by_role("heading", name="What to fix first")).to_have_count(0)
    expect(page.get_by_role("heading", name="Exposure by product")).to_have_count(0)
    expect(page.get_by_role("heading", name="Set up your first repository")).to_be_visible()
    page.locator("#main-content").get_by_role("link", name="Add component", exact=True).click()
    expect(page.get_by_role("heading", name="New component", exact=True)).to_be_visible()
    page.go_back()
    page.goto("/dashboard/trends/")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    expect(page.locator("#vuln-trends-body")).to_be_visible()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_empty_dashboard_snapshot(
    authenticated_page: Page, snapshot: Any, width: int, theme: str, settings: SettingsWrapper
) -> None:
    settings.APP_BASE_URL = "https://app.example.com"
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/dashboard")
    expect(page.get_by_role("heading", name="Set up your first repository")).to_be_visible()
    expect(page.locator("#navbar-search-dropdown")).to_be_hidden()
    page.wait_for_load_state("networkidle")
    assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")

    baseline = snapshot.get_or_create_baseline_screenshot(page, width=width)
    current = snapshot.take_screenshot(page, width=width)
    snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    page.get_by_role("tab", name="Terminal", exact=True).click()
    expect(page.locator("#repository-setup-command")).to_contain_text("sbomify-action wizard")
    page.get_by_role("button", name="uv", exact=True).click()
    expect(page.locator("#repository-setup-command")).to_contain_text("uvx sbomify-action wizard")


@pytest.mark.django_db
@pytest.mark.parametrize("component_type", ["bom", "document"])
def test_empty_dashboard_manual_upload_and_first_artifact(
    authenticated_page: Page, team_with_business_plan: Any, component_type: str
) -> None:
    from sbomify.apps.core.models import Component
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.models import SBOM

    component = Component.objects.create(
        name="First component", team=team_with_business_plan, component_type=component_type
    )
    page = authenticated_page
    page.goto("/dashboard")
    main = page.locator("#main-content")
    if component_type == "bom":
        main.get_by_role("button", name="Upload SBOM", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        SBOM.objects.create(name="First SBOM", component=component, format="cyclonedx")
    else:
        expect(main.get_by_role("button", name="Upload SBOM", exact=True)).to_have_count(0)
        expect(main.get_by_role("link", name="Add component", exact=True)).to_be_visible()
        Document.objects.create(name="Architecture", component=component)

    page.reload()
    expect(page.get_by_role("heading", name="Set up your first repository")).to_have_count(0)
    expect(page.get_by_role("group", name="Key metrics", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Exposure by product")).to_be_visible()
    page.goto("/getting-started/")
    expect(page.get_by_role("tab", name="Coding agent", exact=True)).to_be_visible()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("runtime", ["docker", "uv"])
def test_repository_terminal_snapshot(
    authenticated_page: Page, snapshot: Any, width: int, theme: str, runtime: str, settings: SettingsWrapper
) -> None:
    settings.APP_BASE_URL = "https://app.example.com"
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/dashboard")
    page.get_by_role("tab", name="Terminal", exact=True).click()
    if runtime == "uv":
        page.get_by_role("button", name="uv", exact=True).click()
    page.wait_for_load_state("networkidle")
    assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
    baseline = snapshot.get_or_create_baseline_screenshot(page, width=width)
    current = snapshot.take_screenshot(page, width=width)
    snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
def test_repository_setup_tabs_copy_and_token_reset(authenticated_page: Page, settings: SettingsWrapper) -> None:
    from sbomify.apps.access_tokens.models import AccessToken

    settings.APP_BASE_URL = "http://localhost:8000"
    page = authenticated_page
    page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async value => { window.setupCopiedText = value; } }
    });""")
    page.goto("/dashboard")
    copy_prompt = page.get_by_role("button", name="Copy prompt", exact=True)
    expect(copy_prompt).to_be_disabled()
    assert not AccessToken.objects.exists()
    page.get_by_role("button", name="Create setup token", exact=True).click()
    expect(copy_prompt).to_be_enabled()
    original = AccessToken.objects.get()
    page.get_by_role("button", name="Public", exact=True).click()
    copy_prompt.click()
    page.wait_for_function("window.setupCopiedText?.includes('Create everything as public.')")
    copied = page.evaluate("window.setupCopiedText")
    assert copied == page.locator("#repository-setup-prompt").text_content()
    assert "YOUR_SETUP_TOKEN" not in copied
    assert original.encoded_token in copied
    page.locator("#panel-setup-agent").get_by_role("button", name="Copy code", exact=True).click()
    assert page.evaluate("window.setupCopiedText") == copied
    agent_tab = page.get_by_role("tab", name="Coding agent", exact=True)
    agent_tab.focus()
    agent_tab.press("ArrowRight")
    expect(page.get_by_role("tab", name="Terminal", exact=True)).to_have_attribute("aria-selected", "true")
    page.get_by_role("button", name="uv", exact=True).click()
    page.get_by_role("button", name="Copy command", exact=True).click()
    page.wait_for_function("window.setupCopiedText?.includes('uvx sbomify-action wizard')")
    assert original.encoded_token in page.evaluate("window.setupCopiedText")
    page.get_by_role("button", name="Reset token", exact=True).click()
    expect(page.get_by_role("button", name="Reset token", exact=True)).to_be_enabled()
    assert not AccessToken.objects.filter(pk=original.pk).exists()
    replacement = AccessToken.objects.get()
    assert replacement.pk != original.pk
    expect(page.locator("#repository-setup-command")).to_contain_text(replacement.encoded_token)
    page.get_by_role("tab", name="Terminal", exact=True).press("ArrowLeft")
    expect(agent_tab).to_have_attribute("aria-selected", "true")
    expect(page.locator("#repository-setup-prompt")).to_contain_text("Create everything as public.")


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_dashboard_view_switch_and_trend_filters(
    authenticated_page: Page, dashboard: dict[str, Any], width: int, theme: str, tmp_path: Path
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/dashboard")
    navigation = page.get_by_role("navigation", name="Dashboard views")
    expect(navigation.get_by_role("link", name="Summary")).to_have_attribute("aria-current", "page")
    summary_metrics = page.get_by_role("group", name="Key metrics").bounding_box()
    assert summary_metrics is not None
    navigation.get_by_role("link", name="Trends").click()

    expect(page.locator("h1")).to_have_text("Overview")
    expect(navigation.locator('[aria-current="page"]')).to_have_text("Trends")
    metrics = page.get_by_role("group", name="Vulnerability metrics")
    expect(metrics).to_be_visible()
    trends_metrics = metrics.bounding_box()
    assert trends_metrics is not None
    assert trends_metrics["x"] == pytest.approx(summary_metrics["x"])
    assert trends_metrics["y"] == pytest.approx(summary_metrics["y"])
    assert trends_metrics["width"] == pytest.approx(summary_metrics["width"])
    assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
    chart = page.locator(".vulnerability-chart-canvas")
    expect(chart).to_be_visible()
    chart_matches_theme = """() => {
        const canvas = document.querySelector('.vulnerability-chart-canvas');
        const chart = window.Chart?.getChart(canvas);
        if (!chart) return false;
        const styles = getComputedStyle(canvas);
        const token = name => styles.getPropertyValue(`--color-${name}`).trim();
        return chart.options.scales.x.ticks.color === token('text-muted')
            && chart.options.plugins.tooltip.backgroundColor === token('surface-elevated')
            && chart.data.datasets[0].borderColor === token('severity-critical');
    }"""
    page.wait_for_function(chart_matches_theme)
    page.wait_for_function(
        "window.Chart?.getChart(document.querySelector('.vulnerability-chart-canvas'))?.config.type === 'line'"
    )
    take_screenshot(page, "trends", width=width, path=tmp_path / f"trends-{theme}-{width}.png")
    page.set_viewport_size({"width": width, "height": 900})

    page.get_by_role("button", name="Severity", exact=True).click()
    expect(page.get_by_role("button", name="Severity", exact=True)).to_have_attribute("aria-pressed", "true")
    # Theme changes repaint the canvas and preserve the selected chart view.
    for selected_theme in ("dark" if theme == "light" else "light", theme):
        page.evaluate("theme => window.themeManager.setTheme(theme)", selected_theme)
        page.wait_for_function("""() => {
            const canvas = document.querySelector('.vulnerability-chart-canvas');
            const chart = window.Chart?.getChart(canvas);
            return chart?.config.type === 'bar' && chart.options.scales.x.ticks.color ===
                getComputedStyle(canvas).getPropertyValue('--color-text-muted').trim();
        }""")
    page.get_by_role("combobox", name="Time range").select_option("7")
    expect(page.get_by_role("combobox", name="Time range")).to_have_value("7")
    page.wait_for_function(
        "window.Chart?.getChart(document.querySelector('.vulnerability-chart-canvas'))?.config.type === 'bar'"
    )

    # A filter with no scans must leave its controls available to recover.
    page.get_by_role("combobox", name="Product", exact=True).select_option(dashboard["products"][2].id)
    expect(page.get_by_role("heading", name="No vulnerability data")).to_be_visible()
    page.wait_for_function("Object.keys(Chart.instances).length === 0")
    expect(page.get_by_role("combobox", name="Product", exact=True)).to_be_visible()
    page.get_by_role("combobox", name="Product", exact=True).select_option(dashboard["products"][0].id)
    expect(chart).to_be_visible()
    expect(page.get_by_role("button", name="Severity", exact=True)).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "window.Chart?.getChart(document.querySelector('.vulnerability-chart-canvas'))?.config.type === 'bar'"
    )
    expect(page.get_by_role("combobox", name="Time range")).to_have_value("7")
    scans = page.get_by_role("table", name="Recent SBOM scans")
    scans.get_by_role("button", name="Vulnerability breakdown:").first.click()
    expect(page.get_by_role("dialog", name="Vulnerability breakdown", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    scans.get_by_role("link", name="sbom-0.json", exact=True).first.click()
    expect(page.locator("h1")).to_contain_text("sbom-0.json")
    page.go_back()
    page.wait_for_function("window.Chart && Object.keys(window.Chart.instances).length === 1")
    page.locator('[x-data="vulnerabilityTrends"]').evaluate("element => element.remove()")
    page.wait_for_function("Object.keys(Chart.instances).length === 0")
    navigation.get_by_role("link", name="Summary").click()
    expect(navigation.locator('[aria-current="page"]')).to_have_text("Summary")
    expect(page.get_by_role("group", name="Key metrics")).to_be_visible()


@pytest.mark.django_db
def test_the_trends_fragment_url_lands_on_the_trends_page(authenticated_page: Page, dashboard: dict[str, Any]) -> None:
    """Both URLs used to render Trends, with different release defaults and a
    different set of controls, so the same workspace reported two totals."""
    page = authenticated_page
    page.goto("/dashboard/trends/")
    expect(page.locator(".vulnerability-chart-canvas")).to_be_visible()
    metrics = page.get_by_role("group", name="Vulnerability metrics")
    expected = metrics.inner_text()
    controls = page.locator("#vuln-trends-body select").count()

    page.goto("/vulnerability-trends/")

    expect(page.locator(".vulnerability-chart-canvas")).to_be_visible()
    assert page.url.endswith("/dashboard/trends/")
    assert metrics.inner_text() == expected
    assert page.locator("#vuln-trends-body select").count() == controls
    expect(page.locator("#sidebar a[aria-current='page']")).to_have_text("Overview")
