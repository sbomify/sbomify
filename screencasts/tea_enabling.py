"""Record the TEA (Transparency Exchange API) enabling screencast.

Drives: Dashboard → Settings → Trust Center tab → enable the Trust Center →
configure a custom domain → (domain verification simulated) → enable TEA →
the discovery endpoint appears → what a TEA client gets back from it.

DNS verification runs asynchronously in production, so the recording marks
the domain verified through the ORM and reloads. The closing JSON is a real
response from the workspace's TEA products endpoint, fetched in-process and
drawn as a code view, because the custom domain does not resolve here.
"""

import html as html_lib
import json

import pytest
from django.test import Client
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    enable_and_configure_trust_center,
    hover_and_click,
    narrate,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_inputs,
    rewrite_localhost_urls,
    settle,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.apps.teams.models import Team

DOMAIN = "trust.piedpiper.com"


@pytest.fixture
def public_product(pied_piper_with_sboms: dict) -> dict:
    product = pied_piper_with_sboms["product"]
    product.is_public = True
    product.save(update_fields=["is_public"])
    return pied_piper_with_sboms


def _show_json(page: Page, url_label: str, payload: object) -> None:
    body = html_lib.escape(json.dumps(payload, indent=2)[:2400])
    page.set_content(
        f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ margin: 0; min-height: 100vh; background: #0A0A23; display: flex;
             align-items: center; justify-content: center;
             font-family: ui-monospace, "SF Mono", Menlo, monospace; }}
      .win {{ width: 900px; background: #14142e; border: 1px solid #2b2b52;
             border-radius: 12px; overflow: hidden; box-shadow: 0 24px 60px rgba(0,0,0,.5); }}
      .bar {{ padding: 12px 16px; background: #1c1c3d; border-bottom: 1px solid #2b2b52;
             color: #a5b4fc; font-size: 15px; }}
      .bar b {{ color: #34d399; margin-right: 10px; }}
      pre {{ margin: 0; padding: 20px 22px; color: #c8c8e0; font-size: 15px; line-height: 1.55;
            max-height: 72vh; overflow: hidden; }}
    </style></head><body><div class="win">
      <div class="bar"><b>GET</b>{html_lib.escape(url_label)}</div><pre>{body}</pre>
    </div></body></html>""",
        wait_until="load",
    )


@pytest.mark.django_db(transaction=True)
def tea_enabling(recording_page: Page, deletable_team: Team, public_product: dict) -> None:
    page = recording_page
    auto_dismiss_toasts(page)
    start_on_dashboard(page, pause_ms=600)

    narrate(page, "intro")

    # ── 1. Trust Center on, custom domain set ─────────────────────────────
    navigate_to_trust_center_tab(page)
    narrate(page, "tea_served_trust")
    enable_and_configure_trust_center(page)

    # ── 2. Domain verification (simulated) ────────────────────────────────
    Team.objects.filter(key=deletable_team.key).update(custom_domain_validated=True)
    narrate(page, "once_dns_records")
    pace(page, 600)
    page.reload()
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    rewrite_localhost_inputs(page)
    verified = page.locator("#team-custom-domain-wrapper").get_by_text("Verified", exact=True)
    verified.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, verified, 400)
    pace(page, 800)

    # ── 3. Enable TEA ─────────────────────────────────────────────────────
    tea_toggle = page.locator("#tea-toggle")
    smooth_scroll(page, tea_toggle, 500)
    narrate(page, "switch_transparency_exchange")
    pace(page, 400)
    with page.expect_navigation():
        hover_and_click(page, tea_toggle)
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    rewrite_localhost_inputs(page)

    # ── 4. Discovery URL ──────────────────────────────────────────────────
    tea_url = page.locator("#tea-discovery-url")
    tea_url.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, tea_url, 400)
    tea_url.hover()
    narrate(page, "discovery_endpoint_appears")
    settle(page)

    # ── 5. What a TEA client gets ─────────────────────────────────────────
    response = Client().get(f"/public/{deletable_team.key}/tea/v{TEA_API_VERSION}/products")
    assert response.status_code == 200, response.content[:300]
    _show_json(page, f"https://{DOMAIN}/tea/v{TEA_API_VERSION}/products", response.json())
    narrate(page, "client_follows_public")
    settle(page)
    pace(page, 800)
