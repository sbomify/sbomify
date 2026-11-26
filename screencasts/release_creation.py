"""Record the release creation screencast.

Drives: Dashboard → Products → the product → its auto-created "latest"
release → Product actions → Create release (New release page) → name,
version, description → the new release → Add Artifact → select every SBOM →
Add to Release → Ships with → Add release (another product's release) → the
release's public page and its "Ships with" section.

Prerequisite: uses the pied_piper_with_sboms ORM fixture which creates the full
Pied Piper hierarchy (product with components) with CycloneDX SBOMs.
The SBOM creation signal auto-creates a "latest" Release on the product.
A second product, the Pied Piper Runtime, is seeded with its own 3.1.0 release
for the new release to ship with. The workspace and both products are public so
the release's public page exists and lists the link.
"""

from typing import Any

import pytest
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_products,
    pace,
    rewrite_localhost_urls,
    settle,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.sboms.models import SBOM, Component, Product

RELEASE_NAME = "Middle-Out Rewrite"
RELEASE_VERSION = "2.0.0"
RELEASE_DESCRIPTION = "Complete rewrite of the compression engine using the middle-out algorithm"


RUNTIME_PRODUCT_NAME = "Pied Piper Runtime"
RUNTIME_VERSION = "3.1.0"


@pytest.fixture
def runtime_release(pied_piper_with_sboms: dict) -> dict:
    """A second product with its own release, for the new release to ship with."""
    product = pied_piper_with_sboms["product"]
    team = product.team
    team.is_public = True
    team.save(update_fields=["is_public"])
    product.is_public = True
    product.save(update_fields=["is_public"])
    for component in pied_piper_with_sboms["components"].values():
        component.visibility = Component.Visibility.PUBLIC
        component.save(update_fields=["visibility"])

    component = Component.objects.create(team=team, name="Runtime", visibility=Component.Visibility.PUBLIC)
    runtime = Product.objects.create(
        team=team,
        name=RUNTIME_PRODUCT_NAME,
        description="The sandboxed runtime Pied Piper applications run on",
        is_public=True,
    )
    runtime.components.set([component])
    sbom = SBOM.objects.create(
        name="com.piedpiper/runtime",
        version=RUNTIME_VERSION,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="runtime-3.1.0.cdx.json",
        source="api",
        component=component,
    )
    release = Release.objects.create(product=runtime, name=f"v{RUNTIME_VERSION}", version=RUNTIME_VERSION)
    ReleaseArtifact.objects.create(release=release, sbom=sbom)
    return {**pied_piper_with_sboms, "runtime_release": release}


def _type_into(page: Page, locator, text: str, delay: int = 50) -> None:
    hover_and_click(page, locator)
    type_text(locator, text, delay=delay)
    pace(page, 250)


@pytest.mark.django_db(transaction=True)
def release_creation(recording_page: Page, runtime_release: dict[str, Any]) -> None:
    page = recording_page

    mock_vuln_trends(page)
    # The opening line plays over the splash, the dashboard and the way to
    # Products, so the video does not open on silence.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=300)

    # ── 1. The product and its rolling "latest" release ──────────────────
    navigate_to_products(page)
    product_link = page.get_by_role("link", name=PIED_PIPER_PRODUCT_NAME, exact=True).first
    product_link.wait_for(state="visible", timeout=15_000)
    narrate(page, "every_product_has")
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")

    latest = page.get_by_role("link", name="latest", exact=True).first
    latest.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, latest, 600)

    # ── 2. Create a release from the product's actions menu ──────────────
    narrate(page, "version_ship_create")
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 500)
    hover_and_click(page, page.get_by_role("button", name="Product actions"))
    pace(page, 400)
    hover_and_click(page, page.get_by_role("menuitem", name="Create release"))
    page.wait_for_url("**/releases/new/**")
    page.wait_for_load_state("networkidle")
    pace(page, 300)

    narrate(page, "product_already_picked")
    _type_into(page, page.locator("#release-name"), RELEASE_NAME)
    _type_into(page, page.locator("#release-version"), RELEASE_VERSION, delay=90)
    _type_into(page, page.locator("#release-description"), RELEASE_DESCRIPTION, delay=30)

    create_btn = page.get_by_role("button", name="Create release")
    smooth_scroll(page, create_btn, 300)
    hover_and_click(page, create_btn)
    page.wait_for_url("**/release/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 500)

    # ── 3. Add artifacts ──────────────────────────────────────────────────
    add_btn = page.get_by_role("button", name="Add Artifact").first
    add_btn.wait_for(state="visible", timeout=10_000)
    narrate(page, "release_starts_empty")
    hover_and_click(page, add_btn)

    page.locator("#modal-artifact-search").wait_for(state="visible", timeout=10_000)
    select_all = page.get_by_role("button", name="Select All Visible")
    select_all.wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    narrate(page, "search_filter_list")
    hover_and_click(page, select_all)
    # Keep the picker open until the line has been said.
    settle(page)

    with page.expect_response(
        lambda r: "/releases/" in r.url and r.request.method == "POST",
        timeout=15_000,
    ):
        hover_and_click(page, page.get_by_role("button", name="Add to Release"))
    page.locator("#modal-artifact-search").wait_for(state="hidden", timeout=20_000)
    page.wait_for_load_state("networkidle")
    # The header's artifact count is rendered with the page and does not
    # follow the table the dialog refreshed, so it still reads 0. Reload to
    # show the count the release really has.
    narrate(page, "release_holds_sbom")
    page.reload()
    page.wait_for_load_state("networkidle")
    release_url = page.url

    # ── 4. Ships with: another product's release ─────────────────────────
    card = page.locator("#release-links-card")
    card.wait_for(state="visible", timeout=10_000)
    narrate(page, "ships_with")
    smooth_scroll(page, card, 900)
    card.get_by_text("Ships with no other release").hover()
    # Nothing is added until the line naming the add has been said.
    narrate(page, "add_runtime")
    hover_and_click(page, card.get_by_role("button", name="Add release").first)
    picker = page.locator("#add-release-link-release")
    picker.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    narrate(page, "pick_version")
    hover_and_click(page, picker)
    # Choose on "Choose version 3.1.0", not while the list is still being described.
    pace(page, 3600)
    picker.select_option(label=RUNTIME_VERSION)
    pace(page, 700)
    settle(page)
    with page.expect_response(lambda r: "/links" in r.url and r.request.method == "POST", timeout=15_000):
        hover_and_click(page, page.locator("#addReleaseLinkModal").get_by_role("button", name="Add"))
    row = page.locator("#release-links-card tr", has_text=RUNTIME_PRODUCT_NAME).first
    row.wait_for(state="visible", timeout=15_000)

    narrate(page, "combined_sbom")
    row.hover()
    pace(page, 1800)
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 700)
    page.locator("a[title='Download as CycloneDX']:visible").first.hover()
    settle(page)

    # ── 5. The release's public page ──────────────────────────────────────
    narrate(page, "public_page")
    release_id = release_url.rstrip("/").split("/")[-1]
    product_id = runtime_release["product"].id
    page.goto(f"/public/product/{product_id}/release/{release_id}/")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    public_links = page.get_by_role("table", name="Linked releases")
    public_links.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    smooth_scroll(page, public_links, 900)
    public_links.get_by_role("link", name=f"v{RUNTIME_VERSION}").hover()
