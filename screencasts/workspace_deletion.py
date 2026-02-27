"""Record the workspace deletion screencast.

Drives: Dashboard → sidebar Settings → General tab → Danger Zone →
Delete Workspace modal → type 'delete' → confirm → redirect back to dashboard.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    navigate_to_settings,
    pace,
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
    start_on_dashboard(page)

    # Click "Settings" in the sidebar
    navigate_to_settings(page)

    # Wait for the HTMX-loaded General tab content (danger zone lives here).
    # Target the workspace danger zone specifically (not the account one).
    danger_card = page.locator(".tw-dangerzone-card", has_text="Delete Workspace")
    danger_card.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    # Scroll to the danger zone and expand it
    danger_card.scroll_into_view_if_needed()
    pace(page, 600)
    danger_header = danger_card.locator(".tw-card-header")
    hover_and_click(page, danger_header)
    pace(page, 800)

    # Click "Delete Workspace" to open the modal
    delete_btn = page.locator("button:has-text('Delete Workspace')").first
    hover_and_click(page, delete_btn)
    pace(page, 800)

    # Type "delete" character-by-character for a human-like feel.
    # Use the workspace-specific confirm input (id starts with "delete-confirm-")
    # to avoid matching the account deletion modal's input.
    confirm_input = page.locator("input[id^='delete-confirm-']")
    hover_and_click(page, confirm_input)
    pace(page, 400)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 600)

    # Click "Delete Workspace" in the modal footer
    confirm_delete_btn = page.get_by_role("button", name="Delete Workspace", exact=True)
    hover_and_click(page, confirm_delete_btn)

    # Wait for redirect back to the dashboard
    page.wait_for_url("**/dashboard**", timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 2000)
