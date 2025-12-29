import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentsListSnapshot:
    def test_components_list_snapshot(
        self,
        authenticated_page: Page,
        dashboard,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/components/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentDetailsPrivateSnapshot:
    def test_component_details_private_sbom_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/component/{sbom_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".sbom-upload-header").click()
        authenticated_page.locator(".dangerzone-card h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_component_details_private_document_snapshot(
        self,
        authenticated_page: Page,
        document_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/component/{document_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".document-upload-wrapper h4").click()
        authenticated_page.locator(".dangerzone-card h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentDetailsPublicSnapshot:
    def test_component_details_public_sbom_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/component/{sbom_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_component_details_public_document_snapshot(
        self,
        authenticated_page: Page,
        document_component_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/component/{document_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
