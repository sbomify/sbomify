"""Generates full-page screenshots for the trust-center public views.

Not a regression test — this saves screenshots to /tmp/ux-review/ so they can
be inspected manually after the trust-center UI changes in PR #966.
"""

import hashlib
from pathlib import Path

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import Component, Release
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.sboms.models import ProductIdentifier, ProductLink

OUT_DIR = Path("/tmp/ux-review")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Widths to capture: desktop, narrow desktop, tablet, mobile.
WIDTHS = [1920, 992, 576, 375]


def _full_page_screenshot(page: Page, label: str, width: int) -> Path:
    page.set_viewport_size({"width": width, "height": 1080})
    page.wait_for_timeout(600)
    page.set_viewport_size({"width": width, "height": page.evaluate("document.body.parentNode.scrollHeight")})
    page.wait_for_timeout(400)
    out = OUT_DIR / f"{label}__{width}.jpg"
    page.screenshot(path=out.as_posix(), type="jpeg", full_page=True, quality=80)
    return out


@pytest.fixture
def trust_center_product(product_factory, component_factory, sbom_factory, document_factory, team_with_business_plan):
    """Realistic trust-center product: SBOM + doc + identifiers + links + releases."""
    team_with_business_plan.is_public = True
    team_with_business_plan.save()

    name = "UX Review Product"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    product = product_factory(name=name, _id=_id, is_public=True)

    bom = component_factory(
        "Backend API",
        Component.ComponentType.BOM,
        product=product,
        visibility=Component.Visibility.PUBLIC,
    )
    sbom_factory(bom, name="backend-api-sbom.json", version="2.4.1")

    doc = component_factory(
        "Compliance Pack",
        Component.ComponentType.DOCUMENT,
        product=product,
        visibility=Component.Visibility.PUBLIC,
    )
    document_factory(doc, name="soc2-report.pdf", version="2025")

    ProductIdentifier.objects.bulk_create([
        ProductIdentifier(
            product=product,
            identifier_type=ProductIdentifier.IdentifierType.SKU,
            value="SKU-UX-001",
            team=product.team,
        ),
        ProductIdentifier(
            product=product,
            identifier_type=ProductIdentifier.IdentifierType.GTIN_13,
            value="0123456789012",
            team=product.team,
        ),
        ProductIdentifier(
            product=product,
            identifier_type=ProductIdentifier.IdentifierType.CPE,
            value="cpe:2.3:a:test:product:1.0.0:*:*:*:*:*:*:*",
            team=product.team,
        ),
    ])

    ProductLink.objects.bulk_create([
        ProductLink(
            product=product,
            link_type=ProductLink.LinkType.WEBSITE,
            title="Product Website",
            url="https://example.com",
            team=product.team,
        ),
        ProductLink(
            product=product,
            link_type=ProductLink.LinkType.REPOSITORY,
            title="GitHub Repository",
            url="https://github.com/example/product",
            team=product.team,
        ),
        ProductLink(
            product=product,
            link_type=ProductLink.LinkType.DOCUMENTATION,
            title="Documentation",
            url="https://docs.example.com",
            team=product.team,
        ),
    ])

    Release.objects.bulk_create([
        Release(product=product, name="v1.0.0", description="Initial GA release", is_latest=False, is_prerelease=False),
        Release(product=product, name="v1.1.0", description="Maintenance release", is_latest=False, is_prerelease=False),
        Release(product=product, name="v2.0.0", description="Major update — new dashboard, faster scans", is_latest=True, is_prerelease=False),
        Release(product=product, name="v2.1.0-beta", description="Beta — preview of release-channel feature", is_latest=False, is_prerelease=True),
    ])

    yield product


@pytest.fixture
def trust_center_empty(product_factory, team_with_business_plan):
    team_with_business_plan.is_public = True
    team_with_business_plan.save()

    name = "UX Review Empty"
    _id = hashlib.md5(name.encode()).hexdigest()[:12]
    yield product_factory(name=name, _id=_id, is_public=True)


@pytest.mark.django_db
@pytest.mark.parametrize("width", WIDTHS)
class TestUxReviewTrustCenter:
    def test_workspace_public(self, authenticated_page, trust_center_product, width):
        # Workspace key derived from team
        team = trust_center_product.team
        authenticated_page.goto(f"/public/workspace/{team.key}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "workspace_public", width)

    def test_product_details_public(self, authenticated_page, trust_center_product, width):
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "product_details_public", width)

    def test_product_details_public_empty(self, authenticated_page, trust_center_empty, width):
        authenticated_page.goto(f"/public/product/{trust_center_empty.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "product_details_public_empty", width)

    def test_product_releases_public(self, authenticated_page, trust_center_product, width):
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/releases/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "product_releases_public", width)

    def test_release_details_public(self, authenticated_page, trust_center_product, width):
        latest = trust_center_product.releases.filter(is_latest=True).first()
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{latest.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "release_details_public_latest", width)

    def test_release_details_public_prerelease(self, authenticated_page, trust_center_product, width):
        pre = trust_center_product.releases.filter(is_prerelease=True).first()
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{pre.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "release_details_public_prerelease", width)

    def test_component_details_public_sbom(self, authenticated_page, trust_center_product, width):
        sbom_comp = trust_center_product.components.filter(component_type=Component.ComponentType.BOM).first()
        authenticated_page.goto(f"/public/component/{sbom_comp.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "component_details_public_sbom", width)

    def test_component_details_public_document(self, authenticated_page, trust_center_product, width):
        doc_comp = trust_center_product.components.filter(component_type=Component.ComponentType.DOCUMENT).first()
        authenticated_page.goto(f"/public/component/{doc_comp.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        _full_page_screenshot(authenticated_page, "component_details_public_document", width)
