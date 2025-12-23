import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductsListSnapshot:
    def test_products_list_snapshot(
        self,
        authenticated_page: Page,
        live_server,
        dashboard_projects,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"{live_server.url}/products/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductDetailsSnapshot:
    def test_product_details_snapshot(
        self,
        authenticated_page: Page,
        live_server,
        product_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"{live_server.url}/product/{product_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".vc-product-danger-zone h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_product_details_snapshot__when_empty(
        self,
        authenticated_page: Page,
        live_server,
        empty_product_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"{live_server.url}/product/{empty_product_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        authenticated_page.locator(".vc-product-danger-zone h4").click()

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductPublicDetailsSnapshot:
    def test_product_public_details_snapshot(
        self,
        authenticated_page: Page,
        live_server,
        product_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"{live_server.url}/public/product/{product_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_product_public_details_snapshot__when_empty(
        self,
        authenticated_page: Page,
        live_server,
        empty_product_details,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"{live_server.url}/public/product/{empty_product_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
