import pytest
from playwright.sync_api import Page


pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSelectPlanSnapshot:
    """Plan selection: the usage strip, the billing toggle, three pricing
    cards and the FAQ accordion. The business plan is the current one, so the
    renewal alert and the manage-subscription button render too."""

    def test_select_plan_snapshot(
        self,
        authenticated_page: Page,
        priced_plans,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/billing/select-plan/{priced_plans.key}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestEnterpriseContactSnapshot:
    """The enterprise inquiry form: the gradient hero, four field groups and
    the development-mode alert that stands in for Turnstile."""

    def test_enterprise_contact_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/billing/enterprise-contact/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestCheckoutOutcomeSnapshot:
    """The two pages Stripe returns to: the paid confirmation and the
    cancelled one. Both are a single centred card with its call to action."""

    def test_checkout_success_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/billing/checkout/success/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_checkout_cancel_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/billing/checkout/cancel/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
