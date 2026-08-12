import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleasesListSnapshot:
    """The releases list. The product_details fixture gives it a latest
    release, a pre-release and a plain one, so the row badges are covered."""

    def test_releases_list_snapshot(
        self,
        authenticated_page: Page,
        product_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
