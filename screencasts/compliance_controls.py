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
    hover_and_click,
    narrate,
    navigate_to_products,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
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

    # The opening line plays over the splash and the trip to Settings.
    narrate(page, "intro")
    start_on_dashboard(page, 0)
    navigate_to_settings(page)
    narrate(page, "controls_tab_lists")
    navigate_to_settings_tab(page, "controls")
    activate = page.get_by_role("button", name=f"Activate {FRAMEWORK}")
    smooth_scroll(page, activate, 600)
    narrate(page, "activate_soc_2")
    hover_and_click(page, activate)
    page.wait_for_load_state("networkidle")

    table = page.locator("[id^='controls-table-']").first
    table.wait_for(state="visible", timeout=15_000)
    narrate(page, "controls_grouped_category")
    pace(page, 1500)

    availability = _category(table, "Availability")
    hover_and_click(page, availability)
    pace(page, 800)
    bulk = table.locator("form", has=page.locator("input[name='category'][value='Availability']")).filter(
        has=page.locator("input[name='status'][value='compliant']")
    )
    narrate(page, "set_whole_category")
    with page.expect_response(lambda r: "bulk-category" in r.url):
        hover_and_click(page, bulk.get_by_role("button"))
    pace(page, 600)

    narrate(page, "set_single_control")
    confidentiality = _category(table, "Confidentiality")
    hover_and_click(page, confidentiality)
    pace(page, 600)
    status = table.locator("select[aria-label^='Status for C1']").first
    smooth_scroll(page, status, 400)
    with page.expect_response(lambda r: r.url.endswith("/status") and r.request.method == "POST"):
        status.select_option("partial")

    # Spoken over the trip to the product, so it lands on its Compliance tab.
    narrate(page, "each_product_has")
    navigate_to_products(page)
    product_link = page.locator("main").get_by_role("link", name=PIED_PIPER_PRODUCT_NAME).first
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    compliance_tab = page.get_by_role("tab", name="Compliance")
    hover_and_click(page, compliance_tab)
    product_table = page.locator("#product-controls-panel [id^='controls-table-']").first
    product_table.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, product_table, 800)

    narrate(page, "override_control_where")
    hover_and_click(page, _category(product_table, "Availability"))
    pace(page, 600)
    product_status = product_table.locator("select[aria-label^='Status for A1']").first
    smooth_scroll(page, product_status, 400)
    with page.expect_response(lambda r: r.url.endswith("/status") and r.request.method == "POST"):
        product_status.select_option("not_applicable")
    page.locator("#product-controls-panel").get_by_text("Product override").first.wait_for(
        state="visible", timeout=10_000
    )
    settle(page)

    page.goto(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))
    page.wait_for_load_state("networkidle")
    frameworks = page.locator("#frameworks")
    frameworks.wait_for(state="visible", timeout=15_000)
    pace(page, 300)
    narrate(page, "active_frameworks_also")
    smooth_scroll(page, frameworks, 800)
