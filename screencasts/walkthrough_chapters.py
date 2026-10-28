"""Marketplace walkthrough — chapter steps, seed data, and per-chapter clips.

This module is the source of truth for the marketplace walkthrough. It holds:

* the Pied Piper seed (:func:`pied_piper_scanned`) — a workspace that already
  looks *lived in*, because an empty product tour sells nothing;
* one ``chapter_*`` function per act of the story (SBOMs in, vulnerabilities
  triaged with VEX, CRA compliance, Trust Center and security advisories out),
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

What the tour does perform, through the real UI, is the moments that carry the
pitch: the VEX upload in :func:`chapter_vulnerabilities` (dry-run preview and
all, exercising the genuine parse and match path, see :func:`fake_s3`),
completing the CRA assessment in :func:`chapter_compliance`, and turning on the
Trust Center and flipping the product public in :func:`chapter_trust_center`.
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
from sbomify.apps.compliance.models import CRAAssessment, CRAScopeScreening, OSCALFinding
from sbomify.apps.compliance.services.document_generation_service import regenerate_all
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import AssessmentRun, TeamPluginSettings
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import Component, ProductIdentifier, ProductLink
from sbomify.apps.security_advisories.models import AdvisoryEvent, AdvisoryProduct, SecurityAdvisory
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact
from sbomify.apps.vulnerability_scanning.findings import sync_findings
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

# The hand-authored CycloneDX VEX the tour uploads. Its subject version matches
# the seeded SBOM's (1.0.0): a VEX applies to the SBOM version it names. ``affects[].ref`` points at
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
                "bom-ref": "pkg:github/piedpiper/compression-core@1.0.0",
                "name": "com.piedpiper/compression-core",
                "version": "1.0.0",
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
    """Back :class:`StorageClient` with an in-process dict instead of a bucket.

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
    return pied_piper_with_sboms


# ---------------------------------------------------------------------------
# Shared steps
# ---------------------------------------------------------------------------


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
    settle(page)
    shot(page, "01-dashboard")

    narrate(page, "supply_chain_products_group_components")
    _nav(page, "Products")
    settle(page)
    shot(page, "02-products-list")

    narrate(page, "supply_chain_pied_piper_s")
    _open_product(page)
    settle(page)
    shot(page, "03-product-overview")

    narrate(page, "supply_chain_cpe_purl_sku")
    _product_detail_tab(page, "Identifiers", "#product-identifiers-card")
    settle(page)
    shot(page, "04-product-identifiers")

    narrate(page, "supply_chain_lifecycle_dates_set")
    _product_detail_tab(page, "Lifecycle", "#product-lifecycle-card")
    settle(page)
    shot(page, "05-product-lifecycle")


# ---------------------------------------------------------------------------
# Chapter 2 — every artifact, versioned
# ---------------------------------------------------------------------------


def chapter_inventory(page: Page) -> None:
    """Components → a component's versions → the release that ships them."""
    narrate(page, "inventory_intro")
    _nav(page, "Components")
    settle(page)
    shot(page, "06-component-inventory")

    narrate(page, "inventory_artifacts_stored_exactly")
    link = page.get_by_role("link", name=CORE_COMPONENT, exact=True).first
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    settle(page)
    shot(page, "07-component-artifacts")

    narrate(page, "inventory_releases_pin_exact")
    _open_product(page)
    releases = page.get_by_role("heading", name="Releases", exact=True)
    smooth_scroll(page, releases, 500)
    settle(page)
    shot(page, "08-releases")

    release_link = page.locator("a[href*='/release/']").first
    release_link.wait_for(state="visible", timeout=15_000)
    narrate(page, "inventory_years_later_release")
    hover_and_click(page, release_link)
    page.wait_for_load_state("networkidle")
    settle(page)
    shot(page, "09-release-artifacts")


# ---------------------------------------------------------------------------
# Chapter 3 — vulnerabilities, triaged with VEX
# ---------------------------------------------------------------------------


def chapter_vulnerabilities(page: Page) -> None:
    """Workspace vulnerabilities → trends → a component → clear one with VEX.

    The chapter closes on the VEX payoff: the critical libwebp row leaves the
    open list, and is still there, with its reason, under "Closed by a
    decision" (ADR-004: nothing is deleted).
    """
    narrate(page, "vulnerabilities_intro")
    _nav(page, "Vulnerabilities")
    settle(page)
    shot(page, "10-vulnerability-posture")

    narrate(page, "vulnerabilities_trends_show_exposure")
    _nav(page, "Overview")
    trends = page.get_by_role("link", name="Trends", exact=True)
    hover_and_click(page, trends)
    page.wait_for_load_state("networkidle")
    settle(page)
    shot(page, "11-vulnerability-trends")

    narrate(page, "vulnerabilities_component_each_vulnerability")
    _open_core_component(page)
    vulns = page.get_by_role("button", name="Vulnerabilities", exact=True).first
    smooth_scroll(page, vulns, 500)
    settle(page)
    shot(page, "12-vulnerability-drilldown")

    # ── The VEX upload, through the real UI ───────────────────────────────
    narrate(page, "vulnerabilities_not_every_vulnerability")
    hover_and_click(page, page.get_by_role("button", name="Component actions"))
    pace(page, 500)
    upload_vex = page.get_by_text("Upload VEX…", exact=True)
    upload_vex.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, upload_vex)
    page.locator("#upload-sbom").wait_for(state="visible", timeout=10_000)
    pace(page, 800)

    file_input = page.locator("#upload-sbom input[type='file']")
    with page.expect_response(lambda r: "/vex-preview" in r.url, timeout=25_000):
        file_input.set_input_files(
            files=[
                {
                    "name": "compression-core-1.0.0.vex.cdx.json",
                    "mimeType": "application/json",
                    "buffer": VEX_DOCUMENT_BYTES,
                }
            ]
        )

    apply_btn = page.get_by_role("button", name="Apply this VEX")
    apply_btn.wait_for(state="visible", timeout=20_000)
    smooth_scroll(page, apply_btn, 400)
    narrate(page, "vulnerabilities_sbomify_shows_dry")
    settle(page)
    shot(page, "13-vex-preview")

    narrate(page, "vulnerabilities_applied_drops_out")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=25_000,
    ):
        hover_and_click(page, apply_btn)
    # The upload enqueues the re-apply job that annotates the stored scans.
    # The screencast stack runs no worker, so run that same job here.
    reapply_vex_to_component_scans.fn(Component.objects.get(name=CORE_COMPONENT).id)
    pace(page, 600)
    page.reload()
    page.wait_for_load_state("networkidle")

    suppressed_badge = page.get_by_text("1 suppressed").first
    suppressed_badge.wait_for(state="visible", timeout=15_000)
    table = page.locator("#component-vulnerabilities-status")
    smooth_scroll(page, table, 500)
    settle(page)
    shot(page, "14-vex-suppressed-hidden")

    narrate(page, "vulnerabilities_nothing_deleted_vulnerability")
    hover_and_click(page, table)
    table.select_option("decided")
    page.wait_for_load_state("networkidle")
    suppressed = page.get_by_text("Not affected").first
    suppressed.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, suppressed, 400)
    suppressed.hover()
    settle(page)
    shot(page, "15-vex-suppression")


# ---------------------------------------------------------------------------
# Chapter 4 — CRA compliance
# ---------------------------------------------------------------------------


def chapter_compliance(page: Page) -> None:
    """Compliance list → the assessment's review step → mark it complete."""
    narrate(page, "compliance_intro")
    _nav(page, "Compliance")
    settle(page)
    shot(page, "18-cra-assessments")

    narrate(page, "compliance_scope_screening_sbom")
    hover_and_click(page, page.get_by_role("link", name="Continue").first)
    page.wait_for_url("**/step/5/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    settle(page)
    shot(page, "19-cra-summary")

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


def chapter_trust_center(page: Page) -> None:
    """Advisories → turn on the Trust Center → publish → the public page."""
    narrate(page, "trust_center_intro")
    _nav(page, "Security advisories")
    settle(page)
    shot(page, "20-security-advisories")

    narrate(page, "trust_center_turn_trust_center")
    navigate_to_trust_center_tab(page)
    enable_and_configure_trust_center(page)
    rewrite_localhost_urls(page)
    rewrite_localhost_inputs(page)
    narrate(page, "trust_center_serve_own_domain")
    settle(page)
    shot(page, "16-trust-center-config")

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
    settle(page)
    shot(page, "17-trust-center-public")
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
    ("vulnerabilities", "Chapter 3", "Triage vulnerabilities with VEX", chapter_vulnerabilities),
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
