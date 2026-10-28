"""Record the user account deletion screencast.

Drives: Dashboard → sidebar Settings → Account tab → Danger zone →
Delete account modal → type 'delete' → confirm → redirect to sign in.
"""

import playwright.sync_api
import pytest
from playwright.sync_api import Page

from conftest import (
    SPLASH_HTML,
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)


@pytest.mark.django_db(transaction=True)
def account_deletion(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page

    # After deletion the app sends the browser to /login/, which hands off to
    # the identity provider. The test stack has none, so the page would render
    # blank white; show the branded splash in its place.
    page.route("**/login/**", lambda route: route.fulfill(status=200, content_type="text/html", body=SPLASH_HTML))
    mock_vuln_trends(page)
    start_on_dashboard(page)
    narrate(page, "intro")
    settle(page)

    navigate_to_settings(page)
    navigate_to_settings_tab(page, "account")
    narrate(page, "open_settings_account")
    settle(page)

    danger_band = page.get_by_role("button", name="Danger zone")
    danger_band.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, danger_band, 600)
    narrate(page, "account_deletion_sits")
    hover_and_click(page, danger_band)
    pace(page, 800)

    delete_btn = page.get_by_role("button", name="Delete your account")
    delete_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, delete_btn)

    modal = page.locator("#deleteAccountModal")
    confirm_input = page.locator("#delete-account-confirm")
    confirm_input.wait_for(state="visible", timeout=5_000)
    pace(page, 400)
    narrate(page, "dialog_lists_what")
    settle(page)
    narrate(page, "workspaces_where_only")
    settle(page)
    narrate(page, "have_14_days")
    settle(page)

    narrate(page, "confirm_type_delete")
    hover_and_click(page, confirm_input)
    pace(page, 300)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 500)

    confirm_btn = modal.get_by_role("button", name="Delete my account")
    hover_and_click(page, confirm_btn)

    try:
        page.wait_for_url("**/login/**", timeout=10_000)
    except playwright.sync_api.Error:
        pass
    page.wait_for_load_state("networkidle")
    narrate(page, "account_deleted_signed")
    settle(page)
    pace(page, 1000)
