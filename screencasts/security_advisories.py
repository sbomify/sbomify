"""Record the Security Advisories screencast.

Dashboard → sidebar Security advisories → the list → Create advisory →
fill the form (title, severity, status, affected product and release,
CVE, CVSS, description) → Create advisory → the draft's detail page and
its timeline → post a "Fix in progress" update → publish it publicly →
the workspace's public Trust Center advisories page.

One published, resolved advisory is seeded so the list and the Trust
Center are not empty, and the product carries a ``v2.1.0`` release for
the picker to offer as an affected version.
"""

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    hover_and_click,
    narrate,
    pace,
    rewrite_localhost_urls,
    settle,
    sidebar_link,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.core.models import Release
from sbomify.apps.security_advisories.models import AdvisoryEvent, SecurityAdvisory

NEW_ADVISORY_TITLE = "Improper authentication in SAML assertion handling"
RESOLVED_ADVISORY_TITLE = "Path traversal in archive extraction"
AFFECTED_VERSION = "v2.1.0"


@pytest.fixture
def seeded_advisories(pied_piper_product: dict) -> dict:
    """A public Trust Center, a release to mark affected, one resolved advisory."""
    product = pied_piper_product["product"]
    team = product.team
    team.is_public = True
    team.save(update_fields=["is_public"])
    product.is_public = True
    product.save(update_fields=["is_public"])
    Release.objects.create(product=product, name=AFFECTED_VERSION, version="2.1.0")

    now = timezone.now()
    resolved = SecurityAdvisory.objects.create(
        team=team,
        title=RESOLVED_ADVISORY_TITLE,
        severity="medium",
        remediation_status=SecurityAdvisory.RemediationStatus.RESOLVED,
        status=SecurityAdvisory.Status.PUBLISHED,
        published_at=now,
        visibility=SecurityAdvisory.Visibility.PUBLIC,
        made_public_at=now,
        tracking_id=SecurityAdvisory.allocate_tracking_id(team),
    )
    AdvisoryEvent.objects.create(
        advisory=resolved, event_type=AdvisoryEvent.EventType.PUBLISHED, payload={"tracking_id": resolved.tracking_id}
    )
    return {"product": product, "resolved": resolved}


@pytest.mark.django_db(transaction=True)
def security_advisories(recording_page: Page, seeded_advisories: dict) -> None:
    page = recording_page
    auto_dismiss_toasts(page)
    # The opening line plays over the dashboard loading.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=600)

    # ── 1. The advisories list ────────────────────────────────────────────
    hover_and_click(page, sidebar_link(page, "Security advisories"))
    page.wait_for_load_state("networkidle")
    page.locator(f"text={RESOLVED_ADVISORY_TITLE}").first.wait_for(state="visible", timeout=15_000)
    narrate(page, "security_advisories_lists")
    settle(page)

    # ── 2. Create advisory ────────────────────────────────────────────────
    hover_and_click(page, page.get_by_role("link", name="Create advisory").first)
    page.wait_for_load_state("networkidle")
    title_input = page.locator("input[name='title']")
    title_input.wait_for(state="visible", timeout=15_000)
    narrate(page, "start_title_all")
    hover_and_click(page, title_input)
    type_text(title_input, NEW_ADVISORY_TITLE, delay=40)
    pace(page, 300)

    narrate(page, "set_severity_where")
    hover_and_click(page, page.locator("label:has(input[name='severity'][value='high'])"))
    pace(page, 500)
    hover_and_click(page, page.locator("label:has(input[name='remediation_status'][value='investigating'])"))
    pace(page, 500)

    # ── 3. Affected product and release ───────────────────────────────────
    product_name = seeded_advisories["product"].name
    open_versions = page.locator("button[aria-expanded]").filter(has_text="version").first
    smooth_scroll(page, open_versions, 500)
    narrate(page, "next_pick_what")
    hover_and_click(page, open_versions)
    pace(page, 600)
    version_row = page.get_by_role("checkbox").filter(has_text="2.1.0").first
    version_row.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, version_row)
    pace(page, 400)
    page.locator("p[aria-live='polite']").filter(has_text=product_name).first.wait_for(state="visible", timeout=5_000)

    # ── 4. Optional details ───────────────────────────────────────────────
    cve_input = page.locator("input[name='vulnerability_id']")
    smooth_scroll(page, cve_input, 500)
    narrate(page, "add_cve_cvss")
    hover_and_click(page, cve_input)
    type_text(cve_input, "CVE-2026-41337", delay=50)
    score_input = page.locator("input[name='cvss_score']")
    hover_and_click(page, score_input)
    type_text(score_input, "8.1", delay=80)
    description = page.locator("textarea[name='description']")
    hover_and_click(page, description)
    type_text(description, "Assertions with a stripped signature block are accepted during SSO.", delay=25)
    pace(page, 400)

    hover_and_click(page, page.get_by_role("button", name="Create advisory"))
    page.wait_for_url("**/security-advisories/*/", timeout=15_000)
    page.wait_for_load_state("networkidle")

    # ── 5. Detail page: draft notice, timeline ────────────────────────────
    page.locator("h1", has_text=NEW_ADVISORY_TITLE).first.wait_for(state="visible", timeout=15_000)
    narrate(page, "advisory_opens_draft")
    settle(page)
    timeline = page.locator("h2", has_text="Timeline").first
    smooth_scroll(page, timeline, 400)
    narrate(page, "timeline_records_every")
    note = page.locator("#composerNote")
    hover_and_click(page, note)
    type_text(note, "Reproduced on 2.1.0. A fix to the assertion parser is underway.", delay=30)
    page.locator("#composerKind").select_option("fix_in_progress")
    pace(page, 500)
    hover_and_click(page, page.get_by_role("button", name="Post update"))
    page.wait_for_load_state("networkidle")
    entry = page.locator("text=A fix to the assertion parser is underway").first
    entry.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, entry, 400)
    narrate(page, "update_lands_timeline")
    settle(page)

    # ── 6. Publish ────────────────────────────────────────────────────────
    publish_btn = page.get_by_role("button", name="Publish advisory").first
    hover_and_click(page, publish_btn)
    modal = page.locator("#publishAdvisoryModal")
    modal.get_by_role("button", name="Publish").wait_for(state="visible", timeout=10_000)
    public_option = modal.locator("label:has(input[name='visibility'][value='public'])")
    narrate(page, "when_ready_publish")
    if public_option.count():
        hover_and_click(page, public_option)
    pace(page, 600)
    hover_and_click(page, modal.get_by_role("button", name="Publish"))
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="View in Trust Center").first.wait_for(state="visible", timeout=15_000)
    narrate(page, "has_permanent_tracking")
    settle(page)

    # ── 7. The public Trust Center advisories page ────────────────────────
    team_key = seeded_advisories["product"].team.key
    page.goto(f"/public/workspace/{team_key}/advisories/")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    page.locator(f"text={NEW_ADVISORY_TITLE}").first.wait_for(state="visible", timeout=15_000)
    narrate(page, "customers_see_public")
