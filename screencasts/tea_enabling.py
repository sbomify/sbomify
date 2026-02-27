"""Record the TEA (Transparency Exchange API) enabling screencast.

Drives: Dashboard → Settings → Trust Center tab → enable trust center →
configure custom domain → mock domain validation → enable TEA →
see discovery URL.
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
from sbomify.apps.teams.models import Team

# ---------------------------------------------------------------------------
# Shared helper — reused steps from trust_center_setup
# ---------------------------------------------------------------------------


def _enable_and_configure_trust_center(page: Page) -> None:
    """Enable the trust center and configure a custom domain.

    Shared between trust_center_setup and tea_enabling screencasts.
    """
    # Enable Trust Center
    toggle = page.locator("#workspace-visibility-toggle")
    toggle.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, toggle)

    # The form auto-submits and reloads with active_tab=trust-center
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 1500)

    # Configure custom domain (loaded via HTMX)
    domain_input = page.locator("#custom-domain-input")
    domain_input.wait_for(state="visible", timeout=15_000)
    pace(page, 600)

    hover_and_click(page, domain_input)
    pace(page, 300)
    type_text(domain_input, "trust.piedpiper.com")
    pace(page, 600)

    # Save domain
    save_btn = page.locator("button:has-text('Save Domain')")
    save_btn.wait_for(state="visible", timeout=5_000)
    hover_and_click(page, save_btn)

    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 1500)


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
    _enable_and_configure_trust_center(page)

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
