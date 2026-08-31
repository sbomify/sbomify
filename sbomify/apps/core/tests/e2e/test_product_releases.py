import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductReleasesPrivateSnapshot:
    """A product's own releases page. The product_details fixture gives it a
    latest release, a pre-release and a plain one, so the list and the count
    chip both have something to show."""

    def test_product_releases_private_snapshot(
        self,
        authenticated_page: Page,
        product_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/product/{product_details.id}/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
