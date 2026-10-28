"""Record the compliance controls screencast.

Drives: Dashboard → Settings → Controls tab → activate SOC 2 Type II → set a
whole category's workspace default, then one control → Products → the product's
Compliance tab → override one control for this product → the public Trust
Center's Compliance frameworks section.
"""

import re

import pytest
from django.urls import reverse
from playwright.sync_api import Locator, Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    caption,
    clear_caption,
    hover_and_click,
    navigate_to_products,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.teams.models import Team

FRAMEWORK = "SOC 2 Type II"


@pytest.fixture
def controls_workspace(pied_piper_with_sboms: dict, sample_user) -> dict:
    team: Team = pied_piper_with_sboms["product"].team
    team.name = "Pied Piper"
    team.is_public = True
    team.save(update_fields=["name", "is_public"])
    sample_user.first_name = "Richard"
    sample_user.last_name = "Hendricks"
    sample_user.save(update_fields=["first_name", "last_name"])
    product = pied_piper_with_sboms["product"]
    product.is_public = True
    product.save(update_fields=["is_public"])
    return pied_piper_with_sboms


def _category(table: Locator, name: str) -> Locator:
    """The accordion item button for a control category."""
    return table.get_by_role("button", name=re.compile(rf"^{name} \(\d+\)"))


@pytest.mark.django_db(transaction=True)
def compliance_controls(controls_workspace: dict, recording_page: Page) -> None:
    page = recording_page
    team = controls_workspace["product"].team
    page.on("dialog", lambda dialog: dialog.accept())

    start_on_dashboard(page, 800)
    caption(page, "Here is how to track compliance controls in sbomify, for the workspace and for each product.")
    clear_caption(page)

    navigate_to_settings(page)
    navigate_to_settings_tab(page, "controls")
    activate = page.get_by_role("button", name=f"Activate {FRAMEWORK}")
    smooth_scroll(page, activate, 600)
    caption(page, "The Controls tab lists the frameworks you can work to, such as SOC 2, ISO 27001 and NIST.")
    caption(page, "Activate SOC 2 Type II.", block=False)
    hover_and_click(page, activate)
    page.wait_for_load_state("networkidle")

    table = page.locator("[id^='controls-table-']").first
    table.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    caption(page, "Its controls are grouped by category. Every product inherits these statuses as its defaults.")

    availability = _category(table, "Availability")
    hover_and_click(page, availability)
    pace(page, 800)
    bulk = table.locator("form", has=page.locator("input[name='category'][value='Availability']")).filter(
        has=page.locator("input[name='status'][value='compliant']")
    )
    caption(page, "Set a whole category at once.", block=False)
    with page.expect_response(lambda r: "bulk-category" in r.url):
        hover_and_click(page, bulk.get_by_role("button"))
    pace(page, 1200)

    confidentiality = _category(table, "Confidentiality")
    hover_and_click(page, confidentiality)
    pace(page, 800)
    status = table.locator("select[aria-label^='Status for C1']").first
    smooth_scroll(page, status, 400)
    caption(page, "Or set a single control. This one is only partly in place.", block=False)
    with page.expect_response(lambda r: r.url.endswith("/status") and r.request.method == "POST"):
        status.select_option("partial")
    pace(page, 1200)
    clear_caption(page)

    navigate_to_products(page)
    product_link = page.locator("main").get_by_role("link", name=PIED_PIPER_PRODUCT_NAME).first
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    compliance_tab = page.get_by_role("tab", name="Compliance")
    hover_and_click(page, compliance_tab)
    product_table = page.locator("#product-controls-panel [id^='controls-table-']").first
    product_table.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, product_table, 800)
    caption(page, "Each product has a Compliance tab with the same checklist, starting from the workspace defaults.")

    hover_and_click(page, _category(product_table, "Availability"))
    pace(page, 800)
    product_status = product_table.locator("select[aria-label^='Status for A1']").first
    smooth_scroll(page, product_status, 400)
    caption(page, "Override a control where this product differs, and it is marked as a product override.", block=False)
    with page.expect_response(lambda r: r.url.endswith("/status") and r.request.method == "POST"):
        product_status.select_option("not_applicable")
    page.locator("#product-controls-panel").get_by_text("Product override").first.wait_for(
        state="visible", timeout=10_000
    )
    pace(page, 1500)
    clear_caption(page)

    page.goto(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))
    page.wait_for_load_state("networkidle")
    frameworks = page.locator("#frameworks")
    frameworks.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, frameworks, 800)
    caption(page, "Active frameworks also show on your Trust Center, with how much of each is in place.")
    pace(page, 800)
