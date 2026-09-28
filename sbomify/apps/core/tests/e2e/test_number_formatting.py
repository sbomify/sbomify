"""Large server and Alpine counts remain readable without changing their values."""

from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.test_design_system_view import _debug_urlconf_fixture
from sbomify.apps.plugins.models import AssessmentRun

debug_gallery = _debug_urlconf_fixture(True)

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("width", [1920, 1536, 1280, 992, 576, 375, 320])
def test_scan_counts_are_grouped(
    authenticated_page: Page, component_factory: Any, sbom_factory: Any, team_with_business_plan: Any, width: int
) -> None:
    sbom = sbom_factory(component_factory("Number formatting component"))
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0",
        category="security",
        status="completed",
        plugin_config_hash="a" * 64,
        run_reason="manual",
        result={
            "summary": {
                "total_findings": 12345678,
                "by_severity": {"critical": 1234567, "high": 2345678, "medium": 3456789, "low": 5308644},
            }
        },
    )
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/workspaces/{team_with_business_plan.key}/vulnerability-scans/")
    card = page.locator("dl").filter(has=page.locator("dt", has_text="Vulnerabilities"))
    expect(card.locator("dd")).to_have_text("12,345,678")
    expect(page.get_by_role("cell").filter(has_text="1,234,567 Critical")).to_have_count(1)
    assert card.locator("dd").evaluate("el => el.scrollWidth <= el.clientWidth")
    assert card.locator("dd").evaluate("""el => {
        const range = document.createRange();
        range.selectNodeContents(el);
        const lines = Array.from(range.getClientRects()).filter(r => r.width > 0).map(r => Math.round(r.top));
        return new Set(lines).size === 1;
    }""")


@pytest.mark.usefixtures("debug_gallery")
def test_alpine_formats_counts_when_the_value_changes(authenticated_page: Page) -> None:
    page = authenticated_page
    page.goto("/design-system/")
    card = page.locator("dl").filter(has=page.locator("dt", has_text="Pending assessments"))
    expect(card.locator("dd")).to_have_text("0")
    page.get_by_role("button", name="Toggle example count").click()
    expect(card.locator("dd")).to_have_text("12,345")
    expect(card).not_to_have_attribute("data-zero", "true")
    page.get_by_role("button", name="Toggle example count").click()
    expect(card.locator("dd")).to_have_text("0")
    expect(card).to_have_attribute("data-zero", "true")
