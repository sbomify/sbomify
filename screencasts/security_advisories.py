"""Record the Security Advisories screencast: an AI agent drafts, a person decides.

The person's side of an agent-first advisory workflow:

1. **The agent drafts.** A terminal-style console shows an AI agent's real API
   calls, made with a real AI agent token: creating the advisory works (201, a
   draft), publishing it is refused (403).
2. **A person publishes.** The draft opens marked "An AI agent drafted this
   advisory"; the person reads it and publishes it publicly.
3. **The agent changes a published advisory.** Two more real calls, an edit
   and a timeline update, both answered 202: held as proposals, not applied.
4. **A person decides.** The advisory's "Waiting for review" list shows each
   change with its diff. Approve the edit, reject the update with a reason.
5. **The outcome.** The public Trust Center advisories page.

One published, resolved advisory is seeded so the list and the Trust Center are
not empty, and the product carries a ``v2.1.0`` release for the agent to name
as affected.
"""

import json
from typing import Any

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.utils import timezone
from playwright.sync_api import Page

from conftest import (
    agent_console,
    agent_console_append,
    auto_dismiss_toasts,
    close_agent_console,
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
from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core import authz
from sbomify.apps.core.models import Release
from sbomify.apps.security_advisories.models import AdvisoryEvent, SecurityAdvisory

NEW_ADVISORY_TITLE = "Improper authentication in SAML assertion handling"
RESOLVED_ADVISORY_TITLE = "Path traversal in archive extraction"
AFFECTED_VERSION = "v2.1.0"
AGENT_TOKEN_NAME = "Claude Code"  # nosec B105 - the token's label, not a secret
API_BASE = "https://app.sbomify.com/api/v2/advisories"

REJECT_NOTE = "2.1.1 has not shipped yet. Post this once it is released."


@pytest.fixture
def seeded_advisories(pied_piper_with_sboms: dict, sample_user: AbstractBaseUser, settings: Any) -> dict:
    """A public Trust Center, a release to mark affected, one resolved advisory, an AI agent token."""
    settings.APP_BASE_URL = "https://app.sbomify.com"
    product = pied_piper_with_sboms["product"]
    team = product.team
    team.is_public = True
    team.save(update_fields=["is_public"])
    product.is_public = True
    product.save(update_fields=["is_public"])
    release = Release.objects.create(product=product, name=AFFECTED_VERSION, version="2.1.0")

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

    # The token an owner made with the AI agent preset and gave to Claude Code.
    token = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        team=team,
        encoded_token=token,
        description=AGENT_TOKEN_NAME,
        scopes=authz.SCOPE_PRESETS["agent"],
    )
    return {"product": product, "release": release, "resolved": resolved, "agent_token": token}


def _agent_call(token: str, method: str, path: str, body: dict[str, Any]) -> Any:
    """What the agent sends: the real advisories API, with its AI agent token."""
    return getattr(Client(), method)(
        f"/api/v2/advisories{path}",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _curl(method: str, path: str, data: str) -> list[str]:
    return [
        f'$ curl -X {method} "{API_BASE}{path}" \\',
        f"    -H \"Authorization: Bearer $SBOMIFY_TOKEN\" --data '{data}'",
    ]


@pytest.mark.django_db(transaction=True)
def security_advisories(recording_page: Page, seeded_advisories: dict) -> None:
    page = recording_page
    token = seeded_advisories["agent_token"]
    auto_dismiss_toasts(page)
    # The opening line plays over the dashboard loading.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=600)

    # ── 1. The agent drafts, and cannot publish ──────────────────────────
    narrate(page, "security_advisories_lists")
    hover_and_click(page, sidebar_link(page, "Security advisories"))
    page.wait_for_load_state("networkidle")
    page.locator(f"text={RESOLVED_ADVISORY_TITLE}").first.wait_for(state="visible", timeout=15_000)
    pace(page, 1200)

    agent_console(
        page,
        f'Claude Code · API token "{AGENT_TOKEN_NAME}" (AI agent)',
        [
            "# Draft an advisory for the SAML bug we just reproduced:",
            *_curl("POST", "/", '{"title": "Improper authentication in SAML ...", "severity": "high", ...}'),
        ],
    )
    narrate(page, "agent_drafts")
    pace(page, 1500)
    created = _agent_call(
        token,
        "post",
        "/",
        {
            "title": NEW_ADVISORY_TITLE,
            "severity": "high",
            "remediation_status": "investigating",
            "identifier": "CVE-2026-41337",
            "cvss_score": 8.1,
            "description": "Assertions with a stripped signature block are accepted during SSO.",
            "product_ids": [seeded_advisories["product"].id],
            "affected_release_ids": [seeded_advisories["release"].id],
        },
    )
    assert created.status_code == 201, created.content
    advisory_id = created.json()["id"]
    agent_console_append(
        page, "HTTP/1.1 201 Created", json.dumps({"id": advisory_id, "status": created.json()["status"]})
    )
    pace(page, 1500)

    agent_console_append(
        page,
        "",
        "# Publish it to the Trust Center:",
        *_curl("POST", f"/{advisory_id}/publish", '{"visibility": "public"}'),
    )
    narrate(page, "agent_cannot_publish")
    pace(page, 1500)
    refused = _agent_call(token, "post", f"/{advisory_id}/publish", {"visibility": "public"})
    assert refused.status_code == 403, refused.content
    agent_console_append(page, "HTTP/1.1 403 Forbidden", json.dumps({"detail": refused.json()["detail"]}))
    settle(page)

    # ── 2. A person reads the draft and publishes it ─────────────────────
    narrate(page, "draft_waits_for_you")
    close_agent_console(page)
    page.reload()
    page.wait_for_load_state("networkidle")
    row_link = page.locator("main tr", has_text=NEW_ADVISORY_TITLE).first
    row_link.wait_for(state="visible", timeout=15_000)
    pace(page, 600)
    hover_and_click(page, row_link)
    page.wait_for_load_state("networkidle")
    banner = page.get_by_text("An AI agent drafted this advisory").first
    banner.wait_for(state="visible", timeout=15_000)
    banner.hover()
    settle(page)

    narrate(page, "read_it_through")
    timeline = page.locator("h2", has_text="Timeline").first
    smooth_scroll(page, timeline, 1500)
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 900)
    hover_and_click(page, page.get_by_role("button", name="Publish advisory").first)
    modal = page.locator("#publishAdvisoryModal")
    modal.get_by_role("button", name="Publish").wait_for(state="visible", timeout=10_000)
    pace(page, 500)
    hover_and_click(page, modal.locator("label:has(input[name='visibility'][value='public'])"))
    pace(page, 500)
    hover_and_click(page, modal.get_by_role("button", name="Publish"))
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="View in Trust Center").first.wait_for(state="visible", timeout=15_000)

    # ── 3. The agent changes the published advisory: held ────────────────
    agent_console(
        page,
        f'Claude Code · API token "{AGENT_TOKEN_NAME}" (AI agent)',
        [
            "# New evidence: raise the severity.",
            *_curl("PATCH", f"/{advisory_id}", '{"severity": "critical", "cvss_score": 9.1, "context": "..."}'),
        ],
    )
    narrate(page, "agent_changes_published")
    pace(page, 1200)
    edit = _agent_call(
        token,
        "patch",
        f"/{advisory_id}",
        {
            "severity": "critical",
            "cvss_score": 9.1,
            "context": "The bypass works without any user interaction, so this is critical, not high.",
        },
    )
    assert edit.status_code == 202, edit.content
    agent_console_append(page, "HTTP/1.1 202 Accepted", json.dumps({"id": edit.json()["id"], "status": "pending"}))
    pace(page, 1200)
    agent_console_append(
        page,
        "",
        "# Mark it resolved:",
        *_curl("POST", f"/{advisory_id}/updates", '{"kind": "resolved", "note": "Fixed in 2.1.1."}'),
    )
    update = _agent_call(
        token,
        "post",
        f"/{advisory_id}/updates",
        {
            "kind": "resolved",
            "note": "Fixed in 2.1.1. Upgrade to 2.1.1 or later.",
            "context": "The fix to the assertion parser is merged.",
        },
    )
    assert update.status_code == 202, update.content
    pace(page, 800)
    agent_console_append(page, "HTTP/1.1 202 Accepted", json.dumps({"id": update.json()["id"], "status": "pending"}))
    settle(page)

    # ── 4. A person decides each change ──────────────────────────────────
    narrate(page, "waiting_for_review")
    close_agent_console(page)
    page.reload()
    page.wait_for_load_state("networkidle")
    review = page.locator("#review")
    review.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, review.locator("li").first, 600)
    review.get_by_text("AI agent").first.hover()

    narrate(page, "diff_shows_change")
    first = review.locator("li").first
    first.get_by_text("Why, in the agent's words").hover()
    pace(page, 1500)
    first.locator(".line-through").first.hover()
    pace(page, 1500)
    first.locator(".line-through").nth(1).hover()
    pace(page, 1200)

    narrate(page, "approve_edit")
    hover_and_click(page, first.get_by_role("button", name="Approve"))
    page.wait_for_load_state("networkidle")
    review = page.locator("#review")
    reject = review.get_by_role("button", name="Reject").first
    reject.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, review.locator("li").first, 600)

    narrate(page, "reject_update")
    hover_and_click(page, reject)
    dialog = page.get_by_role("alertdialog")
    dialog.get_by_text("Too early").wait_for(state="visible", timeout=10_000)
    hover_and_click(page, dialog.locator("label").filter(has_text="Too early").first)
    note = page.locator("#rejectProposalNote")
    hover_and_click(page, note)
    type_text(note, REJECT_NOTE, delay=25)
    narrate(page, "agent_reads_reason")
    hover_and_click(page, dialog.get_by_role("button", name="Reject", exact=True))
    page.wait_for_load_state("networkidle")
    page.get_by_text("Nothing waiting").first.wait_for(state="visible", timeout=15_000)
    pace(page, 1200)

    # ── 5. The public Trust Center advisories page ────────────────────────
    team_key = seeded_advisories["product"].team.key
    page.goto(f"/public/workspace/{team_key}/advisories/")
    narrate(page, "customers_see_public")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    page.locator(f"text={NEW_ADVISORY_TITLE}").first.wait_for(state="visible", timeout=15_000)
    page.locator(f"text={NEW_ADVISORY_TITLE}").first.hover()
