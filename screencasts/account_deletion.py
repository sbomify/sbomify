"""Record the user account deletion screencast.

Drives: Dashboard → sidebar Settings → Account tab → Danger zone →
Delete account modal → type 'delete' → confirm → redirect to sign in.
"""

import playwright.sync_api
import pytest
from playwright.sync_api import Page

from conftest import (
    SPLASH_HTML,
    caption,
    clear_caption,
    hover_and_click,
    mock_vuln_trends,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
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
    caption(page, "Here is how to delete your sbomify account.")
    clear_caption(page)

    navigate_to_settings(page)
    navigate_to_settings_tab(page, "account")
    caption(page, "Open Settings, then the Account tab. It shows your sign-in details and preferences.")

    danger_band = page.get_by_role("button", name="Danger zone")
    danger_band.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, danger_band, 600)
    caption(page, "Account deletion sits in the danger zone at the bottom.", block=False)
    hover_and_click(page, danger_band)
    pace(page, 800)

    delete_btn = page.get_by_role("button", name="Delete your account")
    delete_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, delete_btn)

    modal = page.locator("#deleteAccountModal")
    confirm_input = page.locator("#delete-account-confirm")
    confirm_input.wait_for(state="visible", timeout=5_000)
    pace(page, 400)
    caption(
        page,
        "The dialog lists what happens. Your account is deactivated right away, and your access tokens are revoked.",
    )
    caption(page, "Workspaces where you are the only member are deleted too.")
    caption(page, "You have 14 days to change your mind. After that, the account is deleted for good.")

    caption(page, "To confirm, type delete.", block=False)
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
    caption(page, "Your account is deleted, and you are signed out.")
    pace(page, 1000)
