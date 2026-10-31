"""Record the trust center setup screencast.

Drives: Dashboard → Settings → Trust Center tab → enable the Trust Center →
welcome message → security.txt → upload a Company NDA → custom domain →
Components → open a component → set its visibility to public, then gated →
the public Trust Center page.

The Pied Piper product is seeded public so the closing public page has
something on it; the component is the thing whose visibility is set on camera.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    MINIMAL_PDF,
    auto_dismiss_toasts,
    dismiss_toasts,
    hover_and_click,
    narrate,
    navigate_to_components,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_inputs,
    rewrite_localhost_urls,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)

COMPONENT_NAME = "Compression Core Library"
WELCOME = "Security and compliance documents for the Pied Piper compression platform."


@pytest.fixture
def public_product(pied_piper_with_sboms: dict) -> dict:
    product = pied_piper_with_sboms["product"]
    product.is_public = True
    product.save(update_fields=["is_public"])
    return pied_piper_with_sboms


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test stack runs no S3, so the NDA upload stores into nothing."""
    from sbomify.apps.core.object_store import StorageClient

    monkeypatch.setattr(StorageClient, "upload_document", lambda self, data: "pied-piper-mutual-nda.pdf")


def _settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    rewrite_localhost_urls(page)
    rewrite_localhost_inputs(page)


@pytest.mark.django_db(transaction=True)
def trust_center_setup(recording_page: Page, public_product: dict, s3_short_circuit: None) -> None:
    page = recording_page
    auto_dismiss_toasts(page)
    # The opening line plays over the dashboard and the walk to Settings.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=600)

    # ── 1. Settings → Trust Center ────────────────────────────────────────
    navigate_to_trust_center_tab(page)
    toggle = page.locator("#workspace-visibility-toggle")
    toggle.wait_for(state="visible", timeout=10_000)
    narrate(page, "lives_under_settings")
    pace(page, 600)
    with page.expect_navigation():
        hover_and_click(page, toggle)
    _settle(page)
    page.locator("#trust-center-public-url").wait_for(state="visible", timeout=10_000)
    narrate(page, "trust_center_live")
    page.locator("#trust-center-public-url").hover()

    # ── 2. Welcome message ────────────────────────────────────────────────
    narrate(page, "add_welcome_message")
    description = page.locator("#trust_center_description")
    smooth_scroll(page, description, 500)
    hover_and_click(page, description)
    type_text(description, WELCOME, delay=25)
    with page.expect_navigation():
        hover_and_click(page, page.get_by_role("button", name="Save description"))
    _settle(page)

    # ── 3. security.txt ───────────────────────────────────────────────────
    security_toggle = page.locator("#security-txt-toggle")
    smooth_scroll(page, security_toggle, 500)
    narrate(page, "turn_security_txt")
    hover_and_click(page, security_toggle)
    csirt = page.locator("#security_txt_csirt_email")
    csirt.wait_for(state="visible", timeout=5_000)
    pace(page, 400)
    hover_and_click(page, csirt)
    type_text(csirt, "security@example.com", delay=40)
    save_security = page.get_by_role("button", name="Save security.txt")
    smooth_scroll(page, save_security, 400)
    with page.expect_navigation():
        hover_and_click(page, save_security)
    _settle(page)

    # ── 4. Company NDA ────────────────────────────────────────────────────
    nda_input = page.locator("#company_nda_file")
    nda_zone = page.locator("label:has(#company_nda_file)")
    smooth_scroll(page, nda_zone, 500)
    narrate(page, "upload_nda_visitors")
    nda_input.set_input_files(
        files=[{"name": "Pied_Piper_Mutual_NDA.pdf", "mimeType": "application/pdf", "buffer": MINIMAL_PDF}]
    )
    pace(page, 800)
    with page.expect_navigation():
        hover_and_click(page, page.get_by_role("button", name="Upload NDA"))
    _settle(page)
    view_nda = page.get_by_role("link", name="View NDA")
    view_nda.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, view_nda, 300)

    # ── 5. Custom domain ──────────────────────────────────────────────────
    domain_input = page.locator("#custom-domain-input")
    domain_input.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, domain_input, 500)
    narrate(page, "serve_own_address")
    hover_and_click(page, domain_input)
    type_text(domain_input, "trust.piedpiper.com")
    pace(page, 300)
    hover_and_click(page, page.get_by_role("button", name="Save domain"))
    page.locator("#team-custom-domain-wrapper").get_by_text("Pending verification").wait_for(
        state="visible", timeout=10_000
    )
    _settle(page)
    narrate(page, "sbomify_verifies_domain")
    page.locator("#team-custom-domain-wrapper").get_by_text("Pending verification").hover()

    # ── 6. Component visibility ───────────────────────────────────────────
    narrate(page, "next_choose_what")
    navigate_to_components(page)
    link = page.locator("main").get_by_role("link", name=COMPONENT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")

    visibility = page.get_by_role("button", name="Component visibility")
    visibility.wait_for(state="visible", timeout=15_000)
    pace(page, 400)
    hover_and_click(page, visibility)
    public_item = page.get_by_role("menuitemradio").filter(has_text="Public").first
    public_item.wait_for(state="visible", timeout=5_000)
    narrate(page, "public_means_anyone")
    pace(page, 500)
    with page.expect_response(lambda r: "toggle" in r.url or "public" in r.url, timeout=10_000):
        hover_and_click(page, public_item)
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 800)

    hover_and_click(page, visibility)
    gated_item = page.get_by_role("menuitemradio").filter(has_text="Gated").first
    gated_item.wait_for(state="visible", timeout=5_000)
    narrate(page, "gated_keeps_listed")
    pace(page, 500)
    with page.expect_response(lambda r: "toggle" in r.url or "public" in r.url, timeout=10_000):
        hover_and_click(page, gated_item)
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 800)

    # ── 7. The public Trust Center ────────────────────────────────────────
    team_key = public_product["product"].team.key
    narrate(page, "what_customers_see")
    page.goto(f"/public/workspace/{team_key}/")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    page.get_by_text(WELCOME).first.wait_for(state="visible", timeout=15_000)

    narrate(page, "below_products_have")
    product_row = page.get_by_text(public_product["product"].name).last
    smooth_scroll(page, product_row, 300)
