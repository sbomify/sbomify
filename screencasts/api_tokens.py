"""Record the API tokens screencast.

Drives: Dashboard → Settings → API tokens tab → Generate token (name, scope,
expiry) → copy the new token → a component's CI/CD integration dialog shows
where SBOMIFY_TOKEN goes → back to API tokens → delete the token.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_components,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    start_on_dashboard,
    type_text,
)

TOKEN_NAME = "GitHub Actions upload"  # nosec B105 - the token's label, not a secret


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


@pytest.mark.django_db(transaction=True)
def api_tokens(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page
    page.add_init_script(CLIPBOARD_STUB_JS)
    mock_vuln_trends(page)

    start_on_dashboard(page, pause_ms=800)
    narrate(page, "intro")
    settle(page)

    navigate_to_settings(page)
    navigate_to_settings_tab(page, "tokens")
    page.get_by_role("heading", name="API tokens").first.wait_for(state="visible", timeout=10_000)
    narrate(page, "api_tokens_live")
    settle(page)

    # ── Generate ─────────────────────────────────────────────────────────
    hover_and_click(page, page.get_by_role("button", name="Generate token").first)
    modal = page.locator("#createTokenModal")
    name = page.locator("#tokenGenerationForm input[name='description']")
    name.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    narrate(page, "give_token_name")
    hover_and_click(page, name)
    type_text(name, TOKEN_NAME, delay=70)
    pace(page, 500)

    scope = page.locator("#tokenGenerationForm select[name='scope']")
    narrate(page, "pick_narrowest_scope")
    hover_and_click(page, scope)
    scope.select_option("publish")
    pace(page, 1200)

    expiry = page.locator("#tokenGenerationForm select[name='expires_in_hours']")
    narrate(page, "give_short_life")
    hover_and_click(page, expiry)
    expiry.select_option(label="30 days")
    pace(page, 1200)

    hover_and_click(page, modal.locator("#generate-token-button"))

    # ── Copy ─────────────────────────────────────────────────────────────
    page.get_by_text("Copy your token now").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    narrate(page, "sbomify_shows_token")
    settle(page)
    hover_and_click(page, page.get_by_role("button", name="Show token"))
    pace(page, 1500)
    hover_and_click(page, page.get_by_role("button", name="Copy token"))
    page.get_by_role("button", name="Copied").wait_for(state="visible", timeout=5_000)
    narrate(page, "clipboard_store_secret")
    settle(page)
    hover_and_click(page, page.get_by_role("button", name="Hide token"))
    pace(page, 600)

    # ── Use it ───────────────────────────────────────────────────────────
    narrate(page, "see_where_goes")
    navigate_to_components(page)
    component_link = page.locator("main").get_by_role("link", name="Web Dashboard", exact=True).first
    hover_and_click(page, component_link)
    page.wait_for_load_state("networkidle")
    menu = page.get_by_role("button", name="Component actions")
    menu.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, menu)
    pace(page, 600)
    hover_and_click(page, page.get_by_role("menuitem", name="CI/CD integration"))
    command = page.locator("#ci-cd-command-" + pied_piper_with_sboms["components"]["Web Dashboard"].id)
    command.wait_for(state="visible", timeout=10_000)
    pace(page, 800)
    narrate(page, "sbomify_action_reads")
    settle(page)
    page.keyboard.press("Escape")
    pace(page, 400)

    # ── Revoke ───────────────────────────────────────────────────────────
    narrate(page, "back_settings_token")
    navigate_to_settings(page)
    navigate_to_settings_tab(page, "tokens")
    row = page.locator("tr", has_text=TOKEN_NAME)
    row.wait_for(state="visible", timeout=10_000)
    narrate(page, "shows_when_token")
    settle(page)
    narrate(page, "when_no_longer")
    hover_and_click(page, row.get_by_role("button", name=f"Delete token {TOKEN_NAME}"))
    confirm = page.get_by_role("alertdialog").get_by_role("button", name="Delete token", exact=True)
    confirm.wait_for(state="visible", timeout=5_000)
    pace(page, 1200)
    hover_and_click(page, confirm)
    page.get_by_text("No tokens yet").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    narrate(page, "token_gone_anything")
    settle(page)
    pace(page, 600)
