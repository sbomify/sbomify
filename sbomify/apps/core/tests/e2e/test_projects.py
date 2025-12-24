import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProjectsListSnapshot:
    def test_projects_list_snapshot(
        self,
        authenticated_page: Page,
        dashboard,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/projects/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProjectDetailsSnapshot:
    def test_project_details_snapshot(
        self,
        authenticated_page: Page,
        project_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/project/{project_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".vc-project-danger-zone h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_project_details_snapshot__when_empty(
        self,
        authenticated_page: Page,
        empty_project_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/project/{empty_project_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".vc-project-danger-zone h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProjectPublicDetailsSnapshot:
    def test_project_public_details_snapshot(
        self,
        authenticated_page: Page,
        project_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/project/{project_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_project_public_details_snapshot__when_empty(
        self,
        authenticated_page: Page,
        empty_project_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/project/{empty_project_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
