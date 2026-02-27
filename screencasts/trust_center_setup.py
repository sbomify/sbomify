"""Record the trust center setup screencast.

Drives: Dashboard → Settings → Trust Center tab → enable trust center →
configure custom domain → save.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_urls,
    start_on_dashboard,
    type_text,
)

# ---------------------------------------------------------------------------
# Main screencast
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def trust_center_setup(recording_page: Page) -> None:
    page = recording_page

    start_on_dashboard(page)

    # ── 1. Navigate to Settings → Trust Center tab ────────────────────────
    navigate_to_trust_center_tab(page)

    # ── 2. Enable Trust Center ────────────────────────────────────────────
    toggle = page.locator("#workspace-visibility-toggle")
    toggle.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, toggle)

    # The form auto-submits and reloads with active_tab=trust-center
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 1500)

    # ── 3. Configure custom domain ────────────────────────────────────────
    # The custom domain section loads via HTMX after the page reload
    domain_input = page.locator("#custom-domain-input")
    domain_input.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    hover_and_click(page, domain_input)
    pace(page, 300)
    type_text(domain_input, "trust.piedpiper.com")
    pace(page, 600)

    # ── 4. Save domain ────────────────────────────────────────────────────
    save_btn = page.locator("button:has-text('Save Domain')")
    save_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, save_btn)

    # Wait for the Alpine API call to complete and UI to update
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 2000)
