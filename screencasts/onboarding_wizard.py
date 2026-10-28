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
    caption,
    clear_caption,
    hover_and_click,
    pace,
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

    caption(page, "Here is how to set up a new sbomify workspace with the Get started wizard.")
    caption(
        page,
        "It asks three things once: who you are, where to report a vulnerability, and how you support your software.",
    )
    clear_caption(page)
    hover_and_click(page, start)
    page.wait_for_load_state("networkidle")

    # ── Your organization ────────────────────────────────────────────────
    company = page.locator("#id_company_name")
    company.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    caption(page, "First, your organization. These details become your default contact profile.", block=False)
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
    caption(page, "Next, your security promises. Security researchers report vulnerabilities to this address.")
    hover_and_click(page, security_email)
    security_email.fill("")
    type_text(security_email, "security@piedpiper.example.com", delay=45)
    pace(page, 400)

    publish = page.get_by_text("Publish this email in my Trust Center's security.txt")
    caption(page, "You can also publish it in your Trust Center's security.txt file.", block=False)
    hover_and_click(page, publish)
    pace(page, 600)

    support = page.locator("#id_default_support_period_years")
    smooth_scroll(page, support, 600)
    caption(
        page,
        "Set a default support period, and the maximum time to fix each severity. The recommended targets "
        "are seven days for critical and thirty for high.",
    )

    save = page.get_by_role("button", name="Save and continue")
    clear_caption(page)
    hover_and_click(page, save)
    go = page.get_by_role("link", name="Go to dashboard")
    go.wait_for(state="visible", timeout=15_000)
    pace(page, 800)

    caption(page, "The workspace is ready, and the checklist on the right shows what was saved.")
    clear_caption(page)
    hover_and_click(page, go)
    page.wait_for_load_state("networkidle")

    # ── Set up your first repository ─────────────────────────────────────
    heading = page.get_by_role("heading", name="Set up your first repository")
    heading.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    caption(page, "Until your first artifact arrives, the dashboard helps you connect a repository.")

    create_token = page.get_by_role("button", name="Create setup token")
    caption(
        page,
        "The coding agent tab gives you a prompt for Claude Code, Cursor or another agent. "
        "First, create a setup token.",
        block=False,
    )
    hover_and_click(page, create_token)
    page.get_by_role("button", name="Reset token").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    caption(
        page, "The token is now part of the prompt. It expires after seven days, and you can revoke it in Settings."
    )

    copy_prompt = page.get_by_role("button", name="Copy prompt")
    caption(
        page,
        "Copy the prompt and paste it into your agent. It finds your lockfiles, creates the components "
        "and adds an SBOM workflow, after you review the changes.",
        block=False,
    )
    hover_and_click(page, copy_prompt)
    pace(page, 1200)

    terminal_tab = page.get_by_role("tab", name="Terminal")
    caption(page, "Prefer the terminal? The same wizard runs with Docker or uv.", block=False)
    hover_and_click(page, terminal_tab)
    pace(page, 1500)
    uv = page.locator("#panel-setup-terminal").get_by_role("button", name="uv", exact=True)
    hover_and_click(page, uv)
    pace(page, 1500)

    # The page stays reachable after the first artifact, from search.
    clear_caption(page)
    search = page.locator("#navbar-search-input")
    caption(page, "To come back to this page later, search for connect a repository.", block=False)
    page.keyboard.press("Control+k")
    search.wait_for(state="visible", timeout=5_000)
    pace(page, 400)
    type_text(search, "connect", delay=110)
    option = page.locator("#navbar-search-list").get_by_role("option", name="Connect a repository")
    option.wait_for(state="visible", timeout=10_000)
    pace(page, 1200)
    clear_caption(page)
    hover_and_click(page, option)
    page.wait_for_url(lambda url: "/getting-started/" in url, timeout=10_000)
    page.wait_for_load_state("networkidle")
    pace(page, 800)

    caption(page, "Commit and push the workflow, and your first SBOM lands in this workspace.")
    pace(page, 800)
