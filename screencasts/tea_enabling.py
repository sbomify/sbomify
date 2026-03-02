"""Record the TEA (Transparency Exchange API) enabling screencast.

Drives: Dashboard → Settings → Trust Center tab → enable trust center →
configure custom domain → mock domain validation → enable TEA →
see discovery URL.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    enable_and_configure_trust_center,
    hover_and_click,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_urls,
    start_on_dashboard,
)
from sbomify.apps.teams.models import Team

# ---------------------------------------------------------------------------
# Main screencast
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def tea_enabling(recording_page: Page, deletable_team: Team) -> None:
    page = recording_page

    start_on_dashboard(page)

    # ── 1. Navigate to Settings → Trust Center tab ────────────────────────
    navigate_to_trust_center_tab(page)

    # ── 2. Enable trust center + configure domain ─────────────────────────
    enable_and_configure_trust_center(page)

    # ── 3. Mock domain validation ─────────────────────────────────────────
    # In production the domain would be validated asynchronously via DNS.
    # We simulate this by updating the DB directly so the TEA discovery URL
    # appears after the next page reload.
    Team.objects.filter(key=deletable_team.key).update(custom_domain_validated=True)

    # Reload the trust center tab to pick up the validated domain
    page.reload()
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 1500)

    # ── 4. Enable TEA ─────────────────────────────────────────────────────
    tea_toggle = page.locator("#tea-toggle")
    tea_toggle.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, tea_toggle)

    # The form auto-submits and reloads with active_tab=trust-center
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 1500)

    # ── 5. Verify TEA discovery URL is shown ──────────────────────────────
    # After reload the TEA section should show the discovery URL
    tea_url = page.locator("text=.well-known/tea")
    tea_url.wait_for(state="visible", timeout=10_000)
    pace(page, 2000)
