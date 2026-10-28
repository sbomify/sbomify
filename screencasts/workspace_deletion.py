"""Record the workspace deletion screencast.

Drives: Dashboard → sidebar Settings → General tab → Danger zone →
Delete workspace modal → type 'delete' → confirm → redirect back to dashboard.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    caption,
    clear_caption,
    hover_and_click,
    navigate_to_settings,
    pace,
    smooth_scroll,
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

    start_on_dashboard(page)
    caption(page, "Here is how to delete a workspace in sbomify. Only the workspace owner can do this.")
    clear_caption(page)

    navigate_to_settings(page)

    # The workspace danger zone sits at the foot of the General tab. The band
    # is the control that expands it.
    danger_band = page.get_by_role("button", name="Danger zone")
    danger_band.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, danger_band, 800)
    caption(page, "Open Settings. The danger zone is at the bottom of the General tab.")
    hover_and_click(page, danger_band)
    pace(page, 800)

    delete_btn = page.locator("button[id^='del_']")
    delete_btn.wait_for(state="visible", timeout=5_000)
    caption(page, "Deleting a workspace removes every product, component and artifact in it.", block=False)
    hover_and_click(page, delete_btn)
    pace(page, 800)

    confirm_input = page.locator("input[id^='delete-confirm-']")
    confirm_input.wait_for(state="visible", timeout=5_000)
    caption(page, "To confirm, type delete.", block=False)
    hover_and_click(page, confirm_input)
    pace(page, 400)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 600)

    confirm_delete_btn = page.locator("#deleteWorkspaceModal").get_by_role("button", name="Delete workspace")
    hover_and_click(page, confirm_delete_btn)

    page.wait_for_url("**/dashboard**", timeout=10_000)
    page.wait_for_load_state("networkidle")
    caption(page, "The workspace is gone, and you are back on the dashboard of your default workspace.")
    pace(page, 1500)
