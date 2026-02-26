"""Record the workspace deletion screencast.

Drives: Dashboard → sidebar Settings → General tab → Danger Zone →
Delete Workspace modal → type 'delete' → confirm → redirect back to dashboard.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends_with_flag,
    navigate_to_settings,
    pace,
    start_on_dashboard,
    type_text,
)


@pytest.mark.django_db(transaction=True)
def workspace_deletion(recording_page: Page) -> None:
    page = recording_page

    # Track whether the workspace has been deleted.  Before deletion the mock
    # shows realistic vulnerability data; afterwards we return an empty div so
    # the 400 error from the real endpoint never reaches the browser.
    workspace_deleted = mock_vuln_trends_with_flag(page)

    # Start on the dashboard so the viewer sees familiar surroundings
    start_on_dashboard(page)

    # Click "Settings" in the sidebar
    navigate_to_settings(page)

    # Wait for the HTMX-loaded General tab content (danger zone lives here)
    danger_header = page.locator(".tw-dangerzone-card .tw-card-header")
    danger_header.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    # Scroll to the danger zone and expand it
    danger_header.scroll_into_view_if_needed()
    pace(page, 600)
    hover_and_click(page, danger_header)
    pace(page, 800)

    # Click "Delete Workspace" to open the modal
    delete_btn = page.locator("button:has-text('Delete Workspace')").first
    hover_and_click(page, delete_btn)
    pace(page, 800)

    # Type "delete" character-by-character for a human-like feel
    confirm_input = page.locator("input[placeholder=\"Type 'delete' to confirm\"]")
    hover_and_click(page, confirm_input)
    pace(page, 400)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 600)

    # Mark workspace as deleted so the route handler returns an empty div
    workspace_deleted["value"] = True

    # Click "Delete Workspace" in the modal footer
    confirm_delete_btn = page.get_by_role("button", name="Delete Workspace", exact=True)
    hover_and_click(page, confirm_delete_btn)

    # Wait for redirect back to the dashboard
    page.wait_for_url("**/dashboard**", timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 2000)
