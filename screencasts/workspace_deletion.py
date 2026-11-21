"""Record the workspace deletion screencast.

Drives: Dashboard → sidebar Settings → General tab → Danger zone →
Delete workspace modal → type 'delete' → confirm → redirect back to dashboard.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    narrate,
    navigate_to_settings,
    pace,
    settle,
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

    # The opening line plays over the splash and the dashboard load.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=300)

    narrate(page, "open_settings_danger")
    navigate_to_settings(page)

    # The workspace danger zone sits at the foot of the General tab. The band
    # is the control that expands it.
    danger_band = page.get_by_role("button", name="Danger zone")
    danger_band.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, danger_band, 800)
    narrate(page, "deleting_workspace_removes")
    hover_and_click(page, danger_band)
    pace(page, 800)

    delete_btn = page.locator("button[id^='del_']")
    delete_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, delete_btn)
    pace(page, 800)

    confirm_input = page.locator("input[id^='delete-confirm-']")
    confirm_input.wait_for(state="visible", timeout=5_000)
    narrate(page, "confirm_type_delete")
    hover_and_click(page, confirm_input)
    pace(page, 400)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 600)

    confirm_delete_btn = page.locator("#deleteWorkspaceModal").get_by_role("button", name="Delete workspace")
    hover_and_click(page, confirm_delete_btn)

    page.wait_for_url("**/dashboard**", timeout=10_000)
    page.wait_for_load_state("networkidle")
    narrate(page, "workspace_gone_back")
    settle(page)
    pace(page, 600)
