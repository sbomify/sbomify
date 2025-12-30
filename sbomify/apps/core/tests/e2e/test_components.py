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

        sbom_upload_area = authenticated_page.locator(".sbom-upload-area")
        sbom_upload_header = authenticated_page.locator(".sbom-upload-header")
        if sbom_upload_header.is_visible():
            if sbom_upload_area.is_hidden():
                sbom_upload_header.click()
        
        sbom_upload_area.wait_for(state="visible")
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

        # Ensure the document upload section is expanded
        document_version = authenticated_page.locator("#document-version")
        if document_version.is_hidden():
            authenticated_page.locator(".document-upload-wrapper h4").click()
        document_version.wait_for(state="visible")
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
