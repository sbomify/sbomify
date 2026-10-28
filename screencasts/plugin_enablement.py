"""Record one FAQ-length screencast per plugin.

Produces ``plugin_enablement_<slug>.webm`` for each plugin (the website links
to these names). Each clip opens Plugins from the sidebar, explains what the
plugin checks, ticks it, saves, and shows the enabled count go up. Billing is
disabled in the screencast fixture so every plugin (including ones that are
plan-gated in production) is clickable here.

Each clip's narration is ``narration/plugin_enablement_<slug>.yaml``; the
beat keys are the same in every one, so the script names them once.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_plugins,
    pace,
    settle,
    smooth_scroll,
    start_on_dashboard,
)

PLUGIN_SLUGS = [
    "osv",
    "dependency-track",
    "ntia-minimum-elements-2021",
    "bsi-tr03183-v2.1-compliance",
    "fda-medical-device-2025",
    "sbom-verification",
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin_slug", PLUGIN_SLUGS, ids=PLUGIN_SLUGS)
def plugin_enablement(recording_page: Page, plugin_slug: str, pied_piper_with_sboms: dict) -> None:
    page = recording_page

    mock_vuln_trends(page)
    start_on_dashboard(page, pause_ms=600)
    narrate(page, "intro")
    settle(page)

    navigate_to_plugins(page)
    page.locator("#plugin-settings-form").wait_for(state="visible", timeout=15_000)
    pace(page, 400)
    narrate(page, "open_plugins")
    settle(page)

    # Attribute selector (not #id) because some plugin slugs contain dots
    # (e.g. bsi-tr03183-v2.1-compliance) which have CSS-special meaning.
    toggle = page.locator(f"[id='plugin-{plugin_slug}']")
    smooth_scroll(page, toggle, 600)
    narrate(page, "about")
    settle(page)

    narrate(page, "tick_save")
    hover_and_click(page, toggle)
    pace(page, 600)

    save_btn = page.locator("#plugin-settings-form button[type='submit']").last
    smooth_scroll(page, save_btn, 500)
    hover_and_click(page, save_btn)
    page.wait_for_load_state("networkidle")

    # The summary cards refresh after the save; scroll back up to show the
    # enabled count.
    enabled_card = page.locator("#plugins-summary")
    enabled_card.get_by_text("Enabled plugins").wait_for(state="visible", timeout=10_000)
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 900)
    narrate(page, "done")
    narrate(page, "changes_apply")
    settle(page)
    pace(page, 600)
