"""Record the Security Advisories screencast.

Dashboard → Security Advisories → the list with its tallies → click into
an in-progress advisory → detail page: severity and status, affected
products, the linked CVE, and the update timeline.

The two seeded advisories mirror the lifecycle the FAQ describes: one
published and resolved (the finished story), one mid-remediation (the
page a team actually works in).
"""

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from conftest import auto_dismiss_toasts, hover_and_click, pace, start_on_dashboard
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryVulnerability,
    SecurityAdvisory,
)

OPEN_ADVISORY_TITLE = "Improper authentication in SAML assertion handling"
RESOLVED_ADVISORY_TITLE = "Path traversal in archive extraction"


@pytest.fixture
def seeded_advisories(pied_piper_product: dict) -> dict:
    """Two advisories on the recording team, attached to the Pied Piper product."""
    product = pied_piper_product["product"]
    team = product.team
    now = timezone.now()

    open_advisory = SecurityAdvisory.objects.create(
        team=team,
        title=OPEN_ADVISORY_TITLE,
        severity="high",
        description="Assertions signed with a stripped signature block are accepted during SSO.",
        remediation_status=SecurityAdvisory.RemediationStatus.FIX_IN_PROGRESS,
    )
    vulnerability = AdvisoryVulnerability.objects.create(advisory=open_advisory, cve_id="CVE-2026-41337")
    advisory_product = AdvisoryProduct.objects.create(advisory=open_advisory, product=product)
    AdvisoryProductStatus.objects.create(
        vulnerability=vulnerability,
        advisory_product=advisory_product,
        status=AdvisoryProductStatus.Status.EXPLOITABLE,
        action_statement="Upgrade to 5.2.1 or disable SSO until patched.",
    )
    for event_type, body, payload in [
        (AdvisoryEvent.EventType.STATUS_CHANGE, "", {"to": "identified"}),
        (AdvisoryEvent.EventType.STATUS_CHANGE, "", {"from": "identified", "to": "investigating"}),
        (AdvisoryEvent.EventType.UPDATE, "Reproduced against 5.1.x; scoping the fix to the assertion parser.", {}),
        (AdvisoryEvent.EventType.STATUS_CHANGE, "", {"from": "investigating", "to": "fix_in_progress"}),
    ]:
        AdvisoryEvent.objects.create(advisory=open_advisory, event_type=event_type, body=body, payload=payload)

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

    return {"open": open_advisory, "resolved": resolved}


@pytest.mark.django_db(transaction=True)
def security_advisories(recording_page: Page, seeded_advisories: dict) -> None:
    page = recording_page
    auto_dismiss_toasts(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Security Advisories ───────────────────────────────
    advisories_link = page.get_by_role("link", name="Security Advisories")
    hover_and_click(page, advisories_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 2. Let the list breathe: tallies on top, both lifecycle states ───
    page.locator(f"text={OPEN_ADVISORY_TITLE}").first.wait_for(state="visible", timeout=15_000)
    pace(page, 2500)

    # ── 3. Open the advisory that is still being worked ──────────────────
    open_row = page.locator(f"tr:has-text('{OPEN_ADVISORY_TITLE}')").first
    hover_and_click(page, open_row)
    page.wait_for_load_state("networkidle")
    pace(page, 2000)

    # ── 4. Detail: header badges, affected product, CVE, timeline ────────
    page.locator(f"h1:has-text('{OPEN_ADVISORY_TITLE}')").first.wait_for(state="visible", timeout=15_000)
    pace(page, 1500)
    timeline_entry = page.locator("text=Reproduced against 5.1.x").first
    timeline_entry.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 2500)
