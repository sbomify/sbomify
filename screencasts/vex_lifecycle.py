"""Record the VEX lifecycle screencast: scan, VEX v1, VEX v2, Trust Center.

1. **The vulnerability.** Open the component. Its scan flagged a critical, a high
   and a medium.
2. **VEX v1.** Show the CycloneDX VEX (version 1) that marks the critical
   ``not_affected``, upload it through Upload VEX with its dry-run preview, and
   watch the critical leave the component's open vulnerabilities. The public
   Trust Center release page shows one suppressed by VEX.
3. **VEX v2 (versioning).** Show a re-issued VEX (version 2) that also clears the
   high. sbomify applies a component's newest VEX, so v2 supersedes v1: the high
   leaves too, the Trust Center shows two suppressed and offers the VEX download.

Infrastructure notes:

1. **S3 in a dict.** The screencast stack runs no S3 service, so
   ``upload_data_as_file`` stores bytes in memory and ``get_file_data`` returns
   them. Both halves matter: re-annotation and the Trust Center VEX download read
   the uploaded document back.
2. **Re-annotation runs the real engine, synchronously.** In production the upload
   enqueues a worker job; here ``reannotate_component_runs`` (the function that job
   calls) runs right after the upload, reading the VEX through the dict-backed S3.
   The seeded scan's finding rows are projected with ``sync_findings`` so the
   component page lists them, as a completed scan would.
"""

import html as html_lib
import json

import pytest
from django.urls import reverse
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    caption,
    clear_caption,
    hover_and_click,
    navigate_to_components,
    pace,
    rewrite_localhost_urls,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM, Component, Product
from sbomify.apps.teams.models import Team

COMPONENT_NAME = "Compression Core Library"
PRODUCT_NAME = "Pied Piper Compression Engine"
SBOM_NAME = "com.piedpiper/compression-core"
VEX_FILENAME = "compression-core-2.1.0.vex.cdx.json"

CRITICAL_CVE = "CVE-2024-12345"
HIGH_CVE = "CVE-2024-45210"

# Raw scan findings for the release's SBOM before any VEX: one critical, one
# high, one medium. Shapes mirror what a security scanner stores.
RAW_FINDINGS = [
    {
        "id": CRITICAL_CVE,
        "severity": "critical",
        "title": "Server-side request forgery in requests",
        "component": {"name": "requests", "version": "2.32.3", "purl": "pkg:pypi/requests@2.32.3"},
    },
    {
        "id": HIGH_CVE,
        "severity": "high",
        "title": "Improper certificate validation in urllib3",
        "component": {"name": "urllib3", "version": "2.0.7", "purl": "pkg:pypi/urllib3@2.0.7"},
    },
    {
        "id": "CVE-2024-33210",
        "severity": "medium",
        "title": "Prototype pollution in lodash",
        "component": {"name": "lodash", "version": "4.17.20", "purl": "pkg:npm/lodash@4.17.20"},
    },
]


def _vex_document(version: int, vulnerabilities: list[dict]) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:11111111-2222-3333-4444-555555555555",
        "version": version,
        "metadata": {
            "timestamp": "2026-04-29T00:00:00Z",
            "component": {"type": "application", "name": SBOM_NAME, "version": "2.1.0"},
        },
        "vulnerabilities": vulnerabilities,
    }


_CRITICAL_STATEMENT = {
    "id": CRITICAL_CVE,
    "source": {"name": "NVD"},
    "ratings": [{"severity": "critical"}],
    "affects": [{"ref": "pkg:pypi/requests@2.32.3"}],
    "analysis": {
        "state": "not_affected",
        "justification": "code_not_reachable",
        "detail": (
            "requests is only used for outbound HTTPS to a fixed allowlist; "
            "the vulnerable redirect path is never exercised."
        ),
    },
}
_HIGH_STATEMENT = {
    "id": HIGH_CVE,
    "source": {"name": "NVD"},
    "ratings": [{"severity": "high"}],
    "affects": [{"ref": "pkg:pypi/urllib3@2.0.7"}],
    "analysis": {
        "state": "not_affected",
        "justification": "protected_by_mitigating_control",
        "detail": (
            "TLS verification is pinned and enforced at the gateway, so the weak certificate path cannot be reached."
        ),
    },
}

# v1 clears the critical; v2 is re-issued (version 2) and also clears the high.
VEX_V1 = _vex_document(1, [_CRITICAL_STATEMENT])
VEX_V2 = _vex_document(2, [_CRITICAL_STATEMENT, _HIGH_STATEMENT])


def _vex_bytes(document: dict) -> bytes:
    return json.dumps(document, indent=2).encode("utf-8")


@pytest.fixture
def vex_release(deletable_team: Team) -> dict:
    """Seed a public release whose scanned SBOM has an unmitigated critical."""
    component = Component.objects.create(
        team=deletable_team, name=COMPONENT_NAME, visibility=Component.Visibility.PUBLIC
    )

    sbom = SBOM.objects.create(
        name=SBOM_NAME,
        version="2.1.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="compression-core-2.1.0.cdx.json",
        source="api",
        bom_type=SBOM.BomType.SBOM,
        component=component,
    )

    product = Product.objects.create(
        team=deletable_team,
        name=PRODUCT_NAME,
        description="Middle-out compression platform for enterprise data optimization",
        is_public=True,
    )
    product.components.set([component])

    release = Release.objects.create(product=product, name="v2.1.0", version="2.1.0")
    ReleaseArtifact.objects.create(release=release, sbom=sbom)

    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result={
            "findings": [dict(f) for f in RAW_FINDINGS],
            "summary": {
                "by_severity": {"critical": 1, "high": 1, "medium": 1, "low": 0},
                "total_findings": 3,
                "suppressed_count": 0,
            },
        },
    )

    # The scan's finding rows, as scan completion projects them.
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    sync_findings(run, fresh=True)

    # The Trust Center is on and publishes vulnerability posture, so the public
    # release page shows the VEX-applied counts.
    deletable_team.is_public = True
    deletable_team.publish_vulnerability_posture = True
    deletable_team.save(update_fields=["is_public", "publish_vulnerability_posture"])

    return {"component": component, "release": release, "run": run, "product": product}


@pytest.fixture
def s3_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Back S3 with a dict so uploads AND downloads work without a bucket.

    No-oping only the put is not enough: ``build_release_vex`` reads each VEX
    back through ``get_sbom_data``, so the Trust Center's "Download latest VEX"
    link would 404 and the recording would show a broken button. Every read path
    funnels through ``get_file_data``, so patching that one method alongside the
    put covers SBOMs, VEX and documents.
    """
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: StorageClient, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: StorageClient, bucket_name: str, file_path: str) -> bytes | None:
        return store.get((bucket_name, file_path))

    monkeypatch.setattr(StorageClient, "upload_data_as_file", _put)
    monkeypatch.setattr(StorageClient, "get_file_data", _get)


def _apply_vex(component: Component, release: Release) -> None:
    """Run the re-annotation the upload enqueues, then pin the newest VEX to the release.

    ``reannotate_component_runs`` is what the worker job calls after a VEX upload:
    it resolves the component's newest VEX (read back through the dict-backed S3),
    re-annotates the stored scan and re-projects its finding rows. ``reapply`` is
    a full recompute, so v2's statements supersede v1's.
    """
    from sbomify.apps.vulnerability_scanning.vex import reannotate_component_runs

    vex = SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX).order_by("-created_at").first()
    if vex is not None:
        ReleaseArtifact.objects.get_or_create(release=release, sbom=vex)
    reannotate_component_runs(component.id)


def _show_vex_file(page: Page, document: dict, subtitle: str, pause_ms: int = 600) -> None:
    """Render the CycloneDX VEX document full-screen so viewers see its contents.

    The in-app VEX Documents card lists uploads but does not render their
    contents, so the file is drawn directly via ``set_content`` as a styled
    code view, with the decision-carrying lines highlighted.
    """
    escaped = html_lib.escape(json.dumps(document, indent=2))
    for needle in (
        "&quot;state&quot;: &quot;not_affected&quot;",
        "&quot;justification&quot;: &quot;code_not_reachable&quot;",
        "&quot;justification&quot;: &quot;protected_by_mitigating_control&quot;",
        f"&quot;id&quot;: &quot;{CRITICAL_CVE}&quot;",
        f"&quot;id&quot;: &quot;{HIGH_CVE}&quot;",
    ):
        escaped = escaped.replace(needle, f'<span class="hl">{needle}</span>')
    for version in ("1", "2"):
        escaped = escaped.replace(
            f"&quot;version&quot;: {version},", f'<span class="hlv">&quot;version&quot;: {version}</span>,'
        )

    content = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; min-height: 100vh; background: #0A0A23;
             display: flex; align-items: center; justify-content: center;
             font-family: ui-monospace, "SF Mono", Menlo, monospace; }}
      .win {{ width: 780px; max-width: 92vw; background: #14142e;
             border: 1px solid #2b2b52; border-radius: 12px; overflow: hidden;
             box-shadow: 0 24px 60px rgba(0,0,0,.5); }}
      .bar {{ display: flex; align-items: center; gap: 10px; padding: 12px 16px;
             background: #1c1c3d; border-bottom: 1px solid #2b2b52; }}
      .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
      .r {{ background: #ff5f57; }} .y {{ background: #febc2e; }} .g {{ background: #28c840; }}
      .fname {{ margin-left: 8px; color: #e6e6f0; font-size: 14px; font-weight: 600; }}
      .badge {{ margin-left: auto; color: #a5b4fc; background: #312e81; font-size: 12px;
               padding: 4px 10px; border-radius: 999px; }}
      pre {{ margin: 0; padding: 20px 22px; color: #c8c8e0; font-size: 14px; line-height: 1.6;
            max-height: 70vh; overflow: auto; }}
      .hl {{ color: #fbbf24; font-weight: 700; }}
      .hlv {{ color: #34d399; font-weight: 700; }}
    </style></head><body>
      <div class="win">
        <div class="bar">
          <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
          <span class="fname">{html_lib.escape(VEX_FILENAME)}</span>
          <span class="badge">{html_lib.escape(subtitle)}</span>
        </div>
        <pre>{escaped}</pre>
      </div>
    </body></html>"""
    page.set_content(content, wait_until="load")
    pace(page, pause_ms)


def _upload_vex(page: Page, document: dict) -> None:
    """Upload a VEX from the component's actions menu, through the dry-run preview."""
    actions = page.get_by_role("button", name="Component actions")
    actions.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, actions)
    pace(page, 300)
    hover_and_click(page, page.get_by_role("menuitem", name="Upload VEX"))

    file_input = page.locator("#upload-sbom input[type='file']")
    file_input.wait_for(state="attached", timeout=10_000)
    pace(page, 500)
    with page.expect_response(lambda r: "/vex-preview" in r.url and r.status == 200, timeout=15_000):
        file_input.set_input_files(
            files=[{"name": VEX_FILENAME, "mimeType": "application/json", "buffer": _vex_bytes(document)}]
        )
    page.get_by_text("Preview: nothing stored yet").first.wait_for(state="visible", timeout=10_000)


def _apply_upload(page: Page) -> None:
    apply_btn = page.get_by_role("button", name="Apply this VEX")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=15_000,
    ):
        hover_and_click(page, apply_btn)
    pace(page, 800)


def _open_vulnerabilities(page: Page, component_url: str) -> None:
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    heading = page.locator("main").get_by_text("Vulnerabilities", exact=True).first
    heading.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, heading, 400)


def _show_trust_center(page: Page, public_url: str) -> None:
    page.goto(public_url)
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    posture = page.get_by_text("suppressed by VEX").first
    posture.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, posture, 400)


@pytest.mark.django_db(transaction=True)
def vex_lifecycle(recording_page: Page, vex_release: dict, s3_short_circuit: None) -> None:
    page = recording_page
    auto_dismiss_toasts(page)

    component = vex_release["component"]
    release = vex_release["release"]
    product = vex_release["product"]
    component_url = reverse("core:component_details", kwargs={"component_id": component.id})
    public_url = reverse(
        "core:release_details_public",
        kwargs={"product_id": product.id, "release_id": release.id},
    )

    start_on_dashboard(page, pause_ms=600)
    caption(
        page,
        "Here is the VEX lifecycle in sbomify: from a scan finding to a statement your customers can see.",
        block=False,
    )

    # ── 1. The vulnerability ──────────────────────────────────────────────
    navigate_to_components(page)
    link = page.locator("main").get_by_role("link", name=COMPONENT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    critical_row = page.locator(f"tr:has-text('{CRITICAL_CVE}')").first
    critical_row.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, critical_row, 400)
    caption(page, "The latest scan of this component found a critical, a high and a medium vulnerability.")
    caption(page, "Your team checks the critical and finds the vulnerable code is never reached.")

    # ── 2. VEX v1 ─────────────────────────────────────────────────────────
    clear_caption(page)
    _show_vex_file(page, VEX_V1, "CycloneDX VEX, version 1")
    caption(page, "So you write a VEX statement: this CVE is not affected, because the code is not reachable.")

    clear_caption(page)
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    caption(page, "Upload it from the component's actions menu, with Upload VEX.", block=False)
    _upload_vex(page, VEX_V1)
    caption(page, "Before anything is stored, a preview shows what the VEX would suppress.")
    clear_caption(page)
    _apply_upload(page)
    _apply_vex(component, release)

    _open_vulnerabilities(page, component_url)
    page.locator(f"tr:has-text('{HIGH_CVE}')").first.wait_for(state="visible", timeout=15_000)
    caption(page, "Once applied, the critical leaves the open list. Only the high and the medium remain.")

    clear_caption(page)
    _show_trust_center(page, public_url)
    caption(page, "Your Trust Center shows the same thing. One vulnerability is suppressed by VEX.")

    # ── 3. VEX v2 ─────────────────────────────────────────────────────────
    clear_caption(page)
    _show_vex_file(page, VEX_V2, "CycloneDX VEX, version 2")
    caption(
        page,
        "Later you re-issue the VEX as version 2. It keeps the first statement and also clears the high.",
        block=False,
    )
    pace(page, 1800)
    page.locator("pre").evaluate("el => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })")
    pace(page, 1500)

    clear_caption(page)
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    _upload_vex(page, VEX_V2)
    caption(page, "Upload it the same way. The preview now counts two.")
    clear_caption(page)
    _apply_upload(page)
    _apply_vex(component, release)

    _open_vulnerabilities(page, component_url)
    page.locator(f"tr:has-text('{HIGH_CVE}')").first.wait_for(state="hidden", timeout=15_000)
    caption(page, "sbomify always applies the newest VEX, so version 2 replaces version 1. Only the medium is left.")

    clear_caption(page)
    _show_trust_center(page, public_url)
    download = page.locator("a[title='Download latest VEX (CycloneDX)']").first
    download.wait_for(state="visible", timeout=10_000)
    caption(
        page, "On the Trust Center, two are now suppressed, and customers can download the latest VEX.", block=False
    )
    smooth_scroll(page, download, 300)
    download.hover()
    pace(page, 800)
