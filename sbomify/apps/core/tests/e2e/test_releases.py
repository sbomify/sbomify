import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleasesListSnapshot:
    def test_releases_list_snapshot(
        self,
        authenticated_page: Page,
        dashboard,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductReleasesPrivateSnapshot:
    def test_product_releases_private_snapshot(
        self,
        authenticated_page: Page,
        product_with_releases,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/product/{product_with_releases.id}/releases/")
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
        product_with_releases,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/product/{product_with_releases.id}/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleaseDetailsPrivateSnapshot:
    def test_release_details_private_snapshot(
        self,
        authenticated_page: Page,
        release_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/product/{release_details.product.id}/release/{release_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".vc-release-danger-zone h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_release_details_private_snapshot__when_empty(
        self,
        authenticated_page: Page,
        empty_release_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/product/{empty_release_details.product.id}/release/{empty_release_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".vc-release-danger-zone h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleaseDetailsPublicSnapshot:
    def test_release_details_public_snapshot(
        self,
        authenticated_page: Page,
        release_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/product/{release_details.product.id}/release/{release_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_release_details_public_snapshot__when_empty(
        self,
        authenticated_page: Page,
        empty_release_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(
            f"/public/product/{empty_release_details.product.id}/release/{empty_release_details.id}/"
        )
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
