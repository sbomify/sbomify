"""App pages keep the products page's heading and spacing at every width."""

from typing import Any

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM

pytest_plugins = [
    "sbomify.apps.core.tests.e2e.fixtures",
    "sbomify.apps.core.tests.e2e.test_cra_compliance",
    "sbomify.apps.core.tests.e2e.test_security_advisories",
]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("width", [1280, 375])
def test_app_headers_match_products(
    authenticated_page: Page,
    product_details: Any,
    advisory_detail: Any,
    cra_assessment: Any,
    cra_billing_session: None,
    width: int,
) -> None:
    product = product_details
    workspace_key = product.team.key
    component = product.components.filter(component_type=Component.ComponentType.BOM).first()
    sbom = SBOM.objects.get(component=component)
    release = product.releases.first()
    destinations = [
        ("core:products_dashboard", []),
        ("core:dashboard", []),
        ("core:dashboard_trends", []),
        ("core:components_dashboard", []),
        ("core:releases_dashboard", []),
        ("teams:vulnerability_scans", [workspace_key]),
        ("plugins:plugins_page", []),
        ("core:security_advisories_dashboard", []),
        ("compliance:cra_product_list", []),
        ("compliance:cra_scope_screening", [product.id]),
        ("compliance:cra_step", [cra_assessment.id, 1]),
        ("teams:team_settings", [workspace_key]),
        ("teams:teams_dashboard", []),
        ("teams:suppliers", [workspace_key]),
        ("teams:invite_user", [workspace_key]),
        ("billing:select_plan", [workspace_key]),
        ("billing:enterprise_contact", []),
        ("sboms:workspace_crypto", [workspace_key]),
        ("core:product_new", []),
        ("core:component_new", []),
        ("core:release_new", []),
        ("core:security_advisory_new", []),
        ("core:product_details", [product.id]),
        ("core:component_details", [component.id]),
        ("core:component_item", [component.id, "sboms", sbom.id]),
        ("core:product_releases", [product.id]),
        ("core:release_details", [product.id, release.id]),
        ("core:security_advisory_detail", [advisory_detail.id]),
        ("sboms:component_artifacts", [component.id]),
        ("sboms:sbom_vulnerabilities", [sbom.id]),
    ]
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    reference = None
    for route, args in destinations:
        response = page.goto(reverse(route, args=args))
        assert response and response.status == 200, route
        header = page.locator("#main-content [data-page-header]")
        expect(header).to_have_count(1)
        heading = header.get_by_role("heading", level=1)
        expect(heading).to_be_visible()
        expect(page.locator("#main-content h1")).to_have_count(1)
        appearance = heading.evaluate(
            "el => { const s = getComputedStyle(el); return { font: s.fontFamily, size: s.fontSize, "
            "weight: s.fontWeight, height: s.lineHeight, spacing: s.letterSpacing, color: s.color, "
            "left: el.getBoundingClientRect().left }; }"
        )
        if reference is None:
            reference = appearance
        assert appearance == reference, route
        assert header.evaluate("el => getComputedStyle(el.parentElement).rowGap") == "24px", route
        assert header.evaluate("el => el.getBoundingClientRect().right <= document.documentElement.clientWidth"), route


@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("kind", ["bom", "document"])
def test_component_sections_keep_the_frame_gap(
    request: pytest.FixtureRequest,
    authenticated_page: Page,
    kind: str,
    width: int,
) -> None:
    fixture = "sbom_component_details" if kind == "bom" else "document_component_details"
    component = request.getfixturevalue(fixture)
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(reverse("core:component_details", args=[component.id]))
    region = "sboms-table-region" if kind == "bom" else "documents-table-region"
    expect(page.locator(f"#{region} table")).to_be_visible()
    gaps = page.locator("[data-page-header]").evaluate(
        """header => {
            const sections = [...header.nextElementSibling.children]
                .map(el => el.getBoundingClientRect()).filter(rect => rect.height > 0);
            return sections.slice(1).map((rect, i) => rect.top - sections[i].bottom);
        }"""
    )
    assert len(gaps) >= 2
    assert all(abs(gap - 24) < 1 for gap in gaps), gaps


@pytest.mark.parametrize("width", [1280, 375])
def test_artifact_assessment_uses_the_frame_gap(
    authenticated_page: Page, sbom_component_details: Any, width: int
) -> None:
    sbom = SBOM.objects.get(component=sbom_component_details)
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(reverse("core:component_item", args=[sbom_component_details.id, "sboms", sbom.id]))
    assessment = page.locator("#assessment-results")
    expect(assessment).to_be_visible()
    gap = assessment.evaluate(
        """el => {
            let previous = el.parentElement.previousElementSibling;
            while (previous && previous.getBoundingClientRect().height === 0) {
                previous = previous.previousElementSibling;
            }
            return el.getBoundingClientRect().top - previous.getBoundingClientRect().bottom;
        }"""
    )
    assert abs(gap - 24) < 1


@pytest.mark.parametrize("width", [1280, 375])
def test_advisory_header_keeps_long_text_and_actions_accessible(
    authenticated_page: Page, advisory_detail: Any, width: int
) -> None:
    advisory_detail.title = "A long advisory title " + "identifier" * 20
    advisory_detail.description = "Supporting information about the affected versions and the available fix. " * 30
    advisory_detail.save(update_fields=["title", "description"])
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(reverse("core:security_advisory_detail", args=[advisory_detail.id]))
    header = page.locator("[data-page-header]")
    title = header.get_by_role("heading", level=1)
    expect(title).to_have_text(advisory_detail.title)
    assert title.evaluate("el => el.scrollWidth <= el.clientWidth")
    expand = header.get_by_role("button", name="Show more", exact=True)
    expect(expand).to_have_attribute("aria-expanded", "false")
    expand.click()
    collapse = header.get_by_role("button", name="Show less", exact=True)
    expect(collapse).to_have_attribute("aria-expanded", "true")
    description = page.locator(f"[id='{collapse.get_attribute('aria-controls')}']")
    assert description.evaluate("el => el.scrollHeight <= el.clientHeight")
    collapse.click()
    expect(expand).to_have_attribute("aria-expanded", "false")
    header.get_by_role("button", name="Advisory actions", exact=True).click()
    page.get_by_role("menuitem", name="Edit advisory", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit advisory", exact=True)).to_be_visible()
    assert not errors
