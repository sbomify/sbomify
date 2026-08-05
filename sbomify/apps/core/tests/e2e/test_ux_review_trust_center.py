"""Generates full-page screenshots for the trust-center public views.

Not a regression test — this saves screenshots to /tmp/ux-review/ so they
can be inspected manually when reviewing changes to the public pages.

Skipped by default in CI because every test passes regardless of output
(no asserts). Run locally with `RUN_UX_REVIEW=1 pytest ...` when you want
fresh screenshots.
"""

import hashlib
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import LATEST_RELEASE_NAME, Component
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403

OUT_DIR = Path("/tmp/ux-review")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_UX_REVIEW"),
    reason="UX screenshot generator — set RUN_UX_REVIEW=1 to run.",
)

# Widths to capture: desktop, narrow desktop, tablet, mobile.
WIDTHS = [1920, 992, 576, 375]


def _full_page_screenshot(page: Page, label: str, width: int) -> Path:
    # Defer dir creation to first call so the module is import-time
    # side-effect free (pytest still imports the module during collection).
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": width, "height": 1080})
    page.wait_for_timeout(600)
    page.set_viewport_size({"width": width, "height": page.evaluate("document.body.parentNode.scrollHeight")})
    page.wait_for_timeout(400)
    out = OUT_DIR / f"{label}__{width}.jpg"
    page.screenshot(path=out.as_posix(), type="jpeg", full_page=True, quality=80)
    return out


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
        # Capture a real versioned release (not the synthetic auto-`latest`).
        versioned = trust_center_product.releases.exclude(name=LATEST_RELEASE_NAME).filter(is_prerelease=False).first()
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{versioned.id}/")
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
