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

    # The opening line plays over the splash and the trip to Settings.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=0)
    navigate_to_settings(page)
    narrate(page, "members_tab_settings")
    navigate_to_settings_tab(page, "members")
    page.get_by_text("Workspace members").first.wait_for(state="visible", timeout=10_000)

    # ── Roles ────────────────────────────────────────────────────────────
    legend = page.locator("#role-legend summary").first
    smooth_scroll(page, legend, 500)
    narrate(page, "not_sure_which")
    hover_and_click(page, legend)
    pace(page, 1000)
    narrate(page, "owners_admins_run")
    settle(page)
    hover_and_click(page, legend)

    # ── Invite ───────────────────────────────────────────────────────────
    invite = page.get_by_role("link", name="Invite member")
    narrate(page, "add_someone_choose")
    hover_and_click(page, invite)
    page.wait_for_load_state("networkidle")
    email = page.locator("#id_email")
    email.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, email)
    type_text(email, INVITEE, delay=55)
    pace(page, 400)

    role = page.locator("#id_role")
    narrate(page, "pick_role_each")
    hover_and_click(page, role)
    role.select_option("operator")
    pace(page, 600)
    narrate(page, "jared_joins_operator")
    pace(page, 2000)

    hover_and_click(page, page.get_by_role("button", name="Invite to workspace"))
    page.wait_for_load_state("networkidle")

    # ── Pending invitation ───────────────────────────────────────────────
    pending = page.locator("tr", has_text=INVITEE)
    pending.wait_for(state="visible", timeout=10_000)
    narrate(page, "sbomify_emails_invite")
    smooth_scroll(page, pending, 500)
    narrate(page, "changed_mind_revoke")
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
    narrate(page, "take_someone_s")
    hover_and_click(page, member_row.get_by_role("button", name="Member actions"))
    pace(page, 600)
    hover_and_click(page, page.get_by_role("menuitem", name="Remove member"))
    remove_confirm = page.get_by_role("alertdialog").get_by_role("button", name="Remove member")
    remove_confirm.wait_for(state="visible", timeout=5_000)
    pace(page, 1000)
    narrate(page, "their_access_ends")
    hover_and_click(page, remove_confirm)
    page.wait_for_load_state("networkidle")
    page.locator("tr", has_text="Dinesh Chugtai").wait_for(state="detached", timeout=10_000)
    pace(page, 800)
    narrate(page, "there_no_role")
