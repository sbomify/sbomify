"""Record the "work with AI agents, with a person in the loop" screencast.

sbomify lets an AI agent do the legwork of vulnerability triage and security
advisories, and keeps every decision with a person. This recording shows both
halves of that, with the agent's side driven for real:

1. **Token.** Settings, API tokens, Generate token with the "For an AI agent"
   scope, and the explanation the form shows for it.
2. **CVE triage.** The agent, using that token against the real API, reads the
   triage prompt for libwebp's CVE-2023-4863 and sends a Not affected ruling
   with ``review=true``. The ruling waits on the Vulnerabilities Review tab,
   marked as from an AI agent. The agent then tries to apply the ruling
   without review and gets the 403 the triage API returns to an agent token.
   A person approves it in the app, and the vulnerability closes.
3. **Security advisory.** The agent drafts an advisory for zlib's
   CVE-2023-45853. It tries to publish it and gets a 403; a person publishes
   it. The agent then posts an update and edits the severity. The advisory is
   published, so both are held as proposals. The person approves the update
   and rejects the severity edit with a reason, which the agent reads back.

Every agent call goes through Django's test client with the token generated
in the recording, so status codes and bodies in the overlay are the API's own.

Seeding (preconditions only): Pied Piper with one completed OSV scan per SBOM,
projected into finding rows with the real ``sync_findings``, the KEV cache
primed, and a public workspace and product so an advisory can be published
publicly. S3 is backed by a dict, and the two jobs the stub broker never runs
(the ruling's impact count, and re-applying VEX after an approval) are run
in-process.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.cache import cache
from django.test import Client
from playwright.sync_api import Page
from vulnerability_triage import (
    CORE_COMPONENT,
    FIX_CVE,
    TRIAGE_CVE,
    USER_FIRST_NAME,
    USER_LAST_NAME,
    WORKSPACE_NAME,
    _security_result,
)

from conftest import (
    auto_dismiss_toasts,
    hover_and_click,
    install_dict_backed_s3,
    mock_vuln_trends,
    narrate,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    sidebar_link,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason

TOKEN_NAME = "Claude Code agent"  # nosec B105 - the token's label, not a secret

TRIAGE_PURL = "pkg:generic/libwebp@1.2.4"
TRIAGE_DETAIL = "libwebp is linked for thumbnail previews only. The vulnerable decoder is never called."
TRIAGE_CONTEXT = (
    "I searched the Compression Core source for every libwebp call. Only `WebPGetInfo` is used, to read "
    "thumbnail sizes. The lossless decoder with the overflow is never reached."
)

ADVISORY_TITLE = "Heap overflow in zlib MiniZip affects Compression Core Library"
ADVISORY_DESCRIPTION = (
    "Compression Core Library bundles zlib 1.2.13. Its MiniZip code has an integer overflow and heap "
    "overflow when opening a crafted archive (CVE-2023-45853)."
)
UPDATE_NOTE = "A fix is in progress. Compression Core Library moves to zlib 1.3 in the next release."
UPDATE_CONTEXT = "The upgrade pull request is open and its tests pass."
SEVERITY_CONTEXT = "MiniZip is only used when importing archives, which most users never do."
REJECT_NOTE = "Every upload goes through the archive import, so MiniZip is reached. Keep it critical."

# The overlay is a terminal-style card bottom right; its id keeps re-renders in place.
OVERLAY_JS = """(payload) => {
    let el = document.getElementById('agent-overlay');
    if (!el) {
        el = document.createElement('div');
        el.id = 'agent-overlay';
        el.style.cssText = `
            position: fixed; right: 24px; bottom: 24px; z-index: 10000;
            width: 720px; padding: 16px 20px 18px;
            background: #0f172a; color: #e2e8f0;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 15px;
            line-height: 1.55; border-radius: 12px; border: 1px solid rgba(255,255,255,0.12);
            box-shadow: 0 16px 40px rgba(0,0,0,0.45);
        `;
        document.body.appendChild(el);
    }
    while (el.firstChild) el.removeChild(el.firstChild);
    const header = document.createElement('div');
    header.style.cssText = 'display:flex; align-items:center; gap:8px; margin-bottom:10px;' +
        ' font-family: ui-sans-serif, system-ui, sans-serif; font-size:14px; font-weight:600; color:#c4b5fd;';
    const icon = document.createElement('span');
    icon.textContent = '\\uD83E\\uDD16';
    const title = document.createElement('span');
    title.textContent = payload.title;
    header.appendChild(icon);
    header.appendChild(title);
    el.appendChild(header);
    const colours = { req: '#93c5fd', ok: '#86efac', no: '#fca5a5', text: '#e2e8f0', dim: '#94a3b8' };
    for (const [kind, text] of payload.lines) {
        const line = document.createElement('div');
        line.style.cssText = 'white-space: pre-wrap; word-break: break-word; color:' + (colours[kind] || colours.text) +
            (kind === 'ok' || kind === 'no' ? '; font-weight:600;' : ';') +
            (kind === 'req' ? ' margin-top:6px;' : '');
        line.textContent = text;
        el.appendChild(line);
    }
}"""


def show_agent(page: Page, lines: list[tuple[str, str]]) -> None:
    """Show what the agent just did: each line is (kind, text), kind one of req/ok/no/text/dim."""
    page.evaluate(OVERLAY_JS, {"title": f'AI agent, using the "{TOKEN_NAME}" token', "lines": lines})


def hide_agent(page: Page) -> None:
    page.evaluate("document.getElementById('agent-overlay')?.remove()")


def _status_line(response: Any) -> tuple[str, str]:
    reasons = {200: "OK", 201: "Created", 202: "Accepted", 403: "Forbidden"}
    code = response.status_code
    return ("ok" if code < 400 else "no", f"{code} {reasons.get(code, '')}".rstrip())


class Agent:
    """An API client holding the token the recording generated, as an agent would."""

    def __init__(self, token: str) -> None:
        self.client = Client()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get(self, path: str) -> Any:
        return self.client.get(path, **self.auth)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.client.post(path, data=json.dumps(body), content_type="application/json", **self.auth)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.client.patch(path, data=json.dumps(body), content_type="application/json", **self.auth)


@pytest.fixture
def scanned_workspace(
    sample_user: AbstractBaseUser, pied_piper_with_sboms: dict, monkeypatch: pytest.MonkeyPatch
) -> dict:
    """Completed OSV scans for every SBOM and their finding rows, in a public workspace."""
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    install_dict_backed_s3(monkeypatch)
    product = pied_piper_with_sboms["product"]
    team = product.team
    team.name = WORKSPACE_NAME
    team.is_public = True
    team.save(update_fields=["name", "is_public"])
    product.is_public = True
    product.save(update_fields=["is_public"])
    sample_user.first_name = USER_FIRST_NAME
    sample_user.last_name = USER_LAST_NAME
    sample_user.save(update_fields=["first_name", "last_name"])

    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": ["osv"]})
    # libwebp's CVE-2023-4863 is in CISA's KEV catalog; prime the cache the pages read.
    cache.set("cisa-kev-cve-ids", frozenset({TRIAGE_CVE.lower()}), 24 * 60 * 60)

    now = datetime.now(tz=timezone.utc)
    for offset, (component_name, sbom) in enumerate(pied_piper_with_sboms["sboms"].items()):
        scanned_at = now - timedelta(hours=3 * offset + 2)
        run = AssessmentRun.objects.create(
            id=uuid.uuid4(),
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            plugin_config_hash="0" * 64,
            category="security",
            run_reason=RunReason.ON_UPLOAD.value,
            status="completed",
            started_at=scanned_at,
            completed_at=scanned_at,
            input_content_digest="0" * 64,
            result=_security_result(component_name, scanned_at),
            result_schema_version="1.0",
        )
        AssessmentRun.objects.filter(pk=run.pk).update(created_at=scanned_at)
        run.refresh_from_db()
        sync_findings(run)

    return pied_piper_with_sboms


def _run_vex_reapply(component_id: Any) -> None:
    """Run the re-apply job the stub broker queued, in-process."""
    from sbomify.apps.vulnerability_scanning.tasks import reapply_vex_to_component_scans

    reapply_vex_to_component_scans.fn(str(component_id))


@pytest.mark.django_db(transaction=True)
def ai_agents(scanned_workspace: dict, recording_page: Page) -> None:
    # scanned_workspace first: it renames the workspace before the session is built.
    from sbomify.apps.vulnerability_scanning.services.vex_submissions import record_impact

    page = recording_page
    auto_dismiss_toasts(page)
    mock_vuln_trends(page)
    team = scanned_workspace["product"].team
    product = scanned_workspace["product"]
    core = scanned_workspace["components"][CORE_COMPONENT]

    # The opening line plays over the dashboard loading.
    narrate(page, "intro")
    start_on_dashboard(page, 600)

    # ── 1. A token for the agent ─────────────────────────────────────────
    narrate(page, "token_first")
    navigate_to_settings(page)
    navigate_to_settings_tab(page, "tokens")
    hover_and_click(page, page.get_by_role("button", name="Generate token").first)
    name = page.locator("#tokenGenerationForm input[name='description']")
    name.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, name)
    type_text(name, TOKEN_NAME, delay=60)

    narrate(page, "choose_agent_preset")
    scope = page.locator("#tokenGenerationForm select[name='scope']")
    hover_and_click(page, scope)
    scope.select_option("agent")
    explanation = page.locator("#createTokenModal").get_by_text("This token can read fix prompts")
    explanation.wait_for(state="visible", timeout=5_000)
    explanation.hover()

    narrate(page, "preset_can_cannot")
    settle(page)

    narrate(page, "generate_hand_over")
    hover_and_click(page, page.locator("#createTokenModal #generate-token-button"))
    page.get_by_text("Copy your token now").wait_for(state="visible", timeout=10_000)
    token = page.locator("[data-token-value]").first.inner_text().strip()
    agent = Agent(token)
    pace(page, 1200)

    # ── 2. CVE triage by the agent ───────────────────────────────────────
    prompt_query = urlencode(
        {
            "component_id": core.id,
            "advisory": TRIAGE_CVE,
            "package": "libwebp",
            "version": "1.2.4",
            "ecosystem": "generic",
            "purl": TRIAGE_PURL,
        }
    )
    prompt = agent.get(f"/api/v2/vulnerability-scanning/workspaces/{team.key}/fix-prompt?{prompt_query}")
    assert prompt.status_code == 200, prompt.content
    prompt_body = prompt.json()
    first_line = next(
        line for line in (prompt_body["triage_prompt"] or prompt_body["fix_prompt"]).splitlines() if line.strip()
    )
    narrate(page, "agent_reads_prompt")
    show_agent(
        page,
        [
            ("req", f"GET /api/v2/vulnerability-scanning/workspaces/{team.key}/fix-prompt"),
            ("dim", f"    ?advisory={TRIAGE_CVE}&package=libwebp"),
            _status_line(prompt),
            ("text", f"triage_prompt: {first_line[:150]}"),
        ],
    )
    pace(page, 2500)

    triage_path = f"/api/v2/vulnerability-scanning/components/{core.id}/triage"
    submitted = agent.post(
        f"{triage_path}?review=true",
        {
            "decisions": [
                {
                    "vuln_id": TRIAGE_CVE,
                    "purl": TRIAGE_PURL,
                    "state": "not_affected",
                    "justification": "code_not_reachable",
                    "detail": TRIAGE_DETAIL,
                }
            ],
            "context": TRIAGE_CONTEXT,
        },
    )
    assert submitted.status_code == 202, submitted.content
    submission = submitted.json()
    record_impact(submission["id"])
    narrate(page, "agent_sends_ruling")
    show_agent(
        page,
        [
            ("req", f"POST {triage_path}?review=true"),
            ("dim", f'    {{"vuln_id": "{TRIAGE_CVE}", "state": "not_affected",'),
            ("dim", '     "justification": "code_not_reachable"}'),
            _status_line(submitted),
            ("text", f'status: "{submission["status"]}"'),
        ],
    )
    pace(page, 1500)

    hover_and_click(page, sidebar_link(page, "Vulnerabilities"))
    page.wait_for_load_state("networkidle")
    review_tab = page.get_by_role("link", name=re.compile(r"^Review"))
    review_tab.wait_for(state="visible", timeout=15_000)
    narrate(page, "ruling_waits_review")
    hover_and_click(page, review_tab)
    page.wait_for_load_state("networkidle")
    approve = page.locator("#vex-review").get_by_role("button", name="Approve")
    approve.wait_for(state="visible", timeout=15_000)
    page.locator("#vex-review").get_by_text("AI agent").first.hover()
    pace(page, 1500)
    smooth_scroll(page, page.locator("#vex-review li li").first, 600)

    refused = agent.post(
        triage_path,
        {
            "decisions": [
                {
                    "vuln_id": TRIAGE_CVE,
                    "purl": TRIAGE_PURL,
                    "state": "not_affected",
                    "justification": "code_not_reachable",
                    "detail": TRIAGE_DETAIL,
                }
            ]
        },
    )
    assert refused.status_code == 403, refused.content
    narrate(page, "agent_tries_apply")
    show_agent(
        page,
        [
            ("req", f"POST {triage_path}"),
            ("dim", "    (the same ruling, without review)"),
            _status_line(refused),
            ("text", f"detail: {refused.json().get('detail', '')}"),
        ],
    )
    settle(page)

    narrate(page, "person_approves_ruling")
    hide_agent(page)
    with page.expect_response(lambda r: "/review/decide/" in r.url, timeout=20_000):
        hover_and_click(page, approve)
    page.locator("#vex-review").get_by_text("Nothing waiting").wait_for(state="visible", timeout=15_000)
    _run_vex_reapply(core.id)

    narrate(page, "vulnerability_closes")
    hover_and_click(page, page.get_by_role("link", name="Open vulnerabilities"))
    page.wait_for_load_state("networkidle")
    status = page.locator("#vulnerabilities-status")
    status.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, status)
    with page.expect_response(lambda r: "vulnerability-scans" in r.url and "status=decided" in r.url):
        status.select_option("decided")
    decided_row = page.locator(f"#vulnerabilities-results tr:has-text('{TRIAGE_CVE}')").first
    decided_row.wait_for(state="visible", timeout=15_000)
    decided_row.hover()

    # ── 3. A security advisory by the agent ──────────────────────────────
    created = agent.post(
        "/api/v2/advisories/",
        {
            "title": ADVISORY_TITLE,
            "severity": "critical",
            "identifier": FIX_CVE,
            "remediation_status": "investigating",
            "cvss_score": 9.8,
            "description": ADVISORY_DESCRIPTION,
            "product_ids": [product.id],
        },
    )
    assert created.status_code == 201, created.content
    advisory = created.json()
    advisory_id = advisory["id"]
    narrate(page, "agent_drafts_advisory")
    show_agent(
        page,
        [
            ("req", "POST /api/v2/advisories/"),
            ("dim", f'    {{"title": "{ADVISORY_TITLE[:44]}...",'),
            ("dim", f'     "identifier": "{FIX_CVE}", "severity": "critical"}}'),
            _status_line(created),
            ("text", f'status: "{advisory["status"]}"'),
        ],
    )
    pace(page, 2000)
    hide_agent(page)
    hover_and_click(page, sidebar_link(page, "Security advisories"))
    page.wait_for_load_state("networkidle")
    # The row navigates on click; aim at the title, not a product link in the row.
    advisory_link = page.locator("main tr span", has_text=ADVISORY_TITLE).first
    advisory_link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, advisory_link)
    page.wait_for_url(f"**/security-advisories/{advisory_id}/", timeout=15_000)
    page.wait_for_load_state("networkidle")
    banner = page.get_by_text("An AI agent drafted this advisory").first
    banner.wait_for(state="visible", timeout=15_000)
    narrate(page, "draft_only_workspace")
    banner.hover()

    publish_path = f"/api/v2/advisories/{advisory_id}/publish"
    refused_publish = agent.post(publish_path, {"visibility": "public"})
    assert refused_publish.status_code == 403, refused_publish.content
    narrate(page, "agent_tries_publish")
    show_agent(
        page,
        [
            ("req", f"POST {publish_path}"),
            ("dim", '    {"visibility": "public"}'),
            _status_line(refused_publish),
            ("text", f"detail: {refused_publish.json().get('detail', '')}"),
        ],
    )
    settle(page)

    narrate(page, "person_publishes")
    hide_agent(page)
    hover_and_click(page, page.get_by_role("button", name="Publish advisory").first)
    modal = page.locator("#publishAdvisoryModal")
    modal.get_by_role("button", name="Publish").wait_for(state="visible", timeout=10_000)
    public_option = modal.locator("label:has(input[name='visibility'][value='public'])")
    if public_option.count():
        hover_and_click(page, public_option)
    pace(page, 500)
    hover_and_click(page, modal.get_by_role("button", name="Publish"))
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="View in Trust Center").first.wait_for(state="visible", timeout=15_000)

    # The agent keeps working on the published advisory: both writes are held.
    update = agent.post(
        f"/api/v2/advisories/{advisory_id}/updates",
        {"kind": "fix_in_progress", "note": UPDATE_NOTE, "context": UPDATE_CONTEXT},
    )
    assert update.status_code == 202, update.content
    edit = agent.patch(f"/api/v2/advisories/{advisory_id}", {"severity": "medium", "context": SEVERITY_CONTEXT})
    assert edit.status_code == 202, edit.content
    update_id = update.json()["id"]
    edit_id = edit.json()["id"]
    narrate(page, "agent_changes_published")
    show_agent(
        page,
        [
            ("req", f"POST /api/v2/advisories/{advisory_id}/updates"),
            ("dim", '    {"kind": "fix_in_progress", "note": "A fix is in progress..."}'),
            _status_line(update),
            ("text", f'status: "{update.json()["status"]}"'),
            ("req", f"PATCH /api/v2/advisories/{advisory_id}"),
            ("dim", '    {"severity": "medium"}'),
            _status_line(edit),
            ("text", f'status: "{edit.json()["status"]}"'),
        ],
    )
    pace(page, 2500)
    hide_agent(page)
    page.reload()
    page.wait_for_load_state("networkidle")
    review = page.locator("#review")
    review.wait_for(state="visible", timeout=15_000)

    narrate(page, "proposals_with_diff")
    smooth_scroll(page, page.locator(f"#proposal-{update_id}"), 1200)
    smooth_scroll(page, page.locator(f"#proposal-{edit_id}"), 800)

    narrate(page, "approve_update")
    update_row = page.locator(f"#proposal-{update_id}")
    smooth_scroll(page, update_row, 400)
    hover_and_click(page, update_row.get_by_role("button", name="Approve", exact=True))
    page.wait_for_load_state("networkidle")
    edit_row = page.locator(f"#proposal-{edit_id}")
    edit_row.wait_for(state="visible", timeout=15_000)

    narrate(page, "reject_severity")
    smooth_scroll(page, edit_row, 400)
    hover_and_click(page, edit_row.get_by_role("button", name="Reject"))
    dialog = page.get_by_role("alertdialog")
    dialog.get_by_text("Not accurate").wait_for(state="visible", timeout=10_000)
    hover_and_click(page, dialog.get_by_text("Not accurate"))
    note = page.locator("#rejectProposalNote")
    hover_and_click(page, note)
    type_text(note, REJECT_NOTE, delay=25)
    pace(page, 300)
    hover_and_click(page, page.locator("button[form='rejectProposalForm']"))
    page.wait_for_load_state("networkidle")
    page.locator("#review").get_by_text("Nothing waiting").wait_for(state="visible", timeout=15_000)

    feedback = agent.get("/api/v2/advisories/proposals?status=rejected")
    assert feedback.status_code == 200, feedback.content
    rejected = feedback.json()[0]
    narrate(page, "agent_reads_reason")
    show_agent(
        page,
        [
            ("req", "GET /api/v2/advisories/proposals?status=rejected"),
            _status_line(feedback),
            ("text", f'rejection_reason: "{rejected["rejection_reason"]}"'),
            ("text", f'decision_note: "{rejected["decision_note"]}"'),
            ("text", f'next_step: "{rejected["next_step"]}"'),
        ],
    )
    settle(page)

    # ── 4. Close ─────────────────────────────────────────────────────────
    narrate(page, "close")
    hide_agent(page)
    decided = page.locator("#review summary", has_text="Recently decided")
    smooth_scroll(page, decided, 300)
    hover_and_click(page, decided)
    pace(page, 800)
