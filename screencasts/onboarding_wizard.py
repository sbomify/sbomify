"""Record the onboarding wizard screencast.

Drives: a brand-new workspace → Get started wizard (Why → Your organization →
Security promises → Workspace ready) → Go to dashboard → "Set up your first
repository" page (coding agent prompt, setup token, terminal command).

The shared session fixture marks the wizard as completed so other recordings
never get bounced into it. ``fresh_workspace`` undoes that for this one
recording, in the database and in the browser's session, so the dashboard
redirects into the wizard the way it does for a new sign-up.
"""

from importlib import import_module

import pytest
from django.conf import settings as django_settings
from playwright.sync_api import BrowserContext, Page

from conftest import (
    hover_and_click,
    narrate,
    pace,
    settle,
    smooth_scroll,
    type_text,
)
from sbomify.apps.teams.models import Team

# The recording browser reaches the app over plain http on a container IP,
# which is not a secure context, so navigator.clipboard does not exist and
# every Copy button would raise "Failed to copy to clipboard". Give the page
# a stand-in clipboard so the copy reads the way it does for a real user.
CLIPBOARD_STUB_JS = """
if (!navigator.clipboard) {
    let text = '';
    Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async (t) => { text = t; }, readText: async () => text },
    });
}
"""


@pytest.fixture
def fresh_workspace(recording_context: BrowserContext, deletable_team: Team, settings) -> Team:
    """Make the recording's workspace look like one that was just created."""
    # The setup page prints the app's address in its prompt and command. The
    # test settings point it at localhost, which a viewer should never see.
    settings.APP_BASE_URL = "https://app.sbomify.com"
    recording_context.add_init_script(CLIPBOARD_STUB_JS)

    deletable_team.has_completed_wizard = False
    deletable_team.save(update_fields=["has_completed_wizard"])

    cookie = next(c for c in recording_context.cookies() if c["name"] == "sessionid")
    store = import_module(django_settings.SESSION_ENGINE).SessionStore(session_key=cookie["value"])
    workspace = dict(store["current_workspace"])
    workspace["has_completed_wizard"] = False
    store["current_workspace"] = workspace
    store.save()
    return deletable_team


@pytest.mark.django_db(transaction=True)
def onboarding_wizard(recording_page: Page, fresh_workspace: Team) -> None:
    page = recording_page

    # A new workspace lands in the wizard instead of the dashboard.
    page.goto("/dashboard")
    page.wait_for_url(lambda url: "/onboarding/" in url, timeout=15_000)
    page.wait_for_load_state("networkidle")
    start = page.get_by_role("link", name="Start")
    start.wait_for(state="visible", timeout=10_000)
    pace(page, 800)

    narrate(page, "intro")
    settle(page)
    narrate(page, "asks_three_things")
    settle(page)
    hover_and_click(page, start)
    page.wait_for_load_state("networkidle")

    # ── Your organization ────────────────────────────────────────────────
    company = page.locator("#id_company_name")
    company.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    narrate(page, "first_organization_these")
    hover_and_click(page, company)
    company.fill("")
    type_text(company, "Pied Piper", delay=90)
    pace(page, 300)

    contact = page.locator("#id_contact_name")
    hover_and_click(page, contact)
    contact.fill("")
    type_text(contact, "Richard Hendricks", delay=70)
    pace(page, 300)

    website = page.locator("#id_website")
    hover_and_click(page, website)
    type_text(website, "https://piedpiper.example.com", delay=45)
    pace(page, 300)

    email = page.locator("#id_email")
    hover_and_click(page, email)
    email.fill("")
    type_text(email, "richard@piedpiper.example.com", delay=45)
    pace(page, 500)

    hover_and_click(page, page.get_by_role("button", name="Continue"))
    pace(page, 800)

    # ── Security promises ────────────────────────────────────────────────
    security_email = page.locator("#id_security_email")
    security_email.wait_for(state="visible", timeout=10_000)
    narrate(page, "next_security_promises")
    settle(page)
    hover_and_click(page, security_email)
    security_email.fill("")
    type_text(security_email, "security@piedpiper.example.com", delay=45)
    pace(page, 400)

    publish = page.get_by_text("Publish this email in my Trust Center's security.txt")
    narrate(page, "can_also_publish")
    hover_and_click(page, publish)
    pace(page, 600)

    support = page.locator("#id_default_support_period_years")
    smooth_scroll(page, support, 600)
    narrate(page, "set_default_support")
    settle(page)

    save = page.get_by_role("button", name="Save and continue")
    hover_and_click(page, save)
    go = page.get_by_role("link", name="Go to dashboard")
    go.wait_for(state="visible", timeout=15_000)
    pace(page, 800)

    narrate(page, "workspace_ready_checklist")
    settle(page)
    hover_and_click(page, go)
    page.wait_for_load_state("networkidle")

    # ── Set up your first repository ─────────────────────────────────────
    heading = page.get_by_role("heading", name="Set up your first repository")
    heading.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    narrate(page, "until_first_artifact")
    settle(page)

    create_token = page.get_by_role("button", name="Create setup token")
    narrate(page, "coding_agent_tab")
    hover_and_click(page, create_token)
    page.get_by_role("button", name="Reset token").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    narrate(page, "token_part_prompt")
    settle(page)

    copy_prompt = page.get_by_role("button", name="Copy prompt")
    narrate(page, "copy_prompt_paste")
    hover_and_click(page, copy_prompt)
    pace(page, 1200)

    terminal_tab = page.get_by_role("tab", name="Terminal")
    narrate(page, "prefer_terminal_same")
    hover_and_click(page, terminal_tab)
    pace(page, 1500)
    uv = page.locator("#panel-setup-terminal").get_by_role("button", name="uv", exact=True)
    hover_and_click(page, uv)
    pace(page, 1500)

    # The page stays reachable after the first artifact, from search.
    search = page.locator("#navbar-search-input")
    narrate(page, "come_back_page")
    page.keyboard.press("Control+k")
    search.wait_for(state="visible", timeout=5_000)
    pace(page, 400)
    type_text(search, "connect", delay=110)
    option = page.locator("#navbar-search-list").get_by_role("option", name="Connect a repository")
    option.wait_for(state="visible", timeout=10_000)
    pace(page, 1200)
    hover_and_click(page, option)
    page.wait_for_url(lambda url: "/getting-started/" in url, timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 800)

    narrate(page, "commit_push_workflow")
    settle(page)
    pace(page, 800)
