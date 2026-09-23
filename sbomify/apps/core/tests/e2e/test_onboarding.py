from typing import Any

import pytest
from playwright.sync_api import Page, expect
from pytest_django.fixtures import SettingsWrapper
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.teams.models import ContactProfileContact, Team


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestOnboardingWizardSnapshot:
    """The onboarding wizard, the one full page that lives under
    core/components/. Welcome is the animated brand logo and the value list;
    setup is the whole form set with its labels, hints and alert."""

    def test_onboarding_welcome_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/workspaces/onboarding/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_onboarding_setup_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/workspaces/onboarding/?step=setup")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
def test_onboarding_saves_security_choices(
    authenticated_page: Page, team_with_business_plan: Team, settings: SettingsWrapper, width: int
) -> None:
    settings.BILLING = False
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/workspaces/onboarding/?step=setup")
    page.get_by_label("Organisation name *", exact=True).fill("Example Software")
    page.get_by_label("Your name *", exact=True).fill("Example Author")
    page.get_by_label("Contact email", exact=True).fill("author@example.com")
    page.get_by_role("button", name="Registered address", exact=True).click()
    page.get_by_label("Registered address", exact=True).fill("1 Example Street")
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(page.get_by_role("heading", name="Your security promises")).to_be_visible()
    expect(page.get_by_role("heading", name="Your security promises")).to_be_in_viewport()
    security = page.get_by_label("Vulnerability reports go to", exact=True)
    expect(security).to_have_value("author@example.com")
    security.fill("security@example.com")
    page.get_by_role("button", name="Back", exact=True).click()
    expect(page.get_by_label("Organisation name *", exact=True)).to_have_value("Example Software")
    expect(page.get_by_role("heading", name="Who are you?", exact=True)).to_be_in_viewport()
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(security).to_have_value("security@example.com")
    page.get_by_label("Publish this email in my Trust Center's security.txt").check()
    page.get_by_label("Default support period (years)", exact=True).fill("7")
    page.get_by_label("Maximum time to fix", exact=True).select_option("custom")
    page.get_by_label("Critical (days)", exact=True).fill("3")
    assert page.locator("html").evaluate("el => el.scrollWidth <= el.clientWidth")
    page.get_by_role("button", name="Save and continue", exact=True).click()
    expect(page.get_by_role("heading", name="Your workspace is set up")).to_be_visible()
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.default_support_period_years == 7
    assert team_with_business_plan.patch_sla_days["critical"] == 3
    assert team_with_business_plan.security_txt_config["enabled"]
    assert ContactProfileContact.objects.filter(
        entity__profile__team=team_with_business_plan, email="security@example.com", is_security_contact=True
    ).exists()
    page.get_by_role("link", name="Go to dashboard", exact=True).click()
    expect(page.get_by_role("heading", name="Set up your first repository", exact=True)).to_be_visible()
    expect(page.locator("#navbar-search-dropdown")).to_be_hidden()
    assert errors == []


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_onboarding_security_snapshot(authenticated_page: Page, snapshot: Any, width: int, theme: str) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.goto("/workspaces/onboarding/?step=setup")
    page.get_by_label("Organisation name *", exact=True).fill("Example Software")
    page.get_by_role("button", name="Continue", exact=True).click()
    page.get_by_label("Maximum time to fix", exact=True).select_option("custom")
    page.wait_for_load_state("networkidle")
    baseline = snapshot.get_or_create_baseline_screenshot(page, width=width)
    current = snapshot.take_screenshot(page, width=width)
    snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
def test_onboarding_plan_snapshot(authenticated_page: Page, priced_plans: Team, snapshot: Any, width: int) -> None:
    priced_plans.has_selected_billing_plan = False
    priced_plans.save(update_fields=["has_selected_billing_plan"])
    authenticated_page.goto("/workspaces/onboarding/?step=plan")
    authenticated_page.wait_for_load_state("networkidle")
    baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
    current = snapshot.take_screenshot(authenticated_page, width=width)
    snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
def test_onboarding_community_plan_finishes_without_checkout(
    authenticated_page: Page, priced_plans: Team, settings: SettingsWrapper, mocker: MockerFixture
) -> None:
    settings.BILLING = True
    priced_plans.has_selected_billing_plan = False
    priced_plans.billing_plan = "community"
    priced_plans.billing_plan_limits = {}
    priced_plans.save(update_fields=["has_selected_billing_plan", "billing_plan", "billing_plan_limits"])
    checkout = mocker.patch("sbomify.apps.billing.stripe_pricing_service.StripePricingService.create_checkout_session")
    page = authenticated_page
    page.goto("/workspaces/onboarding/?step=setup")
    page.get_by_label("Organisation name *", exact=True).fill("Example Software")
    page.get_by_role("button", name="Continue", exact=True).click()
    page.get_by_role("button", name="Save and continue", exact=True).click()
    page.get_by_role("link", name="Choose your plan", exact=True).click()
    page.get_by_role("button", name="Annual", exact=True).click()
    expect(page.locator("form input[name=billing_period]").first).to_have_value("annual")
    page.get_by_role("button", name="Continue with Community", exact=True).click()
    expect(page.get_by_role("heading", name="Set up your first repository", exact=True)).to_be_visible()
    priced_plans.refresh_from_db()
    assert priced_plans.has_completed_wizard
    assert priced_plans.has_selected_billing_plan
    checkout.assert_not_called()
