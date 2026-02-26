"""Record the user account deletion screencast.

Drives: Dashboard → user menu → Settings → Account Danger Zone →
Delete Account modal → type 'delete' → confirm → redirect to login.

The /settings view only renders the account page (with the danger zone)
when the session has no current_team AND the user has a pending workspace
invitation.  To reach it we: (1) show the dashboard with workspace context,
(2) modify the Django session to remove current_team, (3) create a pending
invitation so the view doesn't redirect again, then (4) click Settings.
"""

import playwright.sync_api
import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone
from playwright.sync_api import Page

from conftest import hover_and_click, mock_vuln_trends, pace, start_on_dashboard, type_text
from sbomify.apps.teams.models import Invitation, Team


def _make_settings_page_reachable(page: Page, user: AbstractBaseUser) -> None:
    """Remove workspace context and add a pending invite so /settings renders."""
    # 1. Clear current_team from the Django session
    cookies = page.context.cookies()
    session_id = next(c["value"] for c in cookies if c["name"] == "sessionid")
    session = SessionStore(session_key=session_id)
    if "current_team" in session:
        del session["current_team"]
    session.save()

    # 2. Create a second team + pending invitation so the view doesn't redirect
    #    to the teams dashboard (it requires pending_invitations).
    invite_team = Team.objects.create(name="Hooli", key="hooli-invite")
    Invitation.objects.create(
        team=invite_team,
        email=user.email,
        role="admin",
        expires_at=timezone.now() + timezone.timedelta(days=7),
    )


@pytest.mark.django_db(transaction=True)
def account_deletion(recording_page: Page, sample_user: AbstractBaseUser) -> None:
    page = recording_page

    # Mock vulnerability-trends on the dashboard so it looks realistic
    mock_vuln_trends(page)

    # Start on the dashboard
    start_on_dashboard(page)

    # The /settings view redirects to workspace settings when current_team
    # exists.  Remove the workspace context and create a pending invitation
    # so it renders the account settings page instead.
    _make_settings_page_reachable(page, sample_user)

    # Open the user dropdown menu (top-right)
    user_menu = page.locator("button[aria-label='User menu']")
    hover_and_click(page, user_menu)
    pace(page, 600)

    # Click "Settings" in the dropdown
    dropdown_settings = page.locator("a[role='menuitem']", has_text="Settings")
    hover_and_click(page, dropdown_settings)
    page.wait_for_load_state("networkidle")

    # Hide the "Pending Workspace Invitations" banner — it only exists because
    # we created a fake invitation to make the /settings view render.
    page.evaluate("""
        const h = document.querySelector('h1');
        if (h && h.textContent.includes('Pending Workspace Invitations')) {
            h.closest('.mb-6').remove();
        }
    """)
    pace(page, 1200)

    # Scroll to the Account Danger Zone section and expand it.
    # The template uses both Bootstrap .collapse and Alpine x-show which conflict
    # (x-show keeps an inline display:none even after the .show class is added).
    # We click the header to trigger Alpine's toggle, then clear the inline style
    # so the collapse section actually becomes visible.
    danger_header = page.locator(".dangerzone-card .collapsible-header")
    danger_header.scroll_into_view_if_needed()
    pace(page, 600)
    hover_and_click(page, danger_header)
    # Force-show the card body by removing all hiding mechanisms.
    # Alpine's x-show and Bootstrap's .collapse both fight over display.
    page.evaluate("""
        const el = document.querySelector('.dangerzone-card .card-body');
        if (el) {
            el.classList.remove('collapse');
            el.classList.add('show');
            el.removeAttribute('x-show');
            el.removeAttribute('x-cloak');
            el.style.display = 'block';
        }
    """)
    pace(page, 800)

    # Click "Delete Account" to open the modal
    delete_btn = page.locator(".dangerzone-card .delete-btn")
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
    confirm_delete_btn = page.locator(".delete-modal-button--danger")
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
    except (TimeoutError, playwright.sync_api.Error):
        pass
    pace(page, 2000)
