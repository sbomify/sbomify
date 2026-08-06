"""Marketplace walkthrough — chapter steps, seed data, and per-chapter clips.

This module is the source of truth for the marketplace walkthrough. It holds:

* the Pied Piper seed (:func:`pied_piper_scanned`) — a workspace that already
  looks *lived in*, because an empty product tour sells nothing;
* one ``chapter_*`` function per act of the story, each self-contained enough
  to open on the dashboard and close on a stable frame;
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

What the tour does perform, through the real UI, is the two moments that carry
the pitch: the VEX upload in :func:`chapter_vulnerabilities` — dry-run preview
and all, exercising the genuine parse and match path (see :func:`fake_s3`) —
and flipping the product public in :func:`chapter_trust_center`.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    auto_dismiss_toasts,
    caption,
    clear_caption,
    click_into_row,
    dismiss_toasts,
    enable_and_configure_trust_center,
    hover_and_click,
    navigate_to_components,
    navigate_to_products,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_urls,
    shot,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import Component, ProductIdentifier, ProductLink
from sbomify.apps.security_advisories.models import AdvisoryEvent, SecurityAdvisory

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

# The hand-authored CycloneDX VEX the tour uploads. ``affects[].ref`` points at
# the purl declared in ``components[]``, which is the package-scoped form
# ``derive_vex_suppressions`` matches on — so the statement clears exactly the
# one libwebp finding and leaves the other three core-library rows alone.
VEX_DOCUMENT_BYTES = json.dumps(
    {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:9f2c1d4e-6b3a-4f18-9c07-2e5d8a1b6f30",
        "version": 1,
        "metadata": {
            "timestamp": "2026-02-24T09:15:00Z",
            "component": {
                "type": "application",
                "bom-ref": "pkg:github/piedpiper/compression-core@2.4.0",
                "name": "com.piedpiper/compression-core",
                "version": "2.4.0",
            },
        },
        "components": [
            {
                "type": "library",
                "bom-ref": VEX_TARGET_PURL,
                "name": VEX_TARGET_PACKAGE,
                "version": VEX_TARGET_VERSION,
                "purl": VEX_TARGET_PURL,
            }
        ],
        "vulnerabilities": [
            {
                "id": VEX_TARGET_CVE,
                "source": {"name": "NVD", "url": f"https://nvd.nist.gov/vuln/detail/{VEX_TARGET_CVE}"},
                "ratings": [{"severity": "critical", "score": 8.8, "method": "CVSSv31"}],
                "affects": [{"ref": VEX_TARGET_PURL}],
                "analysis": {
                    "state": "not_affected",
                    "justification": "code_not_reachable",
                    "detail": VEX_JUSTIFICATION_DETAIL,
                },
            }
        ],
    },
    indent=2,
).encode("utf-8")


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
    """Back :class:`S3Client` with an in-process dict instead of a bucket.

    The screencast compose stack runs no S3 service. The other recordings
    work around that by no-op'ing the *write* (``vex_upload.py``), which is
    enough to make an upload return 201 — but the bytes are gone, so nothing
    that reads them back can work. This tour needs the round trip: the VEX it
    uploads has to be re-read, parsed, and matched against the seeded findings
    for the suppression to appear on screen.

    Storing the payload in a dict keyed by ``(bucket, object)`` gives us that
    round trip while leaving every layer above the object store — the upload
    endpoint, ``derive_vex_suppressions``, ``find_matching_statement`` — running
    for real. What you see suppressed on screen was genuinely suppressed by the
    matcher, not staged.
    """
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: S3Client, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: S3Client, bucket_name: str, object_name: str) -> bytes | None:
        return store.get((bucket_name, object_name))

    monkeypatch.setattr(S3Client, "upload_data_as_file", _put)
    monkeypatch.setattr(S3Client, "get_file_data", _get)
    return store


def _seed_published_advisory(team: Any) -> None:
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
    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.PUBLISHED,
        payload={"tracking_id": advisory.tracking_id},
    )


@pytest.fixture
def pied_piper_scanned(
    sample_user: AbstractBaseUser,
    pied_piper_with_sboms: dict,
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
       what lights up the dashboard digest and the component drill-down.

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

    _seed_published_advisory(team)

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

    return pied_piper_with_sboms


# ---------------------------------------------------------------------------
# Chapter 1 — the product hierarchy
# ---------------------------------------------------------------------------


def _expand_product_panel(page: Page, header: str, card_selector: str, text: str, shot_name: str) -> None:
    """Expand one of the product-record accordions and hold on its card.

    The panels on the product page render collapsed with an
    ``hx-trigger="click once from:previous button"`` body, so the card only
    exists in the DOM after its header is clicked. Waiting on the card without
    clicking first times out — which is exactly what a naive selector does here.
    """
    toggle = page.locator(f"button:has-text('{header}')").first
    toggle.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, toggle, 600)
    hover_and_click(page, toggle)

    card = page.locator(card_selector)
    card.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, card, 800)

    caption(page, text)
    pace(page, 2600)
    shot(page, shot_name)
    clear_caption(page)


def chapter_supply_chain(page: Page) -> None:
    """Dashboard → Products → the product's full record.

    Establishes the mental model the rest of the tour builds on: a workspace
    holds products, a product holds components, and every product carries the
    identifiers, links, and lifecycle dates a downstream consumer asks for.
    """
    start_on_dashboard(page)
    caption(page, "One workspace holds every product you ship.")
    shot(page, "01-dashboard")
    pace(page, 2200)

    clear_caption(page)
    navigate_to_products(page)
    caption(page, "Products group the components that make up a shippable thing.")
    shot(page, "02-products-list")
    pace(page, 2400)

    clear_caption(page)
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1600)

    caption(page, "Pied Piper's compression engine — four components under one product.")
    shot(page, "03-product-overview")
    pace(page, 2600)

    # The product-record accordions: identifiers, links, and lifecycle dates.
    # This is the metadata that makes a product record answer a procurement
    # questionnaire, and the part a marketplace viewer is least likely to guess
    # at. Each panel lazily HTMX-loads its card on the first header click, so
    # the expand is both the interaction and the fetch.
    clear_caption(page)
    _expand_product_panel(
        page,
        "Product identifiers",
        "#product-identifiers-card",
        "CPE, PURL and SKU identifiers, so scanners can match your product.",
        "04-product-identifiers",
    )
    _expand_product_panel(
        page,
        "Lifecycle",
        "#product-lifecycle-card",
        "Lifecycle dates — release, end of support, end of life.",
        "05-product-lifecycle",
    )

    page.mouse.wheel(0, -3000)
    pace(page, 1000)


# ---------------------------------------------------------------------------
# Chapter 2 — artifacts and releases
# ---------------------------------------------------------------------------


def chapter_inventory(page: Page) -> None:
    """Components → a component's artifacts → the release that ships them.

    The point of this chapter is that sbomify stores artifacts *immutably* and
    organises them by release, so "what was in build 2.4.0" has an answer
    years later.
    """
    navigate_to_components(page)
    caption(page, "Every component tracks its own SBOMs, VEX, and documents.")
    shot(page, "06-component-inventory")
    pace(page, 2600)

    clear_caption(page)
    click_into_row(page, CORE_COMPONENT)

    caption(page, "Artifacts are stored exactly as received — never rewritten.")
    shot(page, "07-component-artifacts")
    pace(page, 2800)
    clear_caption(page)

    # The releases list lives on the product, so hop back for the release story.
    navigate_to_products(page)
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 400)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1400)

    # "Latest releases" is a card on the product page; creating a release now
    # lives behind the header meatball, so the card — not a Create button — is
    # what the tour holds on.
    releases_card = page.locator("h4:has-text('Latest releases')")
    releases_card.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, releases_card, 1200)

    caption(page, "Releases pin an exact set of artifacts to a version you shipped.")
    shot(page, "08-releases")
    pace(page, 2800)
    clear_caption(page)

    # Open the release itself so the artifacts pinned to it are on screen —
    # the "what exactly was in that build" answer this chapter is about.
    # Matched on the href rather than the anchor's classes: the product page
    # also carries hidden download anchors that share font-semibold/text-text,
    # and `.first` on the class selector picks one of those instead.
    release_link = page.locator("a[href*='/release/']").first
    release_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    hover_and_click(page, release_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1800)

    caption(page, "Every artifact in that build, frozen — years later it still resolves.")
    shot(page, "09-release-artifacts")
    pace(page, 3000)
    clear_caption(page)


# ---------------------------------------------------------------------------
# Chapter 3 — vulnerabilities and VEX
# ---------------------------------------------------------------------------


def chapter_vulnerabilities(page: Page) -> None:
    """Dashboard posture → per-component findings → clear a false positive.

    The chapter closes on the VEX payoff: the critical libwebp row is still
    listed (ADR-004 — nothing is deleted) but reads "Not affected · VEX" and
    drops out of the counts that page your on-call.
    """
    start_on_dashboard(page)
    caption(page, "The dashboard leads with what actually needs attention.")
    pace(page, 2600)
    shot(page, "10-vulnerability-posture")

    # The trends widget loads via HTMX after the digest; give it a beat and
    # capture the whole page so the chart lands in the still.
    clear_caption(page)
    page.mouse.wheel(0, 700)
    pace(page, 2000)
    caption(page, "Severity trends across every product, over time.")
    pace(page, 2400)
    shot(page, "11-vulnerability-trends")
    clear_caption(page)
    page.mouse.wheel(0, -1400)
    pace(page, 800)

    navigate_to_components(page)
    click_into_row(page, CORE_COMPONENT)

    vulns_card = page.locator("text=Vulnerabilities").first
    vulns_card.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, vulns_card, 1400)

    caption(page, "Drill into a component: advisory, package, fix version, status.")
    shot(page, "12-vulnerability-drilldown")
    pace(page, 3000)
    clear_caption(page)

    # ── The VEX upload ────────────────────────────────────────────────────
    # This is the one flow the tour performs rather than seeds, and it runs
    # entirely through the real UI: the ⋮ menu, the artifact-type select, the
    # dropzone, the dry-run preview, and Apply. Nothing is stubbed above the
    # object store (see the fake_s3 fixture), so the "would suppress: 1" the
    # preview reports is the matcher's own answer.
    caption(page, "Not every finding is exploitable. VEX says so, in a standard format.")
    pace(page, 2600)
    clear_caption(page)

    # Role-based lookups, matching the convention the other recordings settled
    # on: the meatball's contents move around, but its accessible names don't.
    menu_btn = page.get_by_role("button", name="More actions")
    menu_btn.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, menu_btn, 700)
    hover_and_click(page, menu_btn)
    pace(page, 800)

    upload_item = page.get_by_role("menuitem", name="Upload artifact")
    upload_item.wait_for(state="visible", timeout=10_000)
    pace(page, 400)
    hover_and_click(page, upload_item)

    upload_modal = page.locator("#upload-sbom")
    upload_modal.wait_for(state="visible", timeout=10_000)
    pace(page, 1200)

    # Switch the artifact type to VEX. The endpoint keys off this select, so
    # this is a genuine UI choice rather than a query parameter we injected.
    bom_type = page.locator("#upload-bom-type")
    bom_type.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, bom_type)
    pace(page, 400)
    bom_type.select_option("vex")
    pace(page, 1200)

    caption(page, "Drop in a CycloneDX VEX — sbomify shows what it would change first.")
    pace(page, 1800)
    clear_caption(page)

    # The dropzone proxies to a hidden <input type="file"> via $refs; setting
    # files on it directly runs the same @change handler a real drop would.
    file_input = page.locator("#upload-sbom input[type='file']")
    with page.expect_response(
        lambda r: "/vex-preview" in r.url,
        timeout=25_000,
    ):
        file_input.set_input_files(
            files=[
                {
                    "name": "compression-core-2.4.0.vex.cdx.json",
                    "mimeType": "application/json",
                    "buffer": VEX_DOCUMENT_BYTES,
                }
            ]
        )

    # ── The dry-run preview ───────────────────────────────────────────────
    apply_btn = page.locator("button:has-text('Apply this VEX')")
    apply_btn.wait_for(state="visible", timeout=20_000)
    smooth_scroll(page, apply_btn, 1400)

    caption(page, "A dry run: one finding would be suppressed, nothing stored yet.")
    pace(page, 3000)
    shot(page, "13-vex-preview")
    clear_caption(page)

    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=25_000,
    ):
        hover_and_click(page, apply_btn)

    pace(page, 1500)
    page.reload()
    page.wait_for_load_state("networkidle")
    pace(page, 1800)

    # Land back on the vulnerabilities table. The suppressed row is now gone
    # from the default view — the working list matches the open counts — and
    # the footer accounts for it rather than silently dropping it.
    vulns_card = page.locator("text=Vulnerabilities").first
    vulns_card.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, vulns_card, 1200)

    hidden_note = page.locator("text=suppressed hidden").first
    hidden_note.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, hidden_note, 800)

    caption(page, "It drops straight out of your working list — and the count says so.")
    pace(page, 3000)
    shot(page, "14-vex-suppressed-hidden")
    clear_caption(page)

    # Reveal it again: nothing was deleted, and the decision is auditable.
    show_suppressed = page.get_by_text("Show suppressed").first
    show_suppressed.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, show_suppressed, 700)
    hover_and_click(page, show_suppressed)
    pace(page, 1400)

    suppressed = page.locator("td:has-text('Not affected')").first
    suppressed.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, suppressed, 800)
    suppressed.hover()

    caption(page, "Nothing is deleted — the finding is still there, with the reason attached.")
    pace(page, 3200)
    shot(page, "15-vex-suppression")
    clear_caption(page)


# ---------------------------------------------------------------------------
# Chapter 4 — the trust center
# ---------------------------------------------------------------------------


def chapter_trust_center(page: Page) -> None:
    """Settings → enable the trust center → the public page customers see.

    Closes the loop the whole tour has been building toward: the inventory and
    the posture are only worth maintaining if you can hand them to a customer
    without a spreadsheet and an NDA thread.
    """
    navigate_to_trust_center_tab(page)
    pace(page, 600)

    caption(page, "Turn on a public trust center — no separate site to build.")
    pace(page, 2400)
    clear_caption(page)

    enable_and_configure_trust_center(page)
    rewrite_localhost_urls(page)

    caption(page, "Serve it from your own domain: trust.piedpiper.com.")
    shot(page, "16-trust-center-config")
    pace(page, 2800)
    clear_caption(page)

    # Publish the product. Nothing reaches the trust center until you say so —
    # showing the switch being thrown makes that explicit, and it is what fills
    # the public page the chapter closes on.
    navigate_to_products(page)
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 400)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1400)

    caption(page, "You decide what goes public — per product, per component.")
    pace(page, 2200)
    clear_caption(page)

    visibility = page.locator("select[aria-label='Product visibility']")
    visibility.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, visibility, 700)
    hover_and_click(page, visibility)
    pace(page, 400)
    visibility.select_option("true")
    page.wait_for_load_state("networkidle")
    dismiss_toasts(page)
    pace(page, 1800)

    # The public page is what a customer or auditor actually lands on, so the
    # tour ends there rather than on an admin screen.
    page.goto("/public/workspace/")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 2000)

    caption(page, "This is what your customers see — always current, no email thread.")
    shot(page, "17-trust-center-public")
    pace(page, 3200)
    clear_caption(page)
    pace(page, 1200)


# ---------------------------------------------------------------------------
# Per-chapter clips
# ---------------------------------------------------------------------------

# Each entry is (slug, eyebrow, title, step function). ``marketplace_walkthrough``
# imports this to play the same chapters as one continuous tour.
CHAPTERS: list[tuple[str, str, str, Callable[[Page], None]]] = [
    ("supply_chain", "Chapter 1", "Know what you ship", chapter_supply_chain),
    ("inventory", "Chapter 2", "Every artifact, versioned", chapter_inventory),
    ("vulnerabilities", "Chapter 3", "Know what's exploitable", chapter_vulnerabilities),
    ("trust_center", "Chapter 4", "Share it with customers", chapter_trust_center),
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

    # chapter_supply_chain and chapter_vulnerabilities open on the dashboard
    # themselves; the other two assume they are already inside the app.
    if step not in (chapter_supply_chain, chapter_vulnerabilities):
        start_on_dashboard(page)

    step(page)
    dismiss_toasts(page)
    pace(page, 1200)
