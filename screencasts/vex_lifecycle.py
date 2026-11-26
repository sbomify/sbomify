"""Record the VEX lifecycle screencast: where a VEX comes from, and what customers see.

Most VEX in sbomify is never written by hand. This recording tells the whole
story on one component, Compression Core Library, whose scan found two
criticals and two highs:

1. **Built in.** A person triages libwebp's critical in the app (Not affected,
   code not reachable). sbomify writes the component's VEX itself; the new VEX
   shows on the component's Latest versions card and its page lists what it
   suppresses.
2. **AI agent.** An agent holding an AI agent token rules the OpenSSL high not
   affected. Applying it directly is refused (403); sending it with
   ``review=true`` is accepted (202). A person approves it on the
   Vulnerabilities Review tab, and the ruling lands in the same VEX.
3. **Upload.** A VEX produced by another tool clears the krb5 high: Upload VEX,
   the dry-run preview, Apply.
4. **Trust Center.** The public release page shows three suppressed by VEX, the
   zlib critical still open, and one VEX download carrying every decision.

Every agent call goes through Django's test client with a token made with the
AI agent preset, so the status codes in the console are the API's own.

Seeding (preconditions only): a public Pied Piper workspace with a public
product, release v2.1.0 and one completed OSV scan projected into finding rows
with the real ``sync_findings``, the KEV cache primed, and the agent's token.
S3 is backed by a dict. The jobs the stub broker never runs (the ruling's impact
count, and re-applying VEX after a decision or upload) are run in-process.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from playwright.sync_api import Page

from conftest import (
    agent_console,
    agent_console_append,
    auto_dismiss_toasts,
    close_agent_console,
    hover_and_click,
    install_dict_backed_s3,
    mock_vuln_trends,
    narrate,
    navigate_to_components,
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
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import SBOM, Component, Product
from sbomify.apps.teams.models import Workspace

COMPONENT_NAME = "Compression Core Library"
PRODUCT_NAME = "Pied Piper Compression Engine"
SBOM_NAME = "com.piedpiper/compression-core"
VERSION = "2.1.0"
VEX_FILENAME = "compression-core-2.1.0.vex.cdx.json"

OPEN_CVE = "CVE-2023-45853"  # zlib, critical: real, and left open
TRIAGE_CVE = "CVE-2023-4863"  # libwebp, critical: a person triages it
AGENT_CVE = "CVE-2024-6119"  # openssl, high: an AI agent proposes a ruling
UPLOAD_CVE = "CVE-2024-37371"  # krb5, high: cleared by an uploaded VEX

# (cve, package, version, purl, severity, cvss, fixed)
FINDINGS = [
    (OPEN_CVE, "zlib", "1.2.13", "pkg:generic/zlib@1.2.13", "critical", 9.8, "1.3"),
    (TRIAGE_CVE, "libwebp", "1.2.4", "pkg:generic/libwebp@1.2.4", "critical", 8.8, "1.3.2"),
    (UPLOAD_CVE, "krb5", "1.20.1", "pkg:generic/krb5@1.20.1", "high", 8.1, "1.21.3"),
    (AGENT_CVE, "openssl", "3.0.13", "pkg:generic/openssl@3.0.13", "high", 7.5, "3.0.15"),
]

AGENT_TOKEN_NAME = "Claude Code"  # nosec B105 - the token's label, not a secret
API_BASE = "https://app.sbomify.com/api/v2/vulnerability-scanning"

TRIAGE_DETAIL = "libwebp is linked for thumbnail sizes only. The vulnerable decoder is never called."

AGENT_RULING = {
    "decisions": [
        {
            "vuln_id": AGENT_CVE,
            "purl": "pkg:generic/openssl@3.0.13",
            "state": "not_affected",
            "justification": "code_not_reachable",
            "detail": "Compression Core never verifies certificate names. TLS ends at the gateway.",
        }
    ],
    "context": (
        "I searched the source for X509_VERIFY_PARAM and every TLS call. The library only hashes with "
        "OpenSSL, so the name check this advisory is about is never reached."
    ),
}

# What another tool produced for krb5: a CycloneDX VEX for this version.
UPLOADED_VEX = json.dumps(
    {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:11111111-2222-3333-4444-555555555555",
        "version": 1,
        "metadata": {
            "timestamp": "2026-04-29T00:00:00Z",
            "component": {"type": "application", "name": SBOM_NAME, "version": VERSION},
        },
        "vulnerabilities": [
            {
                "id": UPLOAD_CVE,
                "source": {"name": "NVD"},
                "ratings": [{"severity": "high"}],
                "affects": [{"ref": "pkg:generic/krb5@1.20.1"}],
                "analysis": {
                    "state": "not_affected",
                    "justification": "requires_configuration",
                    "detail": "GSS message token handling is disabled in this build.",
                },
            }
        ],
    },
    indent=2,
).encode("utf-8")


def _security_result(scanned_at: datetime) -> dict[str, Any]:
    """One OSV ``AssessmentRun.result`` in the schema the plugin SDK emits."""
    findings = [
        {
            "id": cve,
            "title": f"{package} {version} is affected by {cve}",
            "description": f"{package} {version} is affected by {cve}. Upgrade to {fixed} or later.",
            "severity": severity,
            "status": "fail",
            "cvss_score": cvss,
            "fixed_version": fixed,
            "source": "osv",
            "component": {"name": package, "version": version, "purl": purl, "ecosystem": "generic"},
        }
        for cve, package, version, purl, severity, cvss, fixed in FINDINGS
    ]
    by_severity = {
        level: sum(1 for f in findings if f["severity"] == level) for level in ("critical", "high", "medium", "low")
    }
    by_severity["info"] = 0
    return {
        "schema_version": "1.0",
        "plugin_name": "osv",
        "plugin_version": "1.0.0",
        "category": "security",
        "assessed_at": scanned_at.isoformat(),
        "summary": {
            "total_findings": len(findings),
            "pass_count": 0,  # nosec B105 - a count, not a credential
            "fail_count": len(findings),
            "warning_count": 0,
            "error_count": 0,
            "by_severity": by_severity,
        },
        "findings": findings,
        "metadata": {"scanner": "osv-scanner", "provider": "osv"},
    }


@pytest.fixture
def vex_release(
    sample_user: AbstractBaseUser, deletable_team: Workspace, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> dict:
    """A public release whose scanned SBOM has two criticals and two highs, and an AI agent token."""
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    install_dict_backed_s3(monkeypatch)
    # The triage and fix prompts peek at the stored SBOM for a repository hint;
    # there is no SBOM bucket here, and the miss costs seconds of retries.
    monkeypatch.setattr(StorageClient, "get_sbom_data_prefix", lambda self, name, limit: None)
    settings.APP_BASE_URL = "https://app.sbomify.com"

    team = deletable_team
    team.is_public = True
    team.publish_vulnerability_posture = True
    team.save(update_fields=["is_public", "publish_vulnerability_posture"])
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": ["osv"]})
    # libwebp's CVE-2023-4863 is in CISA's KEV catalog; prime the cache the pages read.
    cache.set("cisa-kev-cve-ids", frozenset({TRIAGE_CVE.lower()}), 24 * 60 * 60)

    component = Component.objects.create(team=team, name=COMPONENT_NAME, visibility=Component.Visibility.PUBLIC)
    sbom = SBOM.objects.create(
        name=SBOM_NAME,
        version=VERSION,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="compression-core-2.1.0.cdx.json",
        source="api",
        bom_type=SBOM.BomType.SBOM,
        component=component,
    )
    product = Product.objects.create(
        team=team,
        name=PRODUCT_NAME,
        description="Middle-out compression platform for enterprise data optimization",
        is_public=True,
    )
    product.components.set([component])
    release = Release.objects.create(product=product, name=f"v{VERSION}", version=VERSION)
    ReleaseArtifact.objects.create(release=release, sbom=sbom)

    scanned_at = datetime.now(tz=timezone.utc) - timedelta(hours=2)
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
        result=_security_result(scanned_at),
        result_schema_version="1.0",
    )
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=scanned_at)
    run.refresh_from_db()
    sync_findings(run)

    # The token a person made with the AI agent preset and gave to Claude Code.
    token = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        team=team,
        encoded_token=token,
        description=AGENT_TOKEN_NAME,
        scopes=authz.SCOPE_PRESETS["agent"],
    )
    return {"component": component, "release": release, "product": product, "agent_token": token}


def _run_vex_reapply(component_id: Any) -> None:
    """Run the re-apply job the stub broker queued, in-process."""
    from sbomify.apps.vulnerability_scanning.tasks import reapply_vex_to_component_scans

    reapply_vex_to_component_scans.fn(str(component_id))


def _agent_triage(token: str, component_id: str, body: dict[str, Any], *, review: bool) -> Any:
    """What the agent sends: the real triage endpoint, with its AI agent token."""
    query = "?review=true" if review else ""
    return Client().post(
        f"/api/v2/vulnerability-scanning/components/{component_id}/triage{query}",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _curl(component_id: str, review: bool) -> list[str]:
    query = "?review=true" if review else ""
    return [
        "$ curl -X POST \\",
        f'    "{API_BASE}/components/{component_id}/triage{query}" \\',
        '    -H "Authorization: Bearer $SBOMIFY_TOKEN" --data @ruling.json',
    ]


def _open_row_menu(page: Page, cve: str) -> None:
    menu = page.get_by_role("button", name=re.compile(rf"^Actions for {cve} "))
    menu.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, menu)
    pace(page, 500)


def _triage_vex(component: Component) -> SBOM:
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    return (
        SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX, source=TRIAGE_SOURCE)
        .order_by("-created_at")
        .first()
    )


def _vex_url(component: Component, vex: SBOM) -> str:
    return reverse("core:component_item", kwargs={"component_id": component.id, "item_type": "vex", "item_id": vex.id})


@pytest.mark.django_db(transaction=True)
def vex_lifecycle(vex_release: dict, recording_page: Page) -> None:
    from sbomify.apps.vulnerability_scanning.services.vex_submissions import record_impact

    page = recording_page
    auto_dismiss_toasts(page)
    mock_vuln_trends(page)
    component = vex_release["component"]
    release = vex_release["release"]
    product = vex_release["product"]
    token = vex_release["agent_token"]
    component_url = reverse("core:component_details", kwargs={"component_id": component.id})
    public_url = reverse("core:release_details_public", kwargs={"product_id": product.id, "release_id": release.id})

    # The opening line plays over the dashboard and the walk to the component.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=600)
    navigate_to_components(page)
    link = page.locator("main").get_by_role("link", name=COMPONENT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    results = page.locator("#component-vulnerabilities-table")
    triage_row = results.locator(f"tr:has-text('{TRIAGE_CVE}')").first
    triage_row.wait_for(state="visible", timeout=15_000)

    narrate(page, "scan_found")
    smooth_scroll(page, page.locator("#component-vulnerabilities"), 600)
    pace(page, 1200)

    # ── 1. Built in: a person triages, sbomify writes the VEX ────────────
    narrate(page, "team_checks_libwebp")
    triage_row.hover()
    pace(page, 2500)

    narrate(page, "triage_not_affected")
    _open_row_menu(page, TRIAGE_CVE)
    hover_and_click(page, page.get_by_role("menuitem", name="Triage"))
    modal = page.locator("#triage-modal")
    modal.get_by_text("Applies to").wait_for(state="visible", timeout=15_000)
    state = page.locator("#triage-state")
    hover_and_click(page, state)
    state.select_option("not_affected")
    justification = page.locator("#triage-justification")
    hover_and_click(page, justification)
    justification.select_option("code_not_reachable")
    detail = page.locator("#triage-detail")
    hover_and_click(page, detail)
    type_text(detail, TRIAGE_DETAIL, delay=20)

    narrate(page, "save_writes_vex")
    with page.expect_response(lambda r: "/triage" in r.url and r.request.method == "POST", timeout=20_000) as resp:
        hover_and_click(page, modal.get_by_role("button", name="Save decision"))
    assert resp.value.ok, resp.value.text()
    _run_vex_reapply(component.id)
    pace(page, 800)
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    versions = page.get_by_role("table", name="Versions")
    versions.wait_for(state="visible", timeout=15_000)
    vex_row = versions.locator("tr", has_text="VEX").first
    vex_row.wait_for(state="visible", timeout=15_000)
    vex_row.hover()
    pace(page, 1500)

    narrate(page, "vex_on_component")
    hover_and_click(page, vex_row.get_by_role("link").first)
    page.wait_for_load_state("networkidle")
    suppressed = page.locator("main").get_by_text(TRIAGE_CVE).first
    suppressed.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, suppressed, 600)
    suppressed.hover()
    settle(page)

    # ── 2. AI agent: proposes, a person approves ─────────────────────────
    agent_console(
        page,
        f'Claude Code · API token "{AGENT_TOKEN_NAME}" (AI agent)',
        ["# OpenSSL CVE-2024-6119 is not reachable. Apply the ruling:", *_curl(component.id, review=False)],
    )
    narrate(page, "agent_tries_apply")
    refused = _agent_triage(token, component.id, AGENT_RULING | {"context": ""}, review=False)
    assert refused.status_code == 403, refused.content
    # The refusal appears only once the line has said the agent tries.
    settle(page)
    agent_console_append(page, "HTTP/1.1 403 Forbidden", json.dumps({"detail": refused.json()["detail"]}))

    narrate(page, "agent_refused")
    pace(page, 2600)
    agent_console_append(page, "", "# Send it for a person to approve instead:", *_curl(component.id, review=True))
    sent = _agent_triage(token, component.id, AGENT_RULING, review=True)
    assert sent.status_code == 202, sent.content
    record_impact(sent.json()["id"])
    settle(page)

    narrate(page, "agent_sends_review")
    pace(page, 300)
    agent_console_append(page, "HTTP/1.1 202 Accepted", json.dumps({"id": sent.json()["id"], "status": "pending"}))
    settle(page)

    narrate(page, "ruling_waits_review")
    close_agent_console(page)
    hover_and_click(page, sidebar_link(page, "Vulnerabilities"))
    page.wait_for_load_state("networkidle")
    review_tab = page.get_by_role("link", name=re.compile(r"^Review"))
    review_tab.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, review_tab)
    page.wait_for_load_state("networkidle")
    review = page.locator("#vex-review")
    approve = review.get_by_role("button", name="Approve").first
    approve.wait_for(state="visible", timeout=15_000)
    review.get_by_text("AI agent").first.hover()
    pace(page, 1200)
    smooth_scroll(page, review.locator("li li").first, 600)

    narrate(page, "approve_same_vex")
    with page.expect_response(lambda r: "/review/decide/" in r.url, timeout=20_000):
        hover_and_click(page, approve)
    review.get_by_text("Nothing waiting").wait_for(state="visible", timeout=15_000)
    _run_vex_reapply(component.id)
    pace(page, 600)
    page.goto(_vex_url(component, _triage_vex(component)))
    page.wait_for_load_state("networkidle")
    agent_row = page.locator("main").get_by_text(AGENT_CVE).first
    agent_row.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, agent_row, 600)
    agent_row.hover()
    settle(page)

    # ── 3. Upload: VEX another tool produced ─────────────────────────────
    narrate(page, "upload_other_tool")
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    actions = page.get_by_role("button", name="Component actions")
    actions.wait_for(state="visible", timeout=15_000)
    actions.hover()
    settle(page)

    narrate(page, "upload_from_menu")
    hover_and_click(page, actions)
    pace(page, 300)
    hover_and_click(page, page.get_by_role("menuitem", name="Upload VEX"))
    file_input = page.locator("#upload-sbom input[type='file']")
    file_input.wait_for(state="attached", timeout=10_000)
    pace(page, 400)
    with page.expect_response(lambda r: "/vex-preview" in r.url and r.status == 200, timeout=15_000):
        file_input.set_input_files(
            files=[{"name": VEX_FILENAME, "mimeType": "application/json", "buffer": UPLOADED_VEX}]
        )
    page.get_by_text("Preview: nothing stored yet").first.wait_for(state="visible", timeout=10_000)

    narrate(page, "preview_first")
    apply_btn = page.get_by_role("button", name="Apply this VEX")
    apply_btn.hover()
    settle(page)

    narrate(page, "apply_closes")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=15_000,
    ):
        hover_and_click(page, apply_btn)
    uploaded = (
        (SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX).exclude(source="sbomify-triage"))
        .order_by("-created_at")
        .first()
    )
    ReleaseArtifact.objects.get_or_create(release=release, sbom=uploaded)
    _run_vex_reapply(component.id)
    pace(page, 600)
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    open_row = page.locator(f"#component-vulnerabilities-table tr:has-text('{OPEN_CVE}')").first
    open_row.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, page.locator("#component-vulnerabilities"), 600)
    open_row.hover()
    settle(page)

    # ── 4. What customers see ────────────────────────────────────────────
    narrate(page, "trust_center")
    page.goto(public_url)
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    posture = page.get_by_text("suppressed by VEX").first
    posture.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, posture, 600)
    pace(page, 1500)

    narrate(page, "download_one_vex")
    download = page.locator("a[title='Download latest VEX (CycloneDX)']").first
    download.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, download, 300)
    download.hover()
