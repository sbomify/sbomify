from typing import Any, Generator

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import Component, Product, Project


@pytest.fixture
def dashboard_test_data(
    team_with_business_plan,
) -> Generator[dict[str, Any], Any, None]:
    team = team_with_business_plan

    products = [Product.objects.create(name=f"Test Product {i}", team=team) for i in range(3)]
    projects = [Project.objects.create(name=f"Test Project {i}", team=team) for i in range(5)]
    components = [Component.objects.create(name=f"Test Component {i}", team=team) for i in range(7)]

    yield {
        "products": products,
        "projects": projects,
        "components": components,
        "team": team,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestDashboardSnapshot:
    def test_dashboard_snapshot(
        self,
        authenticated_page: Page,
        live_server,
        dashboard_test_data: dict,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"{live_server.url}/dashboard")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
