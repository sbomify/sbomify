from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.fixture
def priced_plans(team_with_business_plan):  # noqa: F811
    """All three plans, priced, so the plan page renders every card it can.

    The business plan the shared fixture creates carries no prices, which
    leaves every card reading "Contact us"; giving it prices, a promotion and
    a fresh sync stamp makes the pricing service serve from the database and
    the cards render their real numbers. The renewal date turns on the
    subscription alert, and the enterprise plan brings the gradient button.
    """
    business = BillingPlan.objects.get(key="business")
    business.monthly_price = 199
    business.annual_price = 1990
    business.discount_percent_monthly = 20
    business.discount_percent_annual = 20
    business.promo_message = "Launch offer"
    business.last_synced_at = timezone.now()
    business.save()

    BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "For open source and evaluation",
            "max_products": 1,
            "max_components": 5,
            "max_users": 1,
        },
    )
    BillingPlan.objects.get_or_create(
        key="enterprise",
        defaults={
            "name": "Enterprise",
            "description": "For organisations with custom needs",
        },
    )

    limits = dict(team_with_business_plan.billing_plan_limits or {})
    limits["next_billing_date"] = (timezone.now() + timedelta(days=21)).date().isoformat()
    team_with_business_plan.billing_plan_limits = limits
    team_with_business_plan.save(update_fields=["billing_plan_limits"])

    return team_with_business_plan


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
