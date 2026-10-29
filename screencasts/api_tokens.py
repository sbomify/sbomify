"""Record the API tokens screencast: a token for an AI agent.

Drives: Dashboard → Settings → API tokens tab → Generate token: name it, step
through the access presets and pick "AI agent", whose explanation says what
the agent can and cannot do → expiry → copy the new token → the token in the
list → delete it.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    start_on_dashboard,
    type_text,
)

TOKEN_NAME = "Claude Code"  # nosec B105 - the token's label, not a secret


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


def _trace_line(page: Page, box: dict[str, float], line_height: float, line: int) -> None:
    """Move the pointer along one line of a paragraph, the way a reader's eye goes."""
    y = box["y"] + line_height * (line + 0.5)
    page.mouse.move(box["x"] + 10, y, steps=8)
    page.mouse.move(box["x"] + box["width"] - 20, y, steps=60)
    pace(page, 900)


@pytest.mark.django_db(transaction=True)
def api_tokens(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page
    page.add_init_script(CLIPBOARD_STUB_JS)
    mock_vuln_trends(page)

    # The opening line plays over the splash and the trip to Settings.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=0)
    navigate_to_settings(page)
    narrate(page, "api_tokens_live")
    navigate_to_settings_tab(page, "tokens")
    page.get_by_role("heading", name="API tokens").first.wait_for(state="visible", timeout=10_000)
    pace(page, 1500)

    # ── Generate ─────────────────────────────────────────────────────────
    hover_and_click(page, page.get_by_role("button", name="Generate token").first)
    modal = page.locator("#createTokenModal")
    name = page.locator("#tokenGenerationForm input[name='description']")
    name.wait_for(state="visible", timeout=10_000)
    narrate(page, "give_token_name")
    hover_and_click(page, name)
    type_text(name, TOKEN_NAME, delay=70)
    pace(page, 300)

    scope = page.locator("#tokenGenerationForm select[name='scope']")
    narrate(page, "presets")
    hover_and_click(page, scope)
    scope.select_option("publish")
    pace(page, 1800)
    scope.select_option("read_only")
    pace(page, 1800)

    narrate(page, "pick_ai_agent")
    scope.select_option("agent")
    explanation = modal.get_by_text("This token can read fix prompts")
    explanation.wait_for(state="visible", timeout=5_000)
    pace(page, 800)
    explanation.hover()

    # Follow the explanation line by line while it is read out.
    box = explanation.bounding_box()
    assert box is not None
    line_height = box["height"] / 5
    narrate(page, "agent_cannot_apply")
    for line in range(3):
        _trace_line(page, box, line_height, line)
    narrate(page, "agent_cannot_publish")
    for line in range(2, 5):
        _trace_line(page, box, line_height, line)
    settle(page)

    expiry = page.locator("#tokenGenerationForm select[name='expires_in_hours']")
    narrate(page, "give_short_life")
    hover_and_click(page, expiry)
    expiry.select_option(label="30 days")
    pace(page, 1200)

    hover_and_click(page, modal.locator("#generate-token-button"))

    # ── Copy ─────────────────────────────────────────────────────────────
    page.get_by_text("Copy your token now").wait_for(state="visible", timeout=10_000)
    narrate(page, "sbomify_shows_token")
    pace(page, 600)
    hover_and_click(page, page.get_by_role("button", name="Show token"))
    pace(page, 1500)
    hover_and_click(page, page.get_by_role("button", name="Copy token"))
    page.get_by_role("button", name="Copied").wait_for(state="visible", timeout=5_000)
    pace(page, 1500)
    hover_and_click(page, page.get_by_role("button", name="Hide token"))

    # ── Revoke ───────────────────────────────────────────────────────────
    row = page.locator("tr", has_text=TOKEN_NAME)
    row.wait_for(state="visible", timeout=10_000)
    narrate(page, "shows_when_token")
    row.hover()
    narrate(page, "when_no_longer")
    hover_and_click(page, row.get_by_role("button", name=f"Delete token {TOKEN_NAME}"))
    confirm = page.get_by_role("alertdialog").get_by_role("button", name="Delete token", exact=True)
    confirm.wait_for(state="visible", timeout=5_000)
    pace(page, 1200)
    hover_and_click(page, confirm)
    page.get_by_text("No tokens yet").wait_for(state="visible", timeout=10_000)
    pace(page, 300)
    narrate(page, "token_gone_anything")
