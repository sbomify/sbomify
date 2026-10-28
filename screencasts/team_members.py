"""Record the workspace members screencast.

Drives: Dashboard → Settings → Members tab → "What can each role do?" →
Invite member (email, role, role descriptions) → pending invitation →
revoke it → remove a member.

The Members tab has no control to change a member's role, so the video does
not claim one: a different role means a new invitation.
"""

import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import Page

from conftest import (
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
from sbomify.apps.teams.models import Member, Team

INVITEE = "jared@piedpiper.example.com"


@pytest.fixture
def workspace_with_members(deletable_team: Team) -> Team:
    """Two colleagues already in the workspace, next to the owner."""
    user_model = get_user_model()
    for username, first, last, role in (
        ("dinesh", "Dinesh", "Chugtai", "member"),
        ("gilfoyle", "Bertram", "Gilfoyle", "admin"),
    ):
        user = user_model.objects.create(
            username=username, email=f"{username}@piedpiper.example.com", first_name=first, last_name=last
        )
        Member.objects.create(team=deletable_team, user=user, role=role)
    return deletable_team


@pytest.mark.django_db(transaction=True)
def team_members(recording_page: Page, workspace_with_members: Team, pied_piper_with_sboms: dict) -> None:
    page = recording_page
    mock_vuln_trends(page)

    start_on_dashboard(page, pause_ms=800)
    caption(page, "Here is how to manage who has access to your sbomify workspace.")
    clear_caption(page)

    navigate_to_settings(page)
    navigate_to_settings_tab(page, "members")
    page.get_by_text("Workspace members").first.wait_for(state="visible", timeout=10_000)
    caption(page, "The Members tab in Settings lists everyone in the workspace, with their role.")

    # ── Roles ────────────────────────────────────────────────────────────
    legend = page.locator("#role-legend summary").first
    smooth_scroll(page, legend, 500)
    caption(page, "Not sure which role to give? Open What can each role do.", block=False)
    hover_and_click(page, legend)
    pace(page, 1000)
    caption(
        page,
        "Owners and admins run the workspace. Members do the day to day work. "
        "Operators read everything and triage vulnerabilities, but change nothing else.",
    )
    hover_and_click(page, legend)
    pace(page, 500)

    # ── Invite ───────────────────────────────────────────────────────────
    invite = page.get_by_role("link", name="Invite member")
    caption(page, "To add someone, choose Invite member.", block=False)
    hover_and_click(page, invite)
    page.wait_for_load_state("networkidle")
    email = page.locator("#id_email")
    email.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, email)
    type_text(email, INVITEE, delay=55)
    pace(page, 400)

    role = page.locator("#id_role")
    caption(page, "Pick a role. Each role is explained below the list.", block=False)
    hover_and_click(page, role)
    role.select_option("operator")
    pace(page, 1200)
    caption(page, "Jared joins as an operator, to help triage vulnerabilities.")

    clear_caption(page)
    hover_and_click(page, page.get_by_role("button", name="Invite to workspace"))
    page.wait_for_load_state("networkidle")

    # ── Pending invitation ───────────────────────────────────────────────
    pending = page.locator("tr", has_text=INVITEE)
    pending.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, pending, 500)
    caption(page, "sbomify emails the invite. Until Jared accepts, it waits under Pending invitations.")
    caption(page, "Changed your mind? Revoke the invitation, and the link stops working.", block=False)
    hover_and_click(page, pending.get_by_role("button", name=f"Revoke invitation for {INVITEE}"))
    # The confirmation dialog is teleported to <body>, out of its wrapper.
    revoke_confirm = page.get_by_role("alertdialog").get_by_role("button", name="Revoke invitation")
    revoke_confirm.wait_for(state="visible", timeout=5_000)
    pace(page, 1200)
    hover_and_click(page, revoke_confirm)
    page.wait_for_load_state("networkidle")
    page.get_by_text("No pending invitations").wait_for(state="visible", timeout=10_000)
    pace(page, 800)

    # ── Remove a member ──────────────────────────────────────────────────
    member_row = page.locator("tr", has_text="Dinesh Chugtai")
    smooth_scroll(page, member_row, 500)
    caption(page, "To take someone's access away, open the menu on their row and remove them.", block=False)
    hover_and_click(page, member_row.get_by_role("button", name="Member actions"))
    pace(page, 600)
    hover_and_click(page, page.get_by_role("menuitem", name="Remove member"))
    remove_confirm = page.get_by_role("alertdialog").get_by_role("button", name="Remove member")
    remove_confirm.wait_for(state="visible", timeout=5_000)
    pace(page, 1000)
    caption(page, "Their access ends immediately.", block=False)
    hover_and_click(page, remove_confirm)
    page.wait_for_load_state("networkidle")
    page.locator("tr", has_text="Dinesh Chugtai").wait_for(state="detached", timeout=10_000)
    pace(page, 800)
    caption(
        page,
        "There is no role switch on this tab. To give someone a different role, remove them and invite them again.",
    )
    pace(page, 600)
