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


def _point_at(page: Page, locator) -> None:
    """Glide the pointer onto a part of the page the voice is describing."""
    locator.wait_for(state="visible", timeout=5_000)
    box = locator.bounding_box()
    if box is None:
        raise AssertionError(f"nothing to point at: {locator}")
    if box["y"] < 0 or box["y"] + box["height"] > page.evaluate("window.innerHeight"):
        smooth_scroll(page, locator, 600)
        box = locator.bounding_box()
        if box is None:
            raise AssertionError(f"nothing to point at: {locator}")
    page.mouse.move(box["x"] + min(box["width"] / 2, 120), box["y"] + box["height"] / 2, steps=15)
    pace(page, 300)


@pytest.mark.django_db(transaction=True)
def account_deletion(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page

    # After deletion the app sends the browser to /login/, which hands off to
    # the identity provider. The test stack has none, so the page would render
    # blank white; show the branded splash in its place.
    page.route("**/login/**", lambda route: route.fulfill(status=200, content_type="text/html", body=SPLASH_HTML))
    mock_vuln_trends(page)
    # The opening line plays over the splash and the dashboard load.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=300)

    narrate(page, "open_settings_account")
    navigate_to_settings(page)
    navigate_to_settings_tab(page, "account")

    danger_band = page.get_by_role("button", name="Danger zone")
    danger_band.wait_for(state="visible", timeout=15_000)
    narrate(page, "account_deletion_sits")
    smooth_scroll(page, danger_band, 600)
    hover_and_click(page, danger_band)
    pace(page, 800)

    delete_btn = page.get_by_role("button", name="Delete your account")
    delete_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, delete_btn)

    modal = page.locator("#deleteAccountModal")
    confirm_input = page.locator("#delete-account-confirm")
    confirm_input.wait_for(state="visible", timeout=5_000)
    pace(page, 400)
    # The dialog is read out a part at a time, with the pointer on the part
    # being spoken, so the picture follows the voice instead of holding still.
    narrate(page, "dialog_lists_what")
    _point_at(page, modal.get_by_text("Account deactivated (cannot sign in)").first)
    pace(page, 2200)
    _point_at(page, modal.get_by_text("Personal access tokens revoked").first)
    narrate(page, "workspaces_where_only")
    _point_at(page, modal.get_by_text("Workspaces where you are the sole member").first)
    narrate(page, "have_14_days")
    _point_at(page, modal.get_by_text("Account deleted for good").first)

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
    pace(page, 600)
