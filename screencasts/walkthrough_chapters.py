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
from django.db.models import QuerySet
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from conftest import (
    CUSTOM_TRUST_DOMAIN,
    PIED_PIPER_PRODUCT_NAME,
    auto_dismiss_toasts,
    caption,
    clear_caption,
    click_into_row,
    configure_custom_domain,
    dismiss_toasts,
    enable_trust_center,
    hover_and_click,
    install_dict_backed_s3,
    narrate,
    navigate_to_advisories,
    navigate_to_components,
    navigate_to_products,
    navigate_to_trust_center_tab,
    pace,
    rewrite_localhost_urls,
    shot,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import Component, ProductIdentifier, ProductLink
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryVulnerability,
    SecurityAdvisory,
)

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

# The version the tour presents as shipped. Used for the tagged release and
# echoed by the product identifiers below, so the frame agrees with itself.
PRODUCT_VERSION = "2.4.0"

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

# The advisory the tour publishes and then shows on the public trust centre.
ADVISORY_TITLE = "Path traversal in archive extraction"

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


def _security_result(
    component_name: str,
    scanned_at: datetime,
    finding_count: int | None = None,
    exclude_cve: str | None = None,
) -> dict[str, Any]:
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
    # Dropped before truncation, not after: the VEX target sits second in the
    # core library's list, so truncating alone would keep it.
    if exclude_cve is not None:
        rows = [row for row in rows if row[0] != exclude_cve]
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
    return install_dict_backed_s3(monkeypatch)


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
        title=ADVISORY_TITLE,
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
    # Name the product it affects. Without this the detail page carries an
    # amber "No products recorded yet — publishing a product advisory requires
    # at least one", which is a warning about the demo data sitting in frame
    # for the whole chapter. An advisory that names nothing is also not the
    # thing being sold: the point is that a customer can see whether *their*
    # product is affected.
    AdvisoryProduct.objects.create(
        advisory=advisory,
        product=product,
        product_name=product.name,
    )

    # The vulnerability behind it, with a CVE and a CVSS vector. CVSS hangs off
    # the vulnerability rather than the advisory — an advisory carries zero or
    # more of these — and the detail page renders "CVSS: Not set" without one,
    # which reads as a product that cannot record it rather than demo data that
    # did not.
    AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id="CVE-2026-31337",
        title=ADVISORY_TITLE,
        cwe_ids=["CWE-22"],
        cvss_scores=[
            {
                "version": "3.1",
                "vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:N/A:N",
                "base_score": 6.5,
            }
        ],
    )

    # A disclosure has a history, and the chapter's line calls the timeline
    # "the part auditors care about — who knew what, and when". One PUBLISHED
    # row is not that: it renders as a single event under a heading promising a
    # sequence. These are the beats a real advisory goes through, spread over
    # the fortnight before publication so the dates read as a story rather than
    # a batch insert.
    #
    # `created_at` is auto_now_add, so each row is stamped afterwards; the model
    # orders by it, and without that they would all land on today.
    timeline = [
        (
            13,
            AdvisoryEvent.EventType.COMMENT,
            "Reported by a customer during a penetration test. Reproduced against 2.4.0.",
        ),
        (
            11,
            AdvisoryEvent.EventType.STATUS_CHANGE,
            "Confirmed. Archive entries with parent-directory segments escape the extraction root.",
        ),
        (
            8,
            AdvisoryEvent.EventType.UPDATE,
            "Fix in review: entry paths are normalised and validated before any write.",
        ),
        (
            4,
            AdvisoryEvent.EventType.UPDATE,
            "Fix shipped in 2.4.0. Verified against the original reproduction.",
        ),
        (
            1,
            AdvisoryEvent.EventType.PUBLISHED,
            "Published to the trust centre.",
        ),
    ]
    for days_ago, event_type, body in timeline:
        published = event_type == AdvisoryEvent.EventType.PUBLISHED
        event = AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=event_type,
            body=body,
            payload={"tracking_id": advisory.tracking_id} if published else {},
        )
        # Stamped through a plain queryset, not the model's manager.
        #
        # AdvisoryEvent uses AppendOnlyQuerySet, which refuses `update()` —
        # correctly, because an audit trail nobody can edit is the entire point
        # of the model. A seed seeding *history* is the one legitimate
        # exception, so the guard is stepped around here explicitly rather than
        # relaxed on the model where production writes would lose it too.
        QuerySet(model=AdvisoryEvent).filter(pk=event.pk).update(created_at=now - timedelta(days=days_ago))


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
    # Brand the trust centre in the workspace's own colours.
    #
    # Chapter 4 configures trust.piedpiper.com on camera and says the link
    # "carries your name rather than ours", and the page it then showed was in
    # platform colours throughout. Setting the accent is what the branded
    # component library reads (see the branded-components notes in AGENTS.md),
    # so the nav marker, headings and status chips all pick it up.
    #
    # The wordmark at the top of that page is a separate problem and is NOT
    # fixed here: `BrandingInfo.logo` resolves against
    # AWS_MEDIA_STORAGE_BUCKET_URL, and this recording installs a dict-backed
    # fake S3 that no browser can fetch from, so pointing at one would render a
    # broken image rather than Pied Piper's mark. Showing the platform logo is
    # the lesser wrong until the seed can serve a real asset.
    team.branding_info = {
        **(team.branding_info or {}),
        "branding_enabled": True,
        "brand_color": "#0F2A1D",
        "accent_color": "#1F7A4D",
    }
    team.save(update_fields=["name", "branding_info"])

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

    # Scan the superseded versions too, once each, at the moment they were
    # uploaded.
    #
    # The loop above only touches the newest SBOM per component, so the
    # artifact list showed one scanned row above three reading "Not scanned" —
    # on a page the narration introduces as a version history, in a chapter
    # about keeping every artifact. It read as a product that only looks at the
    # latest, which is the opposite of the claim.
    #
    # An older version legitimately carries *more* findings than its successor:
    # that is what shipping fixes looks like. The count steps down as the
    # series advances, ending one short of the newest, whose full set the loop
    # above already established.
    #
    # These land on their upload dates (194, 96 and 38 days back), well outside
    # the dashboard's 30-day window, so the trends chart is untouched.
    for offset, (component_name, versions) in enumerate(pied_piper_with_sboms["sbom_history"].items()):
        findings = FINDINGS_BY_COMPONENT[component_name]
        superseded = versions[:-1]
        # The VEX target must exist on the newest version only.
        #
        # A VEX statement matches by purl, so if every version carries
        # libwebp@1.2.4 then one statement clears four scan records and the
        # dry-run preview reads "4 would suppress" — against a file that makes
        # a single claim. The honest fix is the data, not the narration: the
        # dependency that introduced it was picked up in the latest release, so
        # the earlier scans legitimately never saw it.
        vex_index = next((i for i, f in enumerate(findings) if f[0] == VEX_TARGET_CVE), None)
        total = len(findings) - (1 if vex_index is not None else 0)
        for index, old_sbom in enumerate(superseded):
            # Oldest carries the most; each release clears one.
            finding_count = max(1, min(total, total + len(superseded) - index - 1))
            scanned_at = old_sbom.created_at + timedelta(hours=2 + offset)
            run = AssessmentRun.objects.create(
                id=uuid.uuid4(),
                sbom=old_sbom,
                plugin_name="osv",
                plugin_version="1.0.0",
                plugin_config_hash="0" * 64,
                category="security",
                run_reason=RunReason.ON_UPLOAD.value,
                status="completed",
                started_at=scanned_at,
                completed_at=scanned_at,
                input_content_digest="0" * 64,
                result=_security_result(component_name, scanned_at, finding_count, exclude_cve=VEX_TARGET_CVE),
                result_schema_version="1.0",
            )
            AssessmentRun.objects.filter(pk=run.pk).update(created_at=scanned_at)

    # A real, tagged release with every artifact pinned to it.
    #
    # The SBOM signal auto-creates a rolling "latest" release, and that used to
    # be the only one here — so chapter 2 opened "latest" while the narration
    # said "not the latest of everything, but precisely what went out of the
    # door in that build". The recording argued against its own script. A
    # tagged release is also the honest artifact for the claim: "latest" is
    # exactly the thing that does not still resolve years later.
    tagged = Release.objects.create(
        product=product,
        name=f"v{PRODUCT_VERSION}",
        version=PRODUCT_VERSION,
    )
    for sbom in pied_piper_with_sboms["sboms"].values():
        ReleaseArtifact.objects.create(release=tagged, sbom=sbom)
    pied_piper_with_sboms["tagged_release"] = tagged

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
    narrate(page, "sc_workspace")
    caption(page, "One workspace holds every product you ship.")
    shot(page, "01-dashboard")
    pace(page, 2200)

    clear_caption(page)
    # Narrate *then* navigate, not the other way round. `narrate` waits for the
    # previous line before it starts, so calling it first ends that line on the
    # page it was describing and lets this one play as the next page paints.
    # With the navigation first, the previous line simply carried over: an
    # audit found twelve beats doing that, the worst by ten seconds.
    narrate(page, "sc_products")
    navigate_to_products(page)
    caption(page, "Products group the components that make up a shippable thing.")
    shot(page, "02-products-list")
    # The line runs 11s over a table with one row in it. Walk the component
    # chips it names — they are the "components that make it real" the sentence
    # is about — so the viewer has something to follow.
    for chip in page.locator("table tbody tr td span, table tbody tr td a").all()[:5]:
        try:
            chip.hover(timeout=2000)
        except PlaywrightError:
            continue
        pace(page, 800)
    pace(page, 1600)

    clear_caption(page)
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    narrate(page, "sc_product_detail")
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
    narrate(page, "inv_component")
    navigate_to_components(page)
    caption(page, "Every component tracks its own SBOMs, VEX, and documents.")
    shot(page, "06-component-inventory")
    pace(page, 2600)

    clear_caption(page)
    narrate(page, "inv_immutable")
    click_into_row(page, CORE_COMPONENT)
    shot(page, "07-component-artifacts")
    pace(page, 1400)

    # Straight through to the full artifact list, *under* the immutability
    # line rather than after it.
    #
    # The component page leads with a card called "Latest artifacts &
    # security" which shows exactly one row, and the four seeded versions this
    # chapter exists to demonstrate live behind its "View all N". Reaching them
    # only when `inv_versions` began left the one-row card on screen for the
    # whole 12.6s of `inv_immutable` — so a chapter titled "every artifact,
    # versioned" spent its first eleven seconds showing a list of one, which is
    # exactly the objection it was meant to answer.
    view_all = page.locator("a:has-text('View all')").first
    view_all.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, view_all)
    page.wait_for_load_state("networkidle")
    caption(page, "Artifacts are stored exactly as received, never rewritten.")
    pace(page, 2400)
    clear_caption(page)

    narrate(page, "inv_versions")
    caption(page, "Every version kept, with the spec it was written against.")
    shot(page, "07b-component-versions")
    # Walk down the four rows while the line counts them. The list was static
    # for the whole 12.5s beat; hovering each version in turn lets the viewer
    # follow the sentence across the table rather than hunt for what is meant.
    rows = page.locator("table tbody tr")
    for index in range(min(rows.count(), 4)):
        rows.nth(index).hover()
        pace(page, 900)
    pace(page, 1200)
    clear_caption(page)

    # The releases list lives on the product, so hop back for the release story.
    narrate(page, "inv_releases")
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

    # Open the *tagged* release so the artifacts pinned to it are on screen —
    # the "what exactly was in that build" answer this chapter is about.
    #
    # Named explicitly rather than taking the first release link. The SBOM
    # signal auto-creates a rolling "latest" release, so `.first` opened that
    # one — while the narration was saying "not the latest of everything, but
    # precisely what went out of the door". The recording contradicted itself.
    #
    # Matched on the href rather than the anchor's classes: the product page
    # also carries hidden download anchors that share font-semibold/text-text,
    # and `.first` on the class selector picks one of those instead.
    release_link = page.locator(f"a[href*='/release/']:has-text('v{PRODUCT_VERSION}')").first
    release_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    narrate(page, "inv_frozen")
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
    narrate(page, "vuln_dashboard")
    caption(page, "The dashboard leads with what actually needs attention.")
    # The line reads out the counts, so put them under the cursor as it does.
    # Ten findings and two critical were being spoken over an unmoving page.
    for chip in ("CRITICAL", "HIGH", "MEDIUM"):
        found = page.locator(f"text={chip}").first
        if found.count():
            found.hover()
            pace(page, 700)
    pace(page, 2600)
    shot(page, "10-vulnerability-posture")

    # The trends widget loads via HTMX after the digest, so wait for the chart
    # itself rather than scrolling blind by a pixel count.
    clear_caption(page)
    # The heading element, not `div:has-text(...)`. `has-text` matches every
    # *ancestor* containing the string, so `.first` resolved to a page-level
    # wrapper taller than the viewport, which can never be scrolled fully into
    # frame — and the recording failed outright once smooth_scroll started
    # asserting instead of failing quietly.
    trends = page.locator("h4:has-text('Vulnerability Trends')").first
    trends.wait_for(state="visible", timeout=15_000)
    narrate(page, "vuln_trends")
    smooth_scroll(page, trends, 1000)
    caption(page, "Severity trends across every product, over time.")
    pace(page, 2400)
    shot(page, "11-vulnerability-trends")
    clear_caption(page)
    # No scroll back up here.
    #
    # There used to be a `page.mouse.wheel(0, -1400)`, which fired while
    # vuln_trends was still speaking and yanked the chart out of frame in the
    # middle of the line describing it. It was also an instant jump rather than
    # a pan. It bought nothing either way: the next step navigates to a new
    # page, which starts at the top regardless.
    pace(page, 800)

    narrate(page, "vuln_drill")
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
    narrate(page, "vuln_not_exploitable")
    caption(page, "Not every finding is exploitable. VEX says so, in a standard format.")
    # Point at the row the line is about. It names the critical finding in the
    # compression core, and the table was simply sitting there while it did —
    # 9.4s of speech over a still frame. Panning to the libwebp row makes the
    # words and the picture the same statement.
    # Walk the table, then land on the one the line is about. This beat is 17s
    # and the modal used to fill its tail; now that the upload has moved under
    # its own line, the picture here has to be the findings themselves.
    rows = page.locator("table tbody tr")
    for index in range(min(rows.count(), 4)):
        rows.nth(index).hover()
        pace(page, 900)
    target_row = page.locator(f"tr:has-text('{VEX_TARGET_CVE}')").first
    target_row.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, target_row, 1100)
    target_row.hover()
    pace(page, 1400)
    # Then read across the row itself: the package, the version that fixes it,
    # and the state it is in. The line spends its second half explaining why
    # this particular finding is not reachable, and the table was motionless
    # for ten seconds of that.
    for cell in target_row.locator("td").all()[1:5]:
        try:
            cell.hover(timeout=2000)
        except PlaywrightError:
            continue
        pace(page, 900)
    pace(page, 1400)
    clear_caption(page)

    # Everything from here to the dropzone happens under `vuln_upload`, the
    # line that is actually about uploading.
    #
    # It used to run under `vuln_not_exploitable` instead, filling that beat's
    # leftover twelve seconds — so the upload modal slid over the vulnerability
    # table while the voice was still describing the libwebp row underneath it,
    # advertising "Drop your SBOM file here" a good ten seconds before the line
    # first says the word VEX.
    narrate(page, "vuln_upload")

    # Role-based lookups, matching the convention the other recordings settled
    # on. The meatball is one c-actions-menu now and its label names the thing
    # it acts on, so a component page answers to "Component actions" and a
    # product page to "Product actions" — the old shared "More actions" is gone.
    menu_btn = page.get_by_role("button", name="Component actions")
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

    caption(page, "Drop in a CycloneDX VEX, and sbomify shows what it would change first.")
    # The line spends eleven seconds on formats and open standards while the
    # modal holds still. The dropzone spells out every accepted format, so pan
    # to it and let the viewer read along instead of being talked at.
    # Hover only, no pan. `smooth_scroll` falls back to a whole-page scroll
    # when the target has no scrollable ancestor, and the dropzone lives inside
    # a fixed modal — so panning to it slid the page *behind* the dialog while
    # the dialog itself stayed put. The modal is fully in frame already.
    dropzone = page.locator("#upload-sbom .border-dashed, #upload-sbom [class*='dashed']").first
    if dropzone.count():
        dropzone.hover()
    pace(page, 2600)
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

    narrate(page, "vuln_dry_run")
    caption(page, "A dry run: one finding would be suppressed, nothing stored yet.")
    pace(page, 3000)
    shot(page, "13-vex-preview")
    clear_caption(page)

    # The claim "nothing has been written yet" has to finish while that is still
    # true. This used to be one 22.6s beat and the click landed ~4s into it, so
    # the sentence was spoken about eight seconds after the write. `narrate`
    # waits for the previous line to finish, so starting the rationale here is
    # what holds the click until the preview copy has landed.
    narrate(page, "vuln_dry_run_why")

    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=25_000,
    ):
        hover_and_click(page, apply_btn)

    pace(page, 1500)
    page.reload()
    page.wait_for_load_state("networkidle")
    pace(page, 1800)

    # Land back on the vulnerabilities table. The finding stays on the list and
    # changes state rather than disappearing: upstream reverted the hide-by-
    # default, because hiding cleared findings made an applied VEX look like it
    # had done nothing. So there is no "N suppressed hidden" footer to wait for
    # any more — the row itself, now reading Not affected, is the evidence.
    vulns_card = page.locator("text=Vulnerabilities").first
    vulns_card.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, vulns_card, 1200)

    suppressed = page.locator("td:has-text('Not affected')").first
    suppressed.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, suppressed, 800)

    narrate(page, "vuln_applied")
    caption(page, "The finding changes state rather than vanishing — now not affected.")
    pace(page, 3000)
    shot(page, "14-vex-applied")
    clear_caption(page)

    suppressed.hover()
    pace(page, 1400)

    narrate(page, "vuln_nothing_deleted")
    caption(page, "Nothing is deleted, the finding is still there with the reason attached.")
    # The claim is that the cleared finding sits *next to* the others, so show
    # that rather than describing it: hover the not-affected row, then pan back
    # across the untouched ones.
    cleared = page.locator("tr:has-text('Not affected')").first
    if cleared.count():
        cleared.hover()
        pace(page, 1400)
    others = page.locator("tr:has-text('Affected')").first
    if others.count():
        smooth_scroll(page, others, 900)
        others.hover()
        pace(page, 1400)
    pace(page, 2400)
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
    narrate(page, "tc_enable")
    navigate_to_trust_center_tab(page)
    pace(page, 600)
    caption(page, "Turn on a public trust center — no separate site to build.")
    pace(page, 2400)
    clear_caption(page)

    enable_trust_center(page)

    # The domain is typed and saved *under* the line about domains, not before
    # it. Running both halves up front meant the viewer watched the hostname
    # being entered while hearing about switching the trust centre on, and then
    # heard "serve it from your own domain" over a form that had been filled in
    # and saved several seconds earlier.
    narrate(page, "tc_domain")
    configure_custom_domain(page)
    rewrite_localhost_urls(page)
    caption(page, "Serve it from your own domain: trust.piedpiper.com.")
    shot(page, "16-trust-center-config")
    pace(page, 2000)
    clear_caption(page)

    # Publish the product. Nothing reaches the trust center until you say so —
    # showing the switch being thrown makes that explicit, and it is what fills
    # the public page the chapter closes on.
    narrate(page, "tc_visibility")
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
    narrate(page, "tc_customer_view")
    page.goto("/public/workspace/")
    page.wait_for_load_state("networkidle")
    # The workspace's own hostname, not ours: chapter 4 configures
    # trust.piedpiper.com on camera, so showing this page on app.sbomify.com
    # contradicted the line about the link carrying your name.
    rewrite_localhost_urls(page, CUSTOM_TRUST_DOMAIN)
    pace(page, 2000)
    caption(page, "This is what your customers see — always current, no email thread.")
    shot(page, "17-trust-center-public")
    pace(page, 3200)
    clear_caption(page)
    pace(page, 1200)


# ---------------------------------------------------------------------------
# Chapter 5 — security advisories, in the app and on the trust centre
# ---------------------------------------------------------------------------


def chapter_advisories(page: Page) -> None:
    """The advisory a customer receives, from the workspace to the public page.

    Runs last because the second half needs the trust centre public, which
    chapter 4 turns on. The first four chapters cover what you ship and what is
    wrong with it; this is the disclosure that reaches the customer, which is
    the part teams currently do over email.

    Both halves are shown deliberately: the workspace view is where the
    advisory is written and its state tracked, and the public view is the only
    half a customer ever sees. Showing one without the other was the gap.
    """
    # adv_why gets the walk back into the app as its picture. It used to be
    # followed immediately by adv_list, with no visual work at all between the
    # two calls, so it played for seven seconds against a frozen frame — the
    # worst single case the slack report found.
    narrate(page, "adv_why")
    # Open on the public advisories section, which is what chapter 4 left on
    # screen and exactly what this line is about. Best-effort on purpose: the
    # long cut arrives here from /public/workspace where the section exists,
    # while the standalone clip opens on the dashboard where it does not, and
    # neither is a failure. Everything this beat *needs* is the navigation
    # below; this only stops it opening on a frozen frame.
    public_advisories = page.locator("h2:has-text('Security advisories')").first
    if public_advisories.count():
        try:
            smooth_scroll(page, public_advisories, 900)
            pace(page, 1200)
        except (PlaywrightError, AssertionError):
            pass
    # Back into the app first. In the long cut chapter 4 signs off on
    # ``/public/workspace/``, which carries its own "Security Advisories"
    # section heading — so the sidebar lookup below matched *that* link, never
    # left the public page, and the workspace table's title span never
    # appeared. The standalone clip opens on the dashboard and so never hit it.
    start_on_dashboard(page, pause_ms=1200)
    navigate_to_advisories(page)
    pace(page, 1600)

    narrate(page, "adv_list")
    caption(page, "Sooner or later you are the one disclosing.")
    pace(page, 1600)
    clear_caption(page)

    advisories_table = page.locator(f"span:text-is('{ADVISORY_TITLE}')").first
    advisories_table.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, advisories_table, 900)
    shot(page, "18-advisories-list")
    # One row, seventeen seconds. Read across it — severity, then the CVE, then
    # the product it affects, then its state — which is the order the line
    # describes them in.
    for cell in ("text=MEDIUM", f"text={ADVISORY_TITLE}", "text=Pied Piper Compression Engine", "text=Resolved"):
        found = page.locator(cell).first
        if found.count():
            try:
                found.hover(timeout=2000)
            except PlaywrightError:
                continue
            pace(page, 900)
    pace(page, 1200)

    # Aim at the title cell rather than the row: the row's own @click is
    # swallowed by the actions cell, and the advisories table grew a row menu.
    narrate(page, "adv_detail")
    hover_and_click(page, advisories_table)
    page.wait_for_url("**/security-advisories/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 1600)

    caption(page, "Severity, affected products, and a timeline an auditor can read.")
    timeline = page.locator("text=Timeline").first
    timeline.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, timeline, 1000)
    shot(page, "19-advisory-detail")
    # Walk the details panel the line lists: status, severity, the score, the
    # identifier, then the product it affects. Fifteen seconds of this page
    # used to pass with nothing moving.
    for field in ("text=Resolved", "text=CVSS", "text=CVE-2026-31337", "text=Pied Piper Compression Engine"):
        found = page.locator(field).first
        if found.count():
            try:
                found.hover(timeout=2000)
            except PlaywrightError:
                continue
            pace(page, 900)
    pace(page, 1400)
    clear_caption(page)

    narrate(page, "adv_publish")
    caption(page, "Nothing reaches a customer until you publish it.")
    pace(page, 2600)
    clear_caption(page)

    # The public half. Same page the tour closed chapter 4 on, now read for the
    # advisory rather than the SBOMs.
    narrate(page, "adv_public")
    page.goto("/public/workspace/")
    page.wait_for_load_state("networkidle")
    # The workspace's own hostname, not ours: chapter 4 configures
    # trust.piedpiper.com on camera, so showing this page on app.sbomify.com
    # contradicted the line about the link carrying your name.
    rewrite_localhost_urls(page, CUSTOM_TRUST_DOMAIN)
    pace(page, 1400)

    public_advisory = page.locator(f"text={ADVISORY_TITLE}").first
    public_advisory.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, public_advisory, 1000)
    caption(page, "Published, on the page your customers already have a link to.")
    shot(page, "20-advisory-public")
    pace(page, 3400)
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
    ("advisories", "Chapter 5", "Tell them what you found", chapter_advisories),
]

_CHAPTERS_BY_SLUG = {slug: (eyebrow, title, fn) for slug, eyebrow, title, fn in CHAPTERS}


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("fake_s3")
@pytest.mark.parametrize("chapter_slug", list(_CHAPTERS_BY_SLUG))
def walkthrough_chapters(recording_page: Page, chapter_slug: str, pied_piper_scanned: dict) -> None:
    """Record one chapter as a standalone clip.

    Produces ``walkthrough_chapters_<slug>.webm`` plus that chapter's hero
    shots. Chapters that do not open on the dashboard themselves get taken
    there first, so each clip stands alone.
    """
    page = recording_page
    _, _, step = _CHAPTERS_BY_SLUG[chapter_slug]

    # In the long cut, chapter 4 turns the trust centre on before chapter 5
    # reads the public page. On its own, chapter 5 would land on a workspace
    # that was never made public and find no advisory there. Set it off camera
    # rather than performing it, so the clip does not re-stage chapter 4's
    # story before telling its own.
    if step is chapter_advisories:
        product = pied_piper_scanned["product"]
        team = product.team
        team.is_public = True
        team.save(update_fields=["is_public"])
        # The product too, or the public page carries a "No public products"
        # empty state under the advisory for the whole closing shot.
        product.is_public = True
        product.save(update_fields=["is_public"])

    auto_dismiss_toasts(page)

    # chapter_supply_chain and chapter_vulnerabilities open on the dashboard
    # themselves; the other two assume they are already inside the app.
    if step not in (chapter_supply_chain, chapter_vulnerabilities):
        start_on_dashboard(page)

    step(page)
    dismiss_toasts(page)
    pace(page, 1200)
