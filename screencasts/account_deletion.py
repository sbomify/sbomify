"""Record the user account deletion screencast.

Drives: Dashboard → sidebar Settings → Account tab → Danger Zone →
Delete Account modal → type 'delete' → confirm → redirect to login.

The account danger zone now lives in the team settings page under the
"Account" tab, available to workspace owners.
"""

import playwright.sync_api
import pytest
from playwright.sync_api import Page

from conftest import hover_and_click, mock_vuln_trends, navigate_to_settings, pace, start_on_dashboard, type_text


@pytest.mark.django_db(transaction=True)
def account_deletion(recording_page: Page) -> None:
    page = recording_page

    # Mock vulnerability-trends on the dashboard so it looks realistic
    mock_vuln_trends(page)

    # Start on the dashboard
    start_on_dashboard(page)

    # Navigate to workspace Settings (the sidebar link)
    navigate_to_settings(page)

    # Click the "Account" tab in the settings sidebar
    account_tab = page.locator("a[data-tab='account']")
    hover_and_click(page, account_tab)
    pace(page, 1000)

    # Scroll to the Account Danger Zone section and expand it.
    # There are two danger zone cards (workspace + account); target the account one.
    danger_card = page.locator(".tw-dangerzone-card", has_text="Delete Account")
    danger_card.scroll_into_view_if_needed()
    pace(page, 600)

    # Click the header to toggle the collapsible section open
    danger_header = danger_card.locator(".tw-card-header")
    hover_and_click(page, danger_header)
    pace(page, 800)

    # Click "Delete Account" to open the modal
    delete_btn = danger_card.locator(".tw-btn-danger")
    delete_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, delete_btn)
    pace(page, 800)

    # Type "delete" character-by-character for a human-like feel.
    # The modal is teleported to <body> via x-teleport, so the input uses
    # x-model bound to the parent Alpine component.
    confirm_input = page.locator("#delete-account-confirm")
    confirm_input.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, confirm_input)
    pace(page, 400)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 600)

    # Move cursor to the "Delete My Account" button for the visual effect,
    # then trigger deletion via Alpine.  The sidebar overlaps the modal at
    # this viewport size and the button stays :disabled until Alpine's
    # reactive system processes confirmText, so we call deleteAccount()
    # directly after ensuring the data is set.
    confirm_delete_btn = page.get_by_role("button", name="Delete My Account")
    box = confirm_delete_btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(250)

    # Trigger the deletion via Alpine's API — ensures canConfirm is true.
    # Don't await: the function sets window.location.href which triggers a
    # navigation, and page.evaluate() can't resolve across navigations.
    page.evaluate("""() => {
        const root = document.querySelector('[x-data*="accountDangerZone"]');
        const data = window.Alpine.$data(root);
        data.confirmText = 'delete';
        data.deleteAccount();
    }""")

    # Wait for redirect to the login page.  The session was invalidated so the
    # server might refuse the connection briefly; treat that as success.
    try:
        page.wait_for_url("**/login/**", timeout=10_000)
        page.wait_for_load_state("networkidle")
    except playwright.sync_api.Error:
        pass
    pace(page, 2000)
