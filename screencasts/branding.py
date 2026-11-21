"""Record the branding screencast.

Drives: Dashboard → Settings → Branding tab → turn on custom branding → set the
brand and accent colors → upload a logo → Save changes → the branded public
Trust Center.

Infrastructure: the stack has no media bucket, so ``upload_media`` stores into
a dict and the browser's requests for the bucket URL are answered from it. The
upload, validation and save all run for real.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, Route

from conftest import (
    hover_and_click,
    narrate,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import TeamPluginSettings
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

BRAND_COLOR = "#1F7A4D"
ACCENT_COLOR = "#2EA36B"

LOGO_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="300" viewBox="0 0 1200 300">
  <rect x="20" y="40" width="220" height="220" rx="48" fill="#1F7A4D"/>
  <path d="M80 210 V90 h60 a40 40 0 0 1 0 80 h-60" fill="none" stroke="#FFFFFF" stroke-width="22"
        stroke-linecap="round" stroke-linejoin="round"/>
  <text x="280" y="190" font-family="Helvetica, Arial, sans-serif" font-size="120" font-weight="700"
        fill="#1F7A4D">Pied Piper</text>
</svg>
"""


@pytest.fixture
def media_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[bytes, str]]:
    """Keep uploaded branding images in a dict, keyed by object name."""
    store: dict[str, tuple[bytes, str]] = {}

    def _upload_media(self: StorageClient, object_name: str, data: bytes, content_type: str) -> None:
        store[object_name] = (data, content_type)

    monkeypatch.setattr(StorageClient, "upload_media", _upload_media)
    return store


@pytest.fixture
def branding_workspace(pied_piper_with_sboms: dict, sample_user) -> dict:
    team: Team = pied_piper_with_sboms["product"].team
    team.name = "Pied Piper"
    team.is_public = True
    team.save(update_fields=["name", "is_public"])
    sample_user.first_name = "Richard"
    sample_user.last_name = "Hendricks"
    sample_user.save(update_fields=["first_name", "last_name"])
    product = pied_piper_with_sboms["product"]
    product.is_public = True
    product.save(update_fields=["is_public"])
    Component.objects.filter(pk__in=[c.pk for c in pied_piper_with_sboms["components"].values()]).update(
        visibility=Component.Visibility.PUBLIC
    )
    # Scanning is on, as in a real workspace; without it the page shows the admin an "enable scanning" nag.
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": ["osv"]})
    return pied_piper_with_sboms


def _hide_test_host(page: Page) -> None:
    """The preview's address bar prints the test server's host; show the product's."""
    page.evaluate(
        """() => {
            const host = window.location.host;
            const walk = (node) => {
                if (node.nodeType === Node.TEXT_NODE && node.textContent.includes(host)) {
                    node.textContent = node.textContent.replace(host, 'app.sbomify.com');
                }
                node.childNodes.forEach(walk);
            };
            walk(document.body);
        }"""
    )


def _set_color(page: Page, field_id: str, value: str) -> None:
    field = page.locator(f"#{field_id}")
    hover_and_click(page, field)
    field.fill("")
    type_text(field, value, delay=90)
    pace(page, 400)


@pytest.mark.django_db(transaction=True)
def branding(branding_workspace: dict, media_store: dict, recording_page: Page) -> None:
    page = recording_page
    team = branding_workspace["product"].team

    def _serve_media(route: Route) -> None:
        key = route.request.url.rsplit("/", 1)[-1]
        if key in media_store:
            data, content_type = media_store[key]
            route.fulfill(status=200, content_type=content_type, body=data)
        else:
            route.fulfill(status=404, body="")

    page.route("http://test-s3.localhost/**", _serve_media)

    # The opening line plays over the splash and the trip to Settings.
    narrate(page, "intro")
    start_on_dashboard(page, 0)
    navigate_to_settings(page)
    narrate(page, "branding_tab_sets")
    navigate_to_settings_tab(page, "branding")
    toggle = page.locator("#branding-enabled-toggle")
    toggle.wait_for(state="visible", timeout=15_000)
    _hide_test_host(page)
    pace(page, 400)
    hover_and_click(page, toggle)
    pace(page, 600)

    narrate(page, "pick_brand_color")
    _set_color(page, "brand-color", BRAND_COLOR)
    _set_color(page, "accent-color", ACCENT_COLOR)
    pace(page, 600)

    logo_input = page.locator("input[type='file'][name='logo']")
    smooth_scroll(page, page.get_by_text("Logo and icon"), 400)
    narrate(page, "add_logo_goes")
    logo_input.set_input_files(files=[{"name": "pied-piper-logo.svg", "mimeType": "image/svg+xml", "buffer": LOGO_SVG}])
    pace(page, 1200)

    save = page.locator("#team-branding-save-btn")
    smooth_scroll(page, save, 400)
    narrate(page, "preview_shows_saved")
    with page.expect_response(lambda r: r.request.method == "POST" and "branding" in r.url):
        hover_and_click(page, save)
    page.wait_for_load_state("networkidle")
    pace(page, 600)
    _hide_test_host(page)
    preview = page.get_by_text("Preview").first
    smooth_scroll(page, preview, 1200)
    settle(page)

    page.goto(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))
    page.wait_for_load_state("networkidle")
    pace(page, 300)
    narrate(page, "public_trust_center")
    settle(page)
    products = page.locator("#products")
    narrate(page, "visitors_see_logo")
    smooth_scroll(page, products, 600)
