from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


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
    page.get_by_role("button", name="Add release", exact=False).click()
    picker = page.get_by_role("dialog", name="Add release", exact=True)
    expect(picker).to_be_visible()
    picker.get_by_role("link", name="Test Product 0", exact=True).click()
    expect(page.get_by_role("dialog", name="Create release", exact=True)).to_be_visible()


@pytest.mark.django_db
def test_empty_overview_and_trends(authenticated_page: Page) -> None:
    page = authenticated_page
    page.goto("/dashboard")
    expect(page.get_by_role("group", name="Key metrics", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="What to fix first")).to_be_visible()
    expect(page.get_by_role("heading", name="Exposure by product")).to_be_visible()
    expect(page.get_by_role("heading", name="Waiting for security scans")).to_be_visible()
    page.get_by_role("button", name="Add release", exact=False).click()
    picker = page.get_by_role("dialog", name="Add release", exact=True)
    expect(picker.get_by_role("heading", name="Add a product first")).to_be_visible()
    page.keyboard.press("Escape")
    expect(picker).to_be_hidden()
    page.get_by_role("link", name="View trends", exact=True).click()
    expect(page.get_by_role("heading", name="Vulnerability trends", exact=True).first).to_be_visible()
    expect(page.locator("#vuln-trends-body")).to_be_visible()
