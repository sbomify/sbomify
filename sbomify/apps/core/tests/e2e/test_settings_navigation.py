"""Settings stay functional when rendered initially and after partial navigation."""

import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.teams.models import ContactProfile

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_settings_controls_and_navigation(
    authenticated_page: Page, team_with_business_plan: Any, width: int, theme: str, settings: Any, mocker: Any
) -> None:
    settings.BILLING = True
    mocker.patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe")
    mocker.patch(
        "sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing",
        return_value={"amount": "$15", "period": "/month", "billing_period": "monthly"},
    )
    mocker.patch(
        "sbomify.apps.billing.stripe_pricing_service.StripePricingService._refresh_pricing_from_stripe", return_value={}
    )
    workspace = team_with_business_plan
    workspace.is_public = True
    workspace.save(update_fields=["is_public"])
    ContactProfile.objects.create(team=workspace, name="Product contacts", is_default=True)
    page = authenticated_page
    errors: list[str] = []
    console: list[str] = []
    page.on("console", lambda message: console.append(message.text) if message.type in ("error", "warning") else None)
    page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"/workspaces/{workspace.key}/settings/general")
    name = page.get_by_role("textbox", name="Workspace name", exact=True)
    expect(name).to_have_value(workspace.name)
    name.fill("Unsaved workspace name")
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(name).to_have_value(workspace.name)
    name.fill("Draft workspace name")
    page.get_by_label("Patch targets", exact=True).select_option("custom")
    page.get_by_label("Critical (days)", exact=True).fill("0")
    page.get_by_label("High (days)", exact=True).fill("14")
    page.get_by_label("Medium (days)", exact=True).fill("")
    page.get_by_role("button", name="Save patch targets", exact=True).click()
    expect(page.get_by_text("Patch targets updated", exact=True)).to_be_visible()
    expect(page.locator("#patch-sla-wrapper")).not_to_have_class(re.compile("htmx-settling"))
    expect(page.get_by_label("Critical (days)", exact=True)).to_have_value("0")
    expect(name).to_have_value("Draft workspace name")
    page.get_by_label("Freshness window (days)").fill("0")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_text("Workspace settings updated successfully", exact=True)).to_be_visible()
    expect(page.locator("#team-general-content")).to_have_attribute("data-team-name", "Draft workspace name")
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
    expect(name).to_have_value("Draft workspace name")
    workspace.refresh_from_db()
    assert workspace.name == "Draft workspace name"
    assert workspace.sbom_freshness_days == 0
    assert workspace.patch_sla_days["critical"] == 0
    navigation = page.get_by_role("navigation", name="Settings sections")
    for label in (
        "Members",
        "API tokens",
        "Parties",
        "Trust Center",
        "Controls",
        "Branding",
        "Billing",
        "Account",
        "General",
    ):
        page.locator("#main-content").evaluate("el => el.scrollTop = 0")
        navigation.get_by_role("link", name=label, exact=True).click()
        expect(page.get_by_role("region", name=f"{label} settings", exact=True)).to_be_visible()
        expect(navigation.get_by_role("link", name=label, exact=True)).to_have_attribute("aria-current", "page")
        expect(navigation.get_by_role("link", name=label, exact=True)).to_be_in_viewport(ratio=1)
        expect(page.locator("#settings-content")).not_to_have_class(re.compile("htmx-settling"))
        # The replacement frame retains the canvas gap after every tab swap.
        assert navigation.evaluate(
            "el => el.getBoundingClientRect().top - el.previousElementSibling.getBoundingClientRect().bottom"
        ) == pytest.approx(24)
        assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
        assert page.locator("#main-content").evaluate("el => el.scrollTop") == 0
        if label == "API tokens":
            page.get_by_role("button", name="Generate token", exact=True).click()
            dialog = page.get_by_role("dialog", name="Generate token", exact=True)
            expect(dialog).to_be_visible()
            dialog.get_by_label("Token name", exact=True).fill("Browser test token")
            dialog.get_by_label("Expiration", exact=True).select_option("custom")
            dialog.get_by_label("Expires after", exact=True).fill("8")
            assert dialog.locator("form").evaluate("el => el.checkValidity()")
            with page.expect_response(
                lambda response: response.request.method == "POST" and "/tokens" in response.url
            ) as created:
                dialog.get_by_role("button", name="Generate token", exact=True).click()
            assert created.value.status == 200
            expect(dialog).to_be_hidden()
            assert "error" not in created.value.headers.get("hx-trigger", ""), created.value.headers.get("hx-trigger")
            expect(page.get_by_text("Copy your token now", exact=True)).to_be_visible()
            expect(
                page.get_by_role("region", name="API tokens settings").get_by_text("Browser test token", exact=True)
            ).to_be_visible()
        if label == "Trust Center":
            expect(page.get_by_label("Enable security.txt", exact=True)).to_be_visible()
            expect(page.locator("#company_nda_file")).to_have_attribute("required", "")
        if label == "Parties":
            expect(page.get_by_text("Product contacts", exact=True)).to_be_visible()
            search = page.get_by_role("searchbox", name="Search contact profiles")
            search.fill("No matching profile")
            expect(page.get_by_text("No matches found", exact=True)).to_be_visible()
            search.fill("")
            page.get_by_role("button", name="Profile actions", exact=True).click()
            page.get_by_role("menuitem", name="Edit profile", exact=True).click()
            expect(page.get_by_role("textbox", name=re.compile("Profile Name"))).to_have_value("Product contacts")
            entities = page.locator("#entities-container")
            expect(entities).to_be_hidden()
            # An empty list cannot create a second gap before the empty state.
            assert entities.evaluate("""list => {
                const notice = list.parentElement.querySelector('[role="alert"]');
                return list.nextElementSibling.getBoundingClientRect().top - notice.getBoundingClientRect().bottom;
            }""") == pytest.approx(16)
            page.get_by_role("button", name="Add Entity", exact=True).first.click()
            expect(entities).to_be_visible()
            page.get_by_role("button", name="Back to profiles", exact=True).click()
            expect(page.get_by_text("Product contacts", exact=True)).to_be_visible()
        if label == "Branding":
            expect(page.get_by_role("textbox", name="Brand color", exact=True)).not_to_have_value("")
            page.get_by_role("textbox", name="Brand color", exact=True).fill("#123456")
            expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_enabled()
            page.get_by_role("button", name="Discard", exact=True).click()
            expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
        if label == "Account":
            expect(
                page.get_by_role("button", name="Dark" if theme == "dark" else "Light", exact=True)
            ).to_have_attribute("aria-pressed", "true")
    page.go_back()
    expect(page.get_by_role("region", name="Account settings")).to_be_visible()
    page.go_forward()
    expect(name).to_have_value("Draft workspace name")
    navigation.get_by_role("link", name="API tokens", exact=True).click()
    expect(
        page.get_by_role("region", name="API tokens settings").get_by_text("Browser test token", exact=True)
    ).to_be_visible()
    expect(page.get_by_text("Copy your token now", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Delete token Browser test token", exact=True).click()
    dialog = page.get_by_role("alertdialog", name="Delete Token", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Delete Token", exact=True).click()
    expect(
        page.get_by_role("region", name="API tokens settings").get_by_text("Browser test token", exact=True)
    ).to_have_count(0)
    assert not errors, "\n".join([*errors, *console])
