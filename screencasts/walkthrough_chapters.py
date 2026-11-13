"""Marketplace walkthrough — chapter steps, seed data, and per-chapter clips.

This module is the source of truth for the marketplace walkthrough. It holds:

* the Pied Piper seed (:func:`pied_piper_scanned`) — a workspace that already
  looks *lived in*, because an empty product tour sells nothing;
* one ``chapter_*`` function per act of the story (SBOMs in, vulnerabilities
  triaged by an AI agent and decided by a person, CRA compliance, an advisory
  an agent drafts and a person publishes, the Trust Center),
  each self-contained enough to open inside the app and close on a stable frame;
* a parametrized recording function that renders each chapter as its own short
  clip, for listings that cap video length.

``marketplace_walkthrough.py`` imports the same ``chapter_*`` functions and
plays them back-to-back as one continuous tour, so the long cut and the short
cuts can never drift apart.

Why the seed is ORM-written rather than driven through the UI: the existing
FAQ recordings demonstrate *creating* things, and that is the right subject
for a FAQ. A marketplace viewer wants to see the product with real data
already in it. Building four components, four SBOMs, and a month of scan
history through the UI would burn the whole runtime before the tour reached
anything worth showing.

What the tour does perform for real is the moments that carry the pitch, and
they are agent-first with a person in the loop. In :func:`chapter_vulnerabilities`
an AI agent rules on libwebp through the actual triage API with an
agent-preset token, is refused when it tries to apply the ruling itself, and
sends it for review; a person approves it on the Review tab, and the genuine
apply and re-apply path closes the finding (see :func:`fake_s3`). In
:func:`chapter_trust_center` the agent drafts an advisory over the API and is
refused publishing it; a person publishes it through the UI, turns on the
Trust Center, and flips the product public. :func:`chapter_compliance`
completes the CRA assessment through the UI.
"""

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    auto_dismiss_toasts,
    dismiss_toasts,
    enable_and_configure_trust_center,
    hover_and_click,
    narrate,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_inputs,
    rewrite_localhost_urls,
    settle,
    shot,
    sidebar_link,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.compliance.models import CRAAssessment, CRAScopeScreening, OSCALFinding
from sbomify.apps.compliance.services.document_generation_service import regenerate_all
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import Component, Product, ProductIdentifier, ProductLink
from sbomify.apps.security_advisories.models import AdvisoryEvent, AdvisoryProduct, SecurityAdvisory
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact
from sbomify.apps.vulnerability_scanning.findings import sync_findings
from sbomify.apps.vulnerability_scanning.models import VexSubmission
from sbomify.apps.vulnerability_scanning.services.vex_submissions import record_impact
from sbomify.apps.vulnerability_scanning.tasks import reapply_vex_to_component_scans

# ---------------------------------------------------------------------------
# Seed data — Silicon Valley's Pied Piper, with a believable dependency tree
#
# The advisories below are real, and are paired with the package each one
# actually affects, so anyone who pauses the video and looks a CVE up finds it
# checks out. The *products* are fictional; the point is a plausible spread of
# severities across four components rather than any claim about real software.
# ---------------------------------------------------------------------------

# The shared test fixtures name these "Test Business Team" / "Test User"; both
# show up in frame (sidebar, dashboard greeting), so the tour renames them.
WORKSPACE_NAME = "Pied Piper"
USER_FIRST_NAME = "Richard"
USER_LAST_NAME = "Hendricks"

CORE_COMPONENT = "Compression Core Library"
DASHBOARD_COMPONENT = "Web Dashboard"
API_COMPONENT = "REST API Service"
WORKER_COMPONENT = "Data Pipeline Worker"

PRODUCT_IDENTIFIERS = [
    ("cpe", "cpe:2.3:a:piedpiper:compression_engine:2.4.0:*:*:*:*:*:*:*"),
    ("purl", "pkg:github/piedpiper/compression-engine@2.4.0"),
    ("sku", "PP-CE-2400-ENT"),
]

PRODUCT_LINKS = [
    ("website", "Pied Piper", "https://piedpiper.com"),
    ("repository", "Source Code", "https://github.com/piedpiper/compression-engine"),
    ("documentation", "API Documentation", "https://docs.piedpiper.com/api"),
    ("security", "Security Policy", "https://piedpiper.com/security"),
]

# The finding the tour clears with a VEX. libwebp is linked into the core
# library but its decode path is never reached from the compression hot loop —
# exactly the "vulnerable but not exploitable" case VEX exists to express.
VEX_TARGET_CVE = "CVE-2023-4863"
VEX_TARGET_PURL = "pkg:generic/libwebp@1.2.4"
VEX_TARGET_PACKAGE = "libwebp"
VEX_TARGET_VERSION = "1.2.4"

# (cve, package, version, purl, ecosystem, severity, cvss, fixed)
FINDINGS_BY_COMPONENT: dict[str, list[tuple[str, str, str, str, str, str, float, str]]] = {
    CORE_COMPONENT: [
        ("CVE-2023-45853", "zlib", "1.2.13", "pkg:generic/zlib@1.2.13", "generic", "critical", 9.8, "1.3"),
        (VEX_TARGET_CVE, VEX_TARGET_PACKAGE, VEX_TARGET_VERSION, VEX_TARGET_PURL, "generic", "critical", 8.8, "1.3.2"),
        ("CVE-2024-37371", "krb5", "1.20.1", "pkg:generic/krb5@1.20.1", "generic", "high", 8.1, "1.21.3"),
        ("CVE-2024-6119", "openssl", "3.0.13", "pkg:generic/openssl@3.0.13", "generic", "high", 7.5, "3.0.15"),
    ],
    DASHBOARD_COMPONENT: [
        ("CVE-2024-21538", "cross-spawn", "7.0.3", "pkg:npm/cross-spawn@7.0.3", "npm", "high", 7.5, "7.0.5"),
        ("CVE-2024-4067", "micromatch", "4.0.5", "pkg:npm/micromatch@4.0.5", "npm", "medium", 5.3, "4.0.8"),
    ],
    API_COMPONENT: [
        ("CVE-2024-3651", "idna", "3.6", "pkg:pypi/idna@3.6", "pypi", "medium", 6.5, "3.7"),
        ("CVE-2024-35195", "requests", "2.31.0", "pkg:pypi/requests@2.31.0", "pypi", "medium", 5.6, "2.32.0"),
    ],
    WORKER_COMPONENT: [
        (
            "CVE-2023-50782",
            "cryptography",
            "41.0.7",
            "pkg:pypi/cryptography@41.0.7",
            "pypi",
            "high",
            7.5,
            "42.0.0",
        ),
        ("CVE-2024-34064", "jinja2", "3.1.3", "pkg:pypi/jinja2@3.1.3", "pypi", "medium", 5.4, "3.1.4"),
    ],
}

# Scan history: one entry per day of the dashboard's default 30-day window,
# oldest first, each the fraction of the component's findings that scan had
# discovered by then.
#
# It has to be *daily*, not weekly. The trends view buckets by calendar day and
# fills days with no scan as zero (it charts what each day's scan found, not a
# carried-forward posture), so a weekly cadence renders as a comb of isolated
# spikes dropping to the axis in between. A daily cadence is also the honest
# picture for the workspace being depicted: one scan per SBOM per day is what a
# team with CI-triggered scanning actually accumulates.
#
# The profile ramps with a couple of plateaus and small dips rather than rising
# monotonically, because advisories land in bursts and get remediated. It ends
# at 1.0 so the newest run — the one every drill-down reads — carries the full
# finding set.
SCAN_HISTORY_PROFILE: list[float] = [
    0.35, 0.35, 0.40, 0.40, 0.40, 0.50, 0.50, 0.45, 0.45, 0.60,
    0.60, 0.60, 0.55, 0.70, 0.70, 0.70, 0.65, 0.75, 0.75, 0.80,
    0.80, 0.75, 0.85, 0.90, 0.90, 0.85, 0.90, 1.00, 1.00, 1.00,
]  # fmt: skip

VEX_JUSTIFICATION_DETAIL = (
    "Pied Piper links libwebp for thumbnail preview only. The middle-out "
    "compression path never invokes the vulnerable Huffman decode routine, "
    "and preview rendering is disabled in all shipped builds."
)

# What the agent tells the person who reviews its libwebp ruling. Markdown: the
# Review tab renders it as the first thing under the row.
AGENT_VEX_CONTEXT = (
    "**Not affected.** I traced every call into libwebp from the compression core. "
    "Only the thumbnail preview links it, and preview rendering is disabled in all "
    "shipped builds, so the vulnerable Huffman decode is never reached."
)

# The advisory the agent drafts in chapter 5: the zlib finding seeded on the
# core library, which unlike libwebp genuinely affects the product.
AGENT_ADVISORY_CVE = "CVE-2023-45853"
AGENT_ADVISORY_TITLE = "Integer overflow in bundled zlib minizip"
AGENT_ADVISORY_DESCRIPTION = (
    "The Compression Core Library bundles zlib 1.2.13, whose minizip "
    "zipOpenNewFileInZip4_64 overflows on a long file name. Archive export is "
    "affected. Upgrading to zlib 1.3 is in progress."
)
AGENT_TOKEN_DESCRIPTION = "Claude Code agent"


def _security_result(component_name: str, scanned_at: datetime, finding_count: int | None = None) -> dict[str, Any]:
    """Build one provider's ``AssessmentRun.result`` for a component's findings.

    Mirrors the schema the OSV plugin emits (``sbomify/apps/plugins/sdk/results.py``):
    a ``summary`` the dashboards read for severity counts, plus a ``findings``
    array the drill-down table flattens into rows. The ``component`` block on
    each finding carries the purl, which is what the VEX matcher keys on.

    ``finding_count`` truncates to the first N findings, which is how the
    historical runs in :data:`SCAN_HISTORY_DAYS` are built — advisories are
    published against dependencies you already shipped, so an older scan of the
    same SBOM legitimately knew about fewer of them.
    """
    rows = FINDINGS_BY_COMPONENT[component_name]
    if finding_count is not None:
        rows = rows[:finding_count]
    findings = [
        {
            "id": cve,
            "title": f"{package} {version} is affected by {cve}",
            "description": (f"{package} {version} is affected by {cve}. Upgrade to {fixed} or later to remediate."),
            "severity": severity,
            "status": "fail",
            "cvss_score": cvss,
            "fixed_version": fixed,
            "source": "osv",
            "component": {
                "name": package,
                "version": version,
                "purl": purl,
                "ecosystem": ecosystem,
            },
        }
        for cve, package, version, purl, ecosystem, severity, cvss, fixed in rows
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
            "pass_count": 0,  # nosec B105 — a count of passing findings, not a credential
            "fail_count": len(findings),
            "warning_count": 0,
            "error_count": 0,
            "by_severity": by_severity,
        },
        "findings": findings,
        "metadata": {"scanner": "osv-scanner", "provider": "osv"},
    }


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], bytes]:
    """Back :class:`StorageClient` with an in-process dict instead of a bucket.

    The screencast compose stack runs no S3 service. The other recordings
    work around that by no-op'ing the *write* (``vex_upload.py``), which is
    enough to make an upload return 201 — but the bytes are gone, so nothing
    that reads them back can work. This tour needs the round trip: approving
    the agent's ruling writes a VEX that the re-apply job has to read back and
    match against the seeded findings for the suppression to appear on
    screen, and the CRA documents are generated into the store too.

    Storing the payload in a dict keyed by ``(bucket, object)`` gives us that
    round trip while leaving every layer above the object store — the triage
    writer, ``derive_vex_suppressions``, ``find_matching_statement`` — running
    for real. What you see suppressed on screen was genuinely suppressed by the
    matcher, not staged.
    """
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: StorageClient, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: StorageClient, bucket_name: str, object_name: str) -> bytes | None:
        return store.get((bucket_name, object_name))

    monkeypatch.setattr(StorageClient, "upload_data_as_file", _put)
    monkeypatch.setattr(StorageClient, "get_file_data", _get)
    return store


def _seed_cra_assessment(product: Any, user: AbstractBaseUser) -> None:
    """A CRA assessment with steps 1 to 4 done and every document generated.

    Chapter 4 opens it from the Compliance list and completes it on camera.
    The wizard refuses a placeholder manufacturer, so the workspace Parties
    gets a real one first. Documents are generated through the real service,
    into the faked object store.
    """
    team = product.team
    profile = ContactProfile.objects.create(team=team, name="Pied Piper", is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Pied Piper B.V.",
        email="compliance@example.com",
        address="Keizersgracht 100, 1015 AA Amsterdam, Netherlands",
        is_manufacturer=True,
        is_supplier=True,
    )
    ContactProfileContact.objects.create(
        entity=entity, name="Richard Hendricks", email="security@example.com", is_security_contact=True
    )
    CRAScopeScreening.objects.create(product=product, team=team, has_data_connection=True)

    assessment = get_or_create_assessment(product.id, user, team).value
    assert assessment is not None
    CRAAssessment.objects.filter(pk=assessment.pk).update(
        intended_use="Middle-out compression for enterprise data pipelines.",
        target_eu_markets=["AT", "BE", "DE", "DK", "ES", "FI", "FR", "IE", "IT", "NL", "PL", "SE"],
        support_period_end=date(2031, 3, 15),
        conformity_assessment_procedure="module_a",
        is_eu_established=True,
        csirt_country="NL",
        acknowledgment_timeline_days=5,
        update_frequency="as-needed",
        update_method="Package manager",
        support_email="security@example.com",
        data_deletion_instructions="Remove the library from your build and delete its cache directory.",
        completed_steps=[1, 2, 3, 4],
        current_step=5,
        status=CRAAssessment.WizardStatus.IN_PROGRESS,
    )
    assessment.refresh_from_db()
    OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).update(
        status=OSCALFinding.FindingStatus.SATISFIED
    )
    regenerate_all(assessment)


def _seed_published_advisory(team: Any, product: Any) -> None:
    """Publish one resolved security advisory for the workspace.

    The trust center now leads with a Security Advisories section, and with
    none published the tour's closing frame is three zeros over a "No
    published advisories" empty state — which argues against the page it is
    meant to sell. One resolved, published advisory is also the honest
    depiction: a team that has disclosed something and shipped the fix.

    Mirrors the publish path the app enforces — ``status`` PUBLISHED needs a
    ``published_at`` and a tracking id, and the advisory only reaches the
    public page once ``visibility`` is PUBLIC.
    """
    now = datetime.now(tz=timezone.utc)
    advisory = SecurityAdvisory.objects.create(
        team=team,
        title="Path traversal in archive extraction",
        severity="medium",
        description=(
            "Archive entries with parent-directory segments could be written outside the "
            "extraction root. Fixed by normalising entry paths before write."
        ),
        remediation_status=SecurityAdvisory.RemediationStatus.RESOLVED,
        status=SecurityAdvisory.Status.PUBLISHED,
        published_at=now,
        visibility=SecurityAdvisory.Visibility.PUBLIC,
        made_public_at=now,
        tracking_id=SecurityAdvisory.allocate_tracking_id(team),
    )
    AdvisoryProduct.objects.create(advisory=advisory, product=product, product_name=product.name)
    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.PUBLISHED,
        payload={"tracking_id": advisory.tracking_id},
    )


@pytest.fixture
def pied_piper_scanned(
    sample_user: AbstractBaseUser,
    pied_piper_with_sboms: dict,
    fake_s3: dict,
) -> dict:
    """Layer branding, product metadata, and completed scans over the hierarchy.

    ``pied_piper_with_sboms`` (conftest) gives us the product, four components,
    and one CycloneDX SBOM each — plus the auto-created "latest" release the
    SBOM signal fires. This fixture adds the three things a marketing frame
    needs on top of that:

    1. **Branding.** The shared test fixtures name the workspace "Test Business
       Team" and the user "Test User", which land in the sidebar and in the
       dashboard greeting. Renaming them here keeps the whole frame in the
       Pied Piper world instead of half-advertising the test suite.
    2. **Product metadata.** Identifiers, links, and lifecycle dates — the part
       of a product record that answers a procurement questionnaire, and the
       part the tour's chapter 1 lingers on.
    3. **Scans.** One completed ``security`` AssessmentRun per SBOM, which is
       what lights up the dashboard digest and the component drill-down,
       projected into the finding rows the vulnerability lists read.
    4. **CRA.** A manufacturer in the workspace Parties and an assessment with
       steps 1 to 4 done and every document generated, which chapter 4 opens
       and completes.

    ``created_at`` is rewritten after insert because it is ``auto_now_add`` —
    without the rewrite every scan reads "scanned 0 minutes ago", which is
    exactly the tell that makes a demo look staged. Staggering them gives the
    digest a plausible week of activity.
    """
    team = pied_piper_with_sboms["product"].team
    team.name = WORKSPACE_NAME
    team.save(update_fields=["name"])

    sample_user.first_name = USER_FIRST_NAME
    sample_user.last_name = USER_LAST_NAME
    sample_user.save(update_fields=["first_name", "last_name"])

    product = pied_piper_with_sboms["product"]
    for identifier_type, value in PRODUCT_IDENTIFIERS:
        ProductIdentifier.objects.create(product=product, team=team, identifier_type=identifier_type, value=value)
    for link_type, title, url in PRODUCT_LINKS:
        ProductLink.objects.create(product=product, team=team, link_type=link_type, title=title, url=url)

    product.release_date = date(2026, 3, 15)
    product.end_of_support = date(2028, 3, 15)
    product.end_of_life = date(2029, 3, 15)
    product.save(update_fields=["release_date", "end_of_support", "end_of_life"])

    # Components ship public; the *product* stays private so chapter 4 can flip
    # it on camera. Without public components the trust center renders its
    # empty state — a closing frame that argues against the feature it is
    # meant to sell.
    Component.objects.filter(pk__in=[c.pk for c in pied_piper_with_sboms["components"].values()]).update(
        visibility=Component.Visibility.PUBLIC
    )

    # Turn OSV on for the workspace. The scans below are seeded directly, but
    # the enabled-plugin list is what several surfaces read to decide whether
    # to show security state at all — with it unset the trust center renders an
    # admin nag ("Enable vulnerability scanning…") over a page that is visibly
    # full of scan results.
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": ["osv"]})

    # A workspace-wide compliance artifact. The trust center counts public
    # global components under "Compliance artifacts"; a real workspace has a
    # SOC 2 report or similar sitting there, and a zero reads as an unfinished
    # setup rather than a feature.
    Component.objects.create(
        team=team,
        name="SOC 2 Type II Report",
        component_type=Component.ComponentType.DOCUMENT,
        is_global=True,
        visibility=Component.Visibility.PUBLIC,
    )

    _seed_published_advisory(team, product)

    now = datetime.now(tz=timezone.utc)
    last_day = len(SCAN_HISTORY_PROFILE) - 1
    for offset, (component_name, sbom) in enumerate(pied_piper_with_sboms["sboms"].items()):
        total = len(FINDINGS_BY_COMPONENT[component_name])
        # Components scan a few hours apart within each day, so the "Recent
        # SBOM Scans" strip reads as four separate jobs rather than a batch.
        history = [
            (
                now - timedelta(days=last_day - day, hours=5 * offset + 3),
                max(1, round(total * fraction)),
            )
            for day, fraction in enumerate(SCAN_HISTORY_PROFILE)
        ]

        for scanned_at, finding_count in history:
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
                result=_security_result(component_name, scanned_at, finding_count),
                result_schema_version="1.0",
            )
            AssessmentRun.objects.filter(pk=run.pk).update(created_at=scanned_at)
        # The vulnerability lists read a projection of each run's findings
        # that scan completion maintains, not the run's stored result. Without
        # it every list reads "Vulnerability details unavailable".
        run.refresh_from_db()
        sync_findings(run, fresh=True)

    _seed_cra_assessment(product, sample_user)

    # The token Richard made for his coding agent, with the "For an AI agent"
    # preset. Chapters 3 and 5 drive the real API with it. Only its hash is
    # stored, so the token itself is kept here for the chapters to send.
    _AGENT_TOKEN["value"] = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        team=team,
        encoded_token=_AGENT_TOKEN["value"],
        description=AGENT_TOKEN_DESCRIPTION,
        scopes=SCOPE_PRESETS["agent"],
    )
    return pied_piper_with_sboms


# ---------------------------------------------------------------------------
# Shared steps
# ---------------------------------------------------------------------------

_AGENT_TOKEN: dict[str, str] = {}


def _agent_call(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """One request from the AI agent: the real API, with the agent-preset token.

    In-process through Django's test client, like ``oidc_trusted_publishing``,
    so the request does not have to cross the Docker network. Same URL, same
    headers and body an agent's ``curl`` would send; nothing on the server
    side is stubbed.
    """
    response = getattr(Client(), method.lower())(
        path,
        data=json.dumps(body or {}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_AGENT_TOKEN['value']}",
    )
    return response.status_code, response.json()


_TERMINAL_ID = "__walkthrough-agent-terminal"


def _agent_terminal(page: Page, lines: list[tuple[str, str]]) -> None:
    """Show what the agent did as a terminal pinned to the bottom right.

    The agent's calls are invisible, so the recording draws them. ``lines``
    are ``(kind, text)`` with kind ``cmd`` (a request), ``ok``, ``refused`` or
    ``note``. Rebuilt from scratch on each call, so a caller appends by
    passing the longer list. Text is set with ``textContent``; all of it comes
    from this script and the API's own responses.
    """
    page.evaluate(
        """({id, lines}) => {
            let el = document.getElementById(id);
            if (!el) {
                el = document.createElement('div');
                el.id = id;
                el.style.cssText = `
                    position: fixed; right: 28px; bottom: 28px; z-index: 10000;
                    width: 760px; border-radius: 12px; overflow: hidden;
                    background: #0d1117; color: #e6edf3;
                    border: 1px solid rgba(255,255,255,0.12);
                    box-shadow: 0 18px 48px rgba(0,0,0,0.45);
                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                `;
                const bar = document.createElement('div');
                bar.style.cssText = 'display:flex; align-items:center; gap:8px; padding:10px 16px;' +
                    ' background:#161b22; font: 600 14px ui-sans-serif, system-ui, sans-serif; color:#c9d1d9;';
                for (const c of ['#ff5f56', '#ffbd2e', '#27c93f']) {
                    const dot = document.createElement('span');
                    dot.style.cssText = `width:11px; height:11px; border-radius:50%; background:${c};`;
                    bar.appendChild(dot);
                }
                const name = document.createElement('span');
                name.style.cssText = 'margin-left:10px;';
                name.textContent = 'AI agent · token preset "For an AI agent"';
                bar.appendChild(name);
                el.appendChild(bar);
                const body = document.createElement('div');
                body.dataset.role = 'body';
                body.style.cssText = 'padding:14px 18px 16px; font-size:15px; line-height:1.55;';
                el.appendChild(body);
                document.body.appendChild(el);
            }
            const body = el.querySelector('[data-role=body]');
            while (body.firstChild) body.removeChild(body.firstChild);
            const colours = {cmd: '#e6edf3', ok: '#3fb950', refused: '#ff7b72', note: '#8b949e'};
            for (const [kind, text] of lines) {
                const row = document.createElement('div');
                row.style.cssText = `color:${colours[kind] || '#e6edf3'}; white-space:pre-wrap;` +
                    ' overflow-wrap:anywhere;' + (kind === 'cmd' ? ' margin-top:6px;' : '');
                row.textContent = (kind === 'cmd' ? '$ ' : '  ') + text;
                body.appendChild(row);
            }
        }""",
        {"id": _TERMINAL_ID, "lines": lines},
    )


def _hide_agent_terminal(page: Page) -> None:
    page.evaluate(f"document.getElementById('{_TERMINAL_ID}')?.remove()")


def _nav(page: Page, label: str) -> None:
    """Follow a sidebar link with a short settle.

    The conftest ``navigate_to_*`` helpers hold 1.2 s after each load, which
    the narrated tour turns into dead air between lines.
    """
    hover_and_click(page, sidebar_link(page, label))
    page.wait_for_load_state("networkidle")
    pace(page, 300)


def _open_product(page: Page) -> None:
    _nav(page, "Products")
    link = page.get_by_role("link", name=PIED_PIPER_PRODUCT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    pace(page, 400)


def _open_core_component(page: Page) -> None:
    _nav(page, "Components")
    link = page.get_by_role("link", name=CORE_COMPONENT, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    pace(page, 400)


def _product_detail_tab(page: Page, tab: str, card_selector: str) -> None:
    """Open one of the product page's detail tabs and pan to its card.

    Links and Identifiers load their card over HTMX on the first click, so the
    card only exists after the tab is pressed.
    """
    tab_btn = page.get_by_role("tab", name=tab, exact=True)
    smooth_scroll(page, tab_btn, 300)
    hover_and_click(page, tab_btn)
    card = page.locator(card_selector)
    card.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, card, 400)


# ---------------------------------------------------------------------------
# Chapter 1 — SBOMs in: the product and what it is made of
# ---------------------------------------------------------------------------


def chapter_supply_chain(page: Page) -> None:
    """Dashboard → Products → the product's record.

    Establishes the model the rest of the tour builds on: a workspace holds
    products, a product holds components, and the product carries the
    identifiers and lifecycle dates a customer or a regulator asks for.
    """
    narrate(page, "supply_chain_intro")
    start_on_dashboard(page, pause_ms=600)
    shot(page, "01-dashboard")
    settle(page)

    narrate(page, "supply_chain_products_group_components")
    _nav(page, "Products")
    shot(page, "02-products-list")
    settle(page)

    narrate(page, "supply_chain_pied_piper_s")
    _open_product(page)
    shot(page, "03-product-overview")
    settle(page)

    narrate(page, "supply_chain_cpe_purl_sku")
    _product_detail_tab(page, "Identifiers", "#product-identifiers-card")
    shot(page, "04-product-identifiers")
    settle(page)

    narrate(page, "supply_chain_lifecycle_dates_set")
    _product_detail_tab(page, "Lifecycle", "#product-lifecycle-card")
    shot(page, "05-product-lifecycle")
    settle(page)


# ---------------------------------------------------------------------------
# Chapter 2 — every artifact, versioned
# ---------------------------------------------------------------------------


def chapter_inventory(page: Page) -> None:
    """Components → a component's versions → the release that ships them."""
    narrate(page, "inventory_intro")
    _nav(page, "Components")
    shot(page, "06-component-inventory")
    settle(page)

    narrate(page, "inventory_artifacts_stored_exactly")
    link = page.get_by_role("link", name=CORE_COMPONENT, exact=True).first
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    shot(page, "07-component-artifacts")
    settle(page)

    narrate(page, "inventory_releases_pin_exact")
    _open_product(page)
    releases = page.get_by_role("heading", name="Releases", exact=True)
    smooth_scroll(page, releases, 500)
    shot(page, "08-releases")
    settle(page)

    release_link = page.locator("a[href*='/release/']").first
    release_link.wait_for(state="visible", timeout=15_000)
    narrate(page, "inventory_years_later_release")
    hover_and_click(page, release_link)
    page.wait_for_load_state("networkidle")
    shot(page, "09-release-artifacts")
    settle(page)


# ---------------------------------------------------------------------------
# Chapter 3 — vulnerabilities, triaged by an agent, decided by a person
# ---------------------------------------------------------------------------


def _agent_rules_libwebp(page: Page) -> None:
    """The agent's libwebp ruling, through the real triage API.

    It tries to apply the ruling first, which an agent-preset token may not do
    (``artifact:publish_vex`` is outside the preset), and the API's 403 says to
    send it for review. The resend with ``review=true`` queues it: nothing
    changes until a person approves it.
    """
    component = Component.objects.get(name=CORE_COMPONENT)
    path = f"/api/v1/vulnerability-scanning/components/{component.id}/triage"
    decision = {
        "vuln_id": VEX_TARGET_CVE,
        "purl": VEX_TARGET_PURL,
        "state": "not_affected",
        "justification": "code_not_reachable",
        "detail": VEX_JUSTIFICATION_DETAIL,
    }
    request_lines = [
        ("cmd", f"POST {path}"),
        ("note", f"{VEX_TARGET_CVE}  libwebp  not_affected  code_not_reachable"),
    ]

    narrate(page, "vulnerabilities_agent_rules")
    _agent_terminal(page, request_lines)
    pace(page, 2500)

    status, body = _agent_call("POST", path, {"decisions": [decision]})
    assert status == 403, (status, body)
    lines = request_lines + [("refused", f"{status} {body['detail']}")]
    narrate(page, "vulnerabilities_agent_refused")
    _agent_terminal(page, lines)
    pace(page, 3200)

    status, body = _agent_call("POST", f"{path}?review=true", {"decisions": [decision], "context": AGENT_VEX_CONTEXT})
    assert status == 202, (status, body)
    # The impact count is filled in by a background task; the stack runs no worker.
    record_impact(body["id"])
    lines += [
        ("cmd", f"POST {path}?review=true"),
        ("ok", f"{status} status: {body['status']}, waiting for a person to approve"),
    ]
    _agent_terminal(page, lines)
    settle(page)


def chapter_vulnerabilities(page: Page) -> None:
    """Workspace vulnerabilities → trends → a component → an agent's ruling → a person approves.

    The agent rules libwebp not affected over the real API, is refused when it
    tries to apply the ruling itself, and sends it for review. A person
    approves it on the Review tab. The chapter closes on the payoff: the
    critical libwebp row leaves the open list, and is still there, with its
    reason, under "Closed by a decision" (ADR-004: nothing is deleted).
    """
    narrate(page, "vulnerabilities_intro")
    _nav(page, "Vulnerabilities")
    shot(page, "10-vulnerability-posture")
    settle(page)

    narrate(page, "vulnerabilities_trends_show_exposure")
    _nav(page, "Overview")
    trends = page.get_by_role("link", name="Trends", exact=True)
    hover_and_click(page, trends)
    page.wait_for_load_state("networkidle")
    shot(page, "11-vulnerability-trends")
    settle(page)

    narrate(page, "vulnerabilities_component_each_vulnerability")
    _open_core_component(page)
    vulns = page.get_by_role("button", name="Vulnerabilities", exact=True).first
    smooth_scroll(page, vulns, 500)
    shot(page, "12-vulnerability-drilldown")
    settle(page)

    # ── The agent's ruling, through the real API ──────────────────────────
    _agent_rules_libwebp(page)

    # ── The Review tab: a person decides ──────────────────────────────────
    narrate(page, "vulnerabilities_review_tab")
    _hide_agent_terminal(page)
    _nav(page, "Vulnerabilities")
    hover_and_click(page, page.get_by_role("link", name=re.compile(r"^Review")))
    page.wait_for_load_state("networkidle")
    review = page.locator("#vex-review")
    approve = review.get_by_role("button", name="Approve")
    approve.wait_for(state="visible", timeout=15_000)
    review.get_by_text("AI agent", exact=True).first.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, review.locator("li li").first, 500)
    shot(page, "13-vex-preview")
    settle(page)

    narrate(page, "vulnerabilities_person_approves")
    pace(page, 1200)
    with page.expect_response(lambda r: "/review/decide/" in r.url, timeout=20_000):
        hover_and_click(page, approve)
    review.get_by_text("Nothing waiting").wait_for(state="visible", timeout=15_000)
    assert VexSubmission.objects.filter(status=VexSubmission.Status.APPROVED).count() == 1
    # Approval writes the VEX and queues the re-apply that annotates the
    # stored scans. The screencast stack runs no worker, so run that job here.
    reapply_vex_to_component_scans.fn(Component.objects.get(name=CORE_COMPONENT).id)
    settle(page)

    narrate(page, "vulnerabilities_applied_drops_out")
    _open_core_component(page)
    suppressed_badge = page.get_by_text("1 suppressed").first
    suppressed_badge.wait_for(state="visible", timeout=15_000)
    table = page.locator("#component-vulnerabilities-status")
    smooth_scroll(page, table, 500)
    shot(page, "14-vex-suppressed-hidden")
    settle(page)

    narrate(page, "vulnerabilities_nothing_deleted_vulnerability")
    hover_and_click(page, table)
    table.select_option("decided")
    page.wait_for_load_state("networkidle")
    suppressed = page.get_by_text("Not affected").first
    suppressed.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, suppressed, 400)
    suppressed.hover()
    shot(page, "15-vex-suppression")
    settle(page)


# ---------------------------------------------------------------------------
# Chapter 4 — CRA compliance
# ---------------------------------------------------------------------------


def chapter_compliance(page: Page) -> None:
    """Compliance list → the assessment's review step → mark it complete."""
    narrate(page, "compliance_intro")
    _nav(page, "Compliance")
    shot(page, "18-cra-assessments")
    settle(page)

    narrate(page, "compliance_scope_screening_sbom")
    hover_and_click(page, page.get_by_role("link", name="Continue").first)
    page.wait_for_url("**/step/5/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    shot(page, "19-cra-summary")
    settle(page)

    documents = page.get_by_role("heading", name="Documents", exact=True)
    narrate(page, "compliance_sbomify_writes_documents")
    smooth_scroll(page, documents, 500)
    settle(page)

    complete_btn = page.get_by_role("button", name="Mark Assessment Complete")
    smooth_scroll(page, complete_btn, 400)
    narrate(page, "compliance_every_control_answered")
    with page.expect_navigation():
        hover_and_click(page, complete_btn)
    page.wait_for_load_state("networkidle")
    pace(page, 600)

    narrate(page, "compliance_back_list_assessment")
    hover_and_click(page, sidebar_link(page, "Compliance"))
    page.wait_for_load_state("networkidle")
    page.get_by_text("Complete", exact=True).first.wait_for(state="visible", timeout=10_000)
    settle(page)


# ---------------------------------------------------------------------------
# Chapter 5 — security advisories and the Trust Center
# ---------------------------------------------------------------------------


def _agent_drafts_advisory(page: Page) -> str:
    """The agent drafts the zlib advisory over the real API, then is refused publishing it.

    ``advisory:manage`` is in the agent preset, so the draft is written at
    once. ``advisory:publish`` is not: publishing, withdrawing and deleting
    stay with a person, and the API answers 403. Returns the draft's id.
    """
    product = Product.objects.get(name=PIED_PIPER_PRODUCT_NAME)
    draft = {
        "title": AGENT_ADVISORY_TITLE,
        "identifier": AGENT_ADVISORY_CVE,
        "severity": "critical",
        "cvss_score": 9.8,
        "remediation_status": "fix_in_progress",
        "description": AGENT_ADVISORY_DESCRIPTION,
        "product_ids": [str(product.id)],
    }
    create_lines = [
        ("cmd", "POST /api/v1/advisories/"),
        ("note", f"{AGENT_ADVISORY_CVE}  critical 9.8  {PIED_PIPER_PRODUCT_NAME}"),
    ]
    _agent_terminal(page, create_lines)
    status, body = _agent_call("POST", "/api/v1/advisories/", draft)
    assert status == 201, (status, body)
    advisory_id = body["id"]
    lines = create_lines + [("ok", f"{status} status: {body['status']}")]
    pace(page, 1500)
    _agent_terminal(page, lines)
    pace(page, 1500)

    publish_path = f"/api/v1/advisories/{advisory_id}/publish"
    lines += [("cmd", f"POST {publish_path}"), ("note", "visibility: public")]
    narrate(page, "trust_center_agent_cannot_publish")
    _agent_terminal(page, lines)
    pace(page, 1500)
    status, body = _agent_call("POST", publish_path, {"visibility": "public"})
    assert status == 403, (status, body)
    lines += [
        ("refused", f"{status} {body['detail']}"),
        ("note", "advisory:publish is not in the agent preset"),
    ]
    _agent_terminal(page, lines)
    settle(page)
    return advisory_id


def chapter_trust_center(page: Page) -> None:
    """An agent drafts an advisory → a person publishes it → the Trust Center shows it."""
    narrate(page, "trust_center_intro")
    _nav(page, "Security advisories")
    pace(page, 600)
    _agent_drafts_advisory(page)

    narrate(page, "trust_center_draft_waits")
    _hide_agent_terminal(page)
    page.reload()
    page.wait_for_load_state("networkidle")
    # The row navigates on click; the title itself is a plain span in it.
    draft_link = page.locator("main").get_by_text(AGENT_ADVISORY_TITLE, exact=True).first
    draft_link.wait_for(state="visible", timeout=15_000)
    shot(page, "20-security-advisories")
    hover_and_click(page, draft_link)
    page.wait_for_url("**/security-advisories/*/", timeout=15_000)
    page.wait_for_load_state("networkidle")
    page.get_by_text("An AI agent drafted this advisory").first.wait_for(state="visible", timeout=15_000)
    shot(page, "21-advisory-agent-draft")
    settle(page)

    narrate(page, "trust_center_person_publishes")
    hover_and_click(page, page.get_by_role("button", name="Publish advisory").first)
    modal = page.locator("#publishAdvisoryModal")
    modal.get_by_role("button", name="Publish").wait_for(state="visible", timeout=10_000)
    pace(page, 600)
    hover_and_click(page, modal.locator("label:has(input[name='visibility'][value='public'])"))
    pace(page, 600)
    hover_and_click(page, modal.get_by_role("button", name="Publish"))
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="View in Trust Center").first.wait_for(state="visible", timeout=15_000)
    dismiss_toasts(page)
    settle(page)

    narrate(page, "trust_center_turn_trust_center")
    navigate_to_trust_center_tab(page)
    enable_and_configure_trust_center(page)
    rewrite_localhost_urls(page)
    rewrite_localhost_inputs(page)
    narrate(page, "trust_center_serve_own_domain")
    shot(page, "16-trust-center-config")
    settle(page)

    narrate(page, "trust_center_decide_what_goes")
    _open_product(page)
    visibility = page.get_by_role("button", name="Product visibility")
    hover_and_click(page, visibility)
    pace(page, 500)
    hover_and_click(page, page.get_by_role("menuitemradio", name="Public"))
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 1200)

    narrate(page, "trust_center_what_customers_see")
    page.goto("/public/workspace/")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    page.get_by_text(AGENT_ADVISORY_TITLE).first.wait_for(state="visible", timeout=15_000)
    shot(page, "17-trust-center-public")
    settle(page)
    page.mouse.wheel(0, 700)
    pace(page, 1500)


# ---------------------------------------------------------------------------
# Per-chapter clips
# ---------------------------------------------------------------------------

# Each entry is (slug, eyebrow, title, step function). ``marketplace_walkthrough``
# imports this to play the same chapters as one continuous tour.
CHAPTERS: list[tuple[str, str, str, Callable[[Page], None]]] = [
    ("supply_chain", "Chapter 1", "Know what you ship", chapter_supply_chain),
    ("inventory", "Chapter 2", "Every SBOM, versioned", chapter_inventory),
    ("vulnerabilities", "Chapter 3", "Triage with an AI agent", chapter_vulnerabilities),
    ("compliance", "Chapter 4", "Prove CRA compliance", chapter_compliance),
    ("trust_center", "Chapter 5", "Disclose it to customers", chapter_trust_center),
]

_CHAPTERS_BY_SLUG = {slug: (eyebrow, title, fn) for slug, eyebrow, title, fn in CHAPTERS}


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("pied_piper_scanned", "fake_s3")
@pytest.mark.parametrize("chapter_slug", list(_CHAPTERS_BY_SLUG))
def walkthrough_chapters(recording_page: Page, chapter_slug: str) -> None:
    """Record one chapter as a standalone clip.

    Produces ``walkthrough_chapters_<slug>.webm`` plus that chapter's hero
    shots. Chapters that do not open on the dashboard themselves get taken
    there first, so each clip stands alone.
    """
    page = recording_page
    _, _, step = _CHAPTERS_BY_SLUG[chapter_slug]

    auto_dismiss_toasts(page)
    if step is not chapter_supply_chain:
        start_on_dashboard(page, pause_ms=600)

    step(page)
    dismiss_toasts(page)
    pace(page, 800)
