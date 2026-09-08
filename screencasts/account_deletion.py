"""Record the user account deletion screencast.

Drives: Dashboard → sidebar Settings → Account tab → Danger Zone →
Delete Account modal → type 'delete' → confirm → redirect to login.

The account danger zone now lives in the team settings page under the
"Account" tab, available to workspace owners.
"""

import re

import playwright.sync_api
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
def account_deletion(recording_page: Page) -> None:
    page = recording_page

    # Start on the dashboard
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=400)

    # Navigate to workspace Settings (the sidebar link)
    narrate(page, "account_tab")
    navigate_to_settings(page)

    # Click the "Account" tab. Settings sections are real links now (one URL
    # each) rather than the old data-tab switcher — same matching style as
    # conftest.navigate_to_trust_center_tab.
    account_tab = page.locator("a.settings-tab[href$='/account']")
    account_tab.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, account_tab)
    pace(page, 800)

    # Scroll to the Account Danger Zone section and expand it.  Every danger
    # zone is one c-cards.dangerzone-collapsible now, so the band that opens it
    # is a role="button" carrying the title rather than a .tw-dangerzone-card
    # header, and the account tab is its own URL so only this zone is on it.
    narrate(page, "danger_zone")
    danger_band = page.get_by_role("button", name=re.compile(r"Danger Zone"))
    danger_band.wait_for(state="visible", timeout=15_000)
    danger_band.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 600)

    # Click the band to toggle the collapsing body open (it starts shut).
    hover_and_click(page, danger_band)
    pace(page, 600)

    # Click "Delete account" to open the modal.  Its aria-label is what names
    # it, and it differs from the modal's own "Delete my account" confirm.
    narrate(page, "consequences")
    delete_btn = page.get_by_role("button", name="Delete your account")
    delete_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, delete_btn)
    pace(page, 800)

    # Type "delete" character-by-character for a human-like feel.
    # The modal is teleported to <body> via x-teleport, so the input uses
    # x-model bound to the parent Alpine component.
    narrate(page, "confirm")
    confirm_input = page.locator("#delete-account-confirm")
    confirm_input.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, confirm_input)
    type_text(confirm_input, "delete", delay=120)
    pace(page, 400)

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

    # The closing line plays over the confirmation state, then the deletion
    # fires — the viewer hears why it is irreversible before it happens.
    narrate(page, "outro")
    settle(page)

    # Trigger the deletion via Alpine's API — ensures canConfirm is true.
    # Don't await: the function sets window.location.href which triggers a
    # navigation, and page.evaluate() can't resolve across navigations.
    page.evaluate("""() => {
        const root = document.querySelector('[x-data*="accountDangerZone"]');
        const data = window.Alpine.$data(root);
        data.confirmText = 'delete';
        data.deleteAccount();
    }""")

    # Wait briefly for the deletion to process — the redirect lands on the
    # login page which is blank in the test environment, so keep this short.
    try:
        page.wait_for_url("**/login/**", timeout=10_000)
    except playwright.sync_api.Error:
        pass
