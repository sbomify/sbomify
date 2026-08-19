"""Record the workspace deletion screencast.

Drives: Dashboard → sidebar Settings → General tab → Danger Zone →
Delete Workspace modal → type 'delete' → confirm → redirect back to dashboard.
"""

import re

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    narrate,
    navigate_to_settings,
    pace,
    settle,
    start_on_dashboard,
    type_text,
)


@pytest.mark.django_db(transaction=True)
def workspace_deletion(recording_page: Page) -> None:
    page = recording_page

    # Intercept the vulnerability-trends endpoint with an empty div to prevent
    # errors after the workspace is deleted (the real endpoint would 400).
    page.route(
        "**/vulnerability-trends/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body="<div></div>"),
    )

    # Start on the dashboard so the viewer sees familiar surroundings
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=400)

    # Click "Settings" in the sidebar
    narrate(page, "settings")
    navigate_to_settings(page)

    # Wait for the HTMX-loaded General tab content (danger zone lives here).
    # Every danger zone is one c-cards.dangerzone-collapsible now: the band that
    # opens it is a role="button" carrying the title, and the account zone lives
    # on its own settings URL, so nothing else on this page answers to it.
    danger_band = page.get_by_role("button", name=re.compile(r"Danger Zone"))
    danger_band.wait_for(state="visible", timeout=15_000)

    # Scroll to the danger zone and expand it
    narrate(page, "expand")
    danger_band.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 600)
    hover_and_click(page, danger_band)
    pace(page, 800)

    # Click "Delete Workspace" to open the modal.  The row's button carries
    # id="del_<team key>", which the modal's own confirm does not.
    delete_btn = page.locator("button[id^='del_']")
    delete_btn.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, delete_btn)
    pace(page, 600)

    # Type "delete" character-by-character for a human-like feel.
    # Use the workspace-specific confirm input (id starts with "delete-confirm-")
    # to avoid matching the account deletion modal's input.
    narrate(page, "confirm")
    confirm_input = page.locator("input[id^='delete-confirm-']")
    confirm_input.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, confirm_input)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 600)

    # Click "Delete Workspace" in the modal footer
    narrate(page, "outro")
    confirm_delete_btn = page.get_by_role("button", name="Delete Workspace", exact=True)
    hover_and_click(page, confirm_delete_btn)

    # Wait for redirect back to the dashboard
    page.wait_for_url("**/dashboard**", timeout=10_000)
    page.wait_for_load_state("networkidle")
    settle(page)
