"""The shared workspace and plan cards preserve their navigation and guards."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from playwright.sync_api import Page, Route, expect

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.models import Product, User
from sbomify.apps.teams.models import Member, Team

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures", "sbomify.apps.core.tests.e2e.test_billing_pages"]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_plan_comparison(authenticated_page: Page, priced_plans: Team, width: int, theme: str, tmp_path: Path) -> None:
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(reverse("billing:select_plan", args=[priced_plans.key]))
    business = page.get_by_role("region", name="Business plan", exact=True)
    expect(business.get_by_text("Current plan", exact=True)).to_be_visible()
    expect(business.get_by_text("Billed monthly", exact=True)).to_be_visible()
    expect(business.get_by_text("$159", exact=True)).to_be_visible()
    expect(business.get_by_text("10 members", exact=True)).to_be_visible()
    expect(business.get_by_text("Launch offer: 20% off", exact=True).first).to_be_visible()
    annual = page.get_by_role("button", name="Annual", exact=True)
    annual.focus()
    page.keyboard.press("Enter")
    expect(annual).to_have_attribute("aria-pressed", "true")
    expect(business.get_by_text("$1,592", exact=True)).to_be_visible()
    expect(business.get_by_text("Billed monthly", exact=True)).to_be_hidden()
    expect(business.get_by_text("Billed once a year", exact=True)).to_be_visible()
    expect(
        page.get_by_role("region", name="Enterprise plan").get_by_text("Unlimited members", exact=True)
    ).to_be_visible()
    question = page.get_by_role("button", name="How does annual billing work?", exact=True)
    question.click()
    expect(question).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_text("The annual price is charged once a year.", exact=False)).to_be_visible()
    assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
    if width == 1280:
        buttons = [
            page.get_by_role("region", name=f"{plan} plan").get_by_role("button").bounding_box()
            for plan in ("Community", "Business", "Enterprise")
        ]
        assert max(box["y"] for box in buttons if box) - min(box["y"] for box in buttons if box) < 2
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(tmp_path / f"plans-{theme}-{width}.png"), full_page=True, animations="disabled")
    assert not errors


@pytest.mark.parametrize("flow", ["checkout", "manage", "downgrade", "enterprise"])
def test_plan_navigation_uses_existing_endpoints(authenticated_page: Page, priced_plans: Team, flow: str) -> None:
    page = authenticated_page
    workspace = priced_plans
    if flow == "checkout":
        workspace.billing_plan = "community"
        workspace.billing_plan_limits = {"billing_period": "annual"}
        workspace.save(update_fields=["billing_plan", "billing_plan_limits"])
    requests = []

    def intercept(route: Route) -> None:
        requests.append(route.request)
        route.fulfill(content_type="text/html", body="<h1>Billing flow preview</h1>")

    select_url = reverse("billing:select_plan", args=[workspace.key])
    if flow == "checkout":

        def checkout(route: Route) -> None:
            if route.request.method == "POST":
                intercept(route)
            else:
                route.continue_()

        page.route(f"**{select_url}", checkout)
    else:
        target = (
            reverse("billing:enterprise_contact")
            if flow == "enterprise"
            else reverse("billing:create_portal_session", args=[workspace.key])
        )
        page.route(f"**{target}*", intercept)
    page.goto(select_url)
    plan = "Community" if flow == "downgrade" else "Enterprise" if flow == "enterprise" else "Business"
    page.get_by_role("region", name=f"{plan} plan").get_by_role("button").click()
    expect(page.get_by_role("heading", name="Billing flow preview")).to_be_visible()
    assert len(requests) == 1
    request = requests[0]
    if flow == "checkout":
        payload = parse_qs(request.post_data or "")
        assert payload["plan"] == ["business"]
        assert payload["billing_period"] == ["annual"]
        assert payload["csrfmiddlewaretoken"][0]
    elif flow != "enterprise":
        assert parse_qs(urlparse(request.url).query)["flow_type"] == [
            "subscription_cancel" if flow == "downgrade" else "subscription_update"
        ]


@pytest.mark.parametrize("state", ["over-limit", "scheduled"])
def test_plan_downgrade_guard(authenticated_page: Page, priced_plans: Team, state: str) -> None:
    workspace = priced_plans
    if state == "over-limit":
        BillingPlan.objects.filter(key="community").update(max_products=0)
        Product.objects.create(team=workspace, name="Example product")
    else:
        workspace.billing_plan_limits["cancel_at_period_end"] = True
        workspace.save(update_fields=["billing_plan_limits"])
    page = authenticated_page
    page.goto(reverse("billing:select_plan", args=[workspace.key]))
    community = page.get_by_role("region", name="Community plan")
    expect(community.get_by_role("button")).to_be_disabled()
    expect(community.get_by_role("button")).to_have_text(
        "Over plan limits" if state == "over-limit" else "Downgrade scheduled"
    )
    if state == "over-limit":
        expect(community.get_by_text("Reduce usage to choose this plan:", exact=False)).to_be_visible()
    else:
        expect(page.get_by_text("Your plan ends on", exact=False)).to_be_visible()


@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_workspace_cards(
    authenticated_page: Page, sample_user: User, team_with_business_plan: Team, width: int, theme: str, tmp_path: Path
) -> None:
    other = Team.objects.create(name="Example engineering", billing_plan="community")
    Member.objects.create(team=other, user=sample_user, role="owner")
    readonly = Team.objects.create(
        name="A workspace with a long name for the shared research group", billing_plan="community"
    )
    Member.objects.create(team=readonly, user=sample_user, role="member")
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(reverse("teams:teams_dashboard"))
    current = page.get_by_role("region", name=re.compile(r"^Test Business Team"))
    card = page.get_by_role("region", name=re.compile(r"^Example engineering"))
    member_card = page.get_by_role("region", name=re.compile(r"^A workspace with a long name"))
    expect(current.get_by_text("Current", exact=True)).to_be_visible()
    expect(current).to_have_attribute("data-current", "true")
    expect(card).to_have_attribute("data-current", "false")
    expect(current.get_by_text("Default", exact=True)).to_be_visible()
    expect(page.get_by_text("0 pending invitations", exact=True)).to_have_count(0)
    expect(card.get_by_role("link", name="Settings", exact=True)).to_have_attribute(
        "href", reverse("teams:team_settings", args=[other.key])
    )
    member_card.get_by_role("button", name=re.compile(r"^Actions for")).click()
    expect(page.get_by_role("menuitem", name="Delete workspace", exact=True)).to_be_hidden()
    page.keyboard.press("Escape")
    card.get_by_role("button", name=re.compile(r"^Actions for")).click()
    page.get_by_role("menuitem", name="Make default", exact=True).click()
    expect(card.get_by_text("Default", exact=True)).to_be_visible()
    expect(current.get_by_text("Current", exact=True)).to_be_visible()
    assert Member.objects.get(team=other, user=sample_user).is_default_team
    card.get_by_role("button", name=re.compile(r"^Actions for")).click()
    expect(page.get_by_role("menuitem", name="Default workspace", exact=True)).to_be_disabled()
    expect(page.get_by_role("menuitem", name="Delete workspace", exact=True)).to_be_hidden()
    page.keyboard.press("Escape")
    assert page.locator("html").evaluate("el => el.scrollWidth <= innerWidth")
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(tmp_path / f"workspaces-{theme}-{width}.png"), full_page=True, animations="disabled")
    card.get_by_role("link", name="Open workspace", exact=True).click()
    page.goto(reverse("teams:teams_dashboard"))
    expect(card.get_by_text("Current", exact=True)).to_be_visible()
    assert not errors


def test_workspace_create_and_delete(authenticated_page: Page, sample_user: User) -> None:
    workspace = Team.objects.create(name="Example temporary workspace", billing_plan="community")
    Member.objects.create(team=workspace, user=sample_user, role="owner")
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(reverse("teams:teams_dashboard"))
    page.get_by_role("region", name=re.compile(r"^Example temporary workspace")).get_by_role(
        "button", name=re.compile(r"^Actions for")
    ).click()
    page.get_by_role("menuitem", name="Delete workspace", exact=True).click()
    dialog = page.get_by_role("alertdialog", name="Delete workspace", exact=True)
    expect(dialog).to_be_visible()
    with page.expect_navigation(wait_until="load"):
        dialog.get_by_role("button", name="Delete workspace", exact=True).click()
    expect(page.get_by_role("region", name=re.compile(r"^Example temporary workspace"))).to_have_count(0)
    assert not Team.objects.filter(pk=workspace.pk).exists()
    expect(page.locator("#add-workspace-modal-dialog")).to_be_attached()
    page.locator("#toast-container").get_by_role("button", name="Dismiss", exact=True).click()
    page.get_by_role("button", name="Add workspace", exact=True).click()
    create = page.get_by_role("dialog", name="Add Workspace", exact=True)
    expect(create).to_be_visible()
    create.get_by_role("textbox", name="Name *", exact=True).fill("Example new workspace")
    with page.expect_navigation(wait_until="load"):
        create.get_by_role("button", name="Add Workspace", exact=True).click()
    page.goto(reverse("teams:teams_dashboard"))
    expect(page.get_by_role("region", name=re.compile(r"^Example new workspace"))).to_be_visible()
    assert Member.objects.filter(team__name="Example new workspace", user=sample_user, role="owner").exists()
    assert not errors
