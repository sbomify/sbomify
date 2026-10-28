"""Record the API tokens screencast.

Drives: Dashboard → Settings → API tokens tab → Generate token (name, scope,
expiry) → copy the new token → a component's CI/CD integration dialog shows
where SBOMIFY_TOKEN goes → back to API tokens → delete the token.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    caption,
    clear_caption,
    hover_and_click,
    mock_vuln_trends,
    navigate_to_components,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
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
    caption(page, "Here is how to create an API token, use it in CI, and revoke it when you are done.")
    clear_caption(page)

    navigate_to_settings(page)
    navigate_to_settings_tab(page, "tokens")
    page.get_by_role("heading", name="API tokens").first.wait_for(state="visible", timeout=10_000)
    caption(page, "API tokens live in Settings. They are personal, so other members cannot see or manage yours.")

    # ── Generate ─────────────────────────────────────────────────────────
    hover_and_click(page, page.get_by_role("button", name="Generate token").first)
    modal = page.locator("#createTokenModal")
    name = page.locator("#tokenGenerationForm input[name='description']")
    name.wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    caption(page, "Give the token a name that says where it is used.", block=False)
    hover_and_click(page, name)
    type_text(name, TOKEN_NAME, delay=70)
    pace(page, 500)

    scope = page.locator("#tokenGenerationForm select[name='scope']")
    caption(
        page,
        "Pick the narrowest scope that does the job. Publish only is made for CI uploads.",
        block=False,
    )
    hover_and_click(page, scope)
    scope.select_option("publish")
    pace(page, 1200)

    expiry = page.locator("#tokenGenerationForm select[name='expires_in_hours']")
    caption(page, "And give it a short life. This one expires in 30 days.", block=False)
    hover_and_click(page, expiry)
    expiry.select_option(label="30 days")
    pace(page, 1200)

    clear_caption(page)
    hover_and_click(page, modal.locator("#generate-token-button"))

    # ── Copy ─────────────────────────────────────────────────────────────
    page.get_by_text("Copy your token now").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    caption(page, "sbomify shows the token only once, so copy it now.")
    hover_and_click(page, page.get_by_role("button", name="Show token"))
    pace(page, 1500)
    hover_and_click(page, page.get_by_role("button", name="Copy token"))
    page.get_by_role("button", name="Copied").wait_for(state="visible", timeout=5_000)
    caption(page, "It is on your clipboard. Store it as a secret in your CI, never in your code.")
    hover_and_click(page, page.get_by_role("button", name="Hide token"))
    pace(page, 600)

    # ── Use it ───────────────────────────────────────────────────────────
    caption(page, "To see where it goes, open a component's CI/CD integration.", block=False)
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
    caption(
        page,
        "The sbomify action reads the token from SBOMIFY_TOKEN. Run this wizard in your repository, "
        "and it writes the pipeline that uploads your SBOMs.",
    )
    page.keyboard.press("Escape")
    pace(page, 400)

    # ── Revoke ───────────────────────────────────────────────────────────
    caption(page, "Back in Settings, the token is listed under Your tokens.", block=False)
    navigate_to_settings(page)
    navigate_to_settings_tab(page, "tokens")
    row = page.locator("tr", has_text=TOKEN_NAME)
    row.wait_for(state="visible", timeout=10_000)
    caption(page, "It shows when the token was last used, and when it expires.")
    caption(page, "When you no longer need it, delete it. It stops working right away.", block=False)
    hover_and_click(page, row.get_by_role("button", name=f"Delete token {TOKEN_NAME}"))
    confirm = page.get_by_role("alertdialog").get_by_role("button", name="Delete token", exact=True)
    confirm.wait_for(state="visible", timeout=5_000)
    pace(page, 1200)
    hover_and_click(page, confirm)
    page.get_by_text("No tokens yet").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    caption(page, "The token is gone, and anything still using it is locked out.")
    pace(page, 600)
