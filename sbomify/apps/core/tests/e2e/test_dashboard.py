import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestDashboardSnapshot:
    def test_dashboard_snapshot(
        self,
        authenticated_page: Page,
        dashboard_scan_results,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/dashboard")
        authenticated_page.wait_for_load_state("networkidle")

        # Canvas is not stable for screenshots here
        authenticated_page.evaluate("document.querySelector('.vulnerability-chart-canvas').style.display = 'none';")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
