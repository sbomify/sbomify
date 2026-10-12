import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
def test_support_form_retains_choices_and_input_after_validation(authenticated_page: Page) -> None:
    page = authenticated_page
    page.goto("/support/contact/")
    support_type = page.get_by_label("Type of Support Request", exact=False)
    support_type.select_option("technical")
    page.get_by_label("Subject", exact=False).fill("Example question")
    page.get_by_label("Message", exact=False).fill("Short")
    page.get_by_role("button", name="Send support request", exact=True).click()
    expect(
        page.get_by_text("Please provide a more detailed message (at least 10 characters).", exact=True)
    ).to_be_visible()
    expect(support_type).to_have_value("technical")
    expect(page.get_by_label("Subject", exact=False)).to_have_value("Example question")
    expect(page.get_by_label("Message", exact=False)).to_have_value("Short")
    expect(page.locator("#main-content")).to_be_visible()


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
