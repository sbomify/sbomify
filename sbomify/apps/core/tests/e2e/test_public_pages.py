"""Snapshot coverage for the public product, release and workspace pages.

test_products.py and test_components.py already referee the public product
details and public component pages. These four had no referee at all, so they
gained one here before the component-library migration touched them.
"""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import LATEST_RELEASE_NAME, Component
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestWorkspacePublicSnapshot:
    def test_workspace_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/workspace/{trust_center_product.team.key}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductReleasesPublicSnapshot:
    def test_product_releases_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleaseDetailsPublicSnapshot:
    def test_release_details_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        # A real versioned release, not the synthetic auto-managed `latest`.
        release = (
            trust_center_product.releases.exclude(name=LATEST_RELEASE_NAME).filter(is_prerelease=False).first()
        )

        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{release.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_release_details_public_prerelease_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        # The pre-release badge in the masthead only renders on this branch.
        release = trust_center_product.releases.filter(is_prerelease=True).first()

        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{release.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentItemPublicSnapshot:
    def test_component_item_public_sbom_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        component = trust_center_product.components.filter(component_type=Component.ComponentType.BOM).first()
        sbom = component.sbom_set.first()

        authenticated_page.goto(f"/public/components/{component.id}/sboms/{sbom.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
