import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSupportContactSnapshot:
    """The support form and the page it lands on once it is sent. Neither
    needs any data beyond the signed-in user."""

    def test_support_contact_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/support/contact/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_support_contact_success_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/support/contact/success/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
