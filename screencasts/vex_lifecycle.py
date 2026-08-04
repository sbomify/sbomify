"""Record the VEX lifecycle screencast — generate → upload → suppress → publish,
including VEX versioning (a re-issued VEX supersedes the previous one).

Drives the full producer-to-consumer journey for hand-authored CycloneDX VEX:

1. **The vulnerability.** Open the component. Its scan flagged a critical, a high
   and a medium.
2. **VEX v1.** Show the CycloneDX VEX (version 1) that marks the critical
   ``not_affected``, upload it, and watch the critical drop from the component's
   severity counts. The public Trust Center shows one finding suppressed.
3. **VEX v2 (versioning).** Show a re-issued VEX (version 2) that also clears the
   high. sbomify applies a component's newest VEX, so uploading v2 supersedes v1:
   the high now drops too and the Trust Center shows two findings suppressed, with
   the newer VEX downloadable.

Two infrastructure notes:

1. **S3 short-circuit.** The screencast compose stack runs no S3 service, so a
   real upload would fail at ``put_object``. We back S3 with an in-memory dict:
   ``upload_data_as_file`` stores the bytes and ``get_file_data`` returns them.
   Both halves are needed. No-oping only the put would let the upload succeed
   while ``build_release_vex`` got nothing back from ``get_sbom_data``, so the
   Trust Center's "Download latest VEX" link would 404 on camera.
2. **Re-annotation runs the real engine, fed directly.** In production, uploading
   a VEX enqueues a job that reads the VEX from S3 and re-annotates the stored
   scan. With no S3 the job cannot fetch the bytes, so ``_apply_vex`` runs the
   same engine functions (``derive_vex_suppressions`` + ``reapply_vex_to_stored_result``)
   on the in-memory VEX document. The suppression and rebuilt counts are the real
   engine's output — only the S3 round-trip is skipped.
"""

import html as html_lib
import json

import pytest
from django.urls import reverse
from playwright.sync_api import Page

from conftest import (
    click_into_row,
    hover_and_click,
    navigate_to_components,
    pace,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.core.object_store import S3Client
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
    component = Component.objects.create(team=deletable_team, name=COMPONENT_NAME)

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

    def _put(self: S3Client, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: S3Client, bucket_name: str, file_path: str) -> bytes | None:
        return store.get((bucket_name, file_path))

    monkeypatch.setattr(S3Client, "upload_data_as_file", _put)
    monkeypatch.setattr(S3Client, "get_file_data", _get)


def _apply_vex(component: Component, release: Release, run: AssessmentRun, document: dict) -> None:
    """Suppress via the real VEX engine, then pin the uploaded VEX to the release.

    Runs ``derive_vex_suppressions`` + ``reapply_vex_to_stored_result`` on the
    in-memory VEX document — the same functions the async job runs after reading
    the VEX from S3 — so the annotated findings and rebuilt counts are the
    engine's genuine output. ``reapply`` is a full recompute, so applying v2's
    statements supersedes v1. Then attaches the component's newest VEX (the one
    just uploaded through the UI) to the release so it's downloadable.
    """
    from sbomify.apps.vulnerability_scanning.vex import (
        derive_vex_suppressions,
        reapply_vex_to_stored_result,
    )

    statements = derive_vex_suppressions(document)
    run.result = reapply_vex_to_stored_result(run.result, statements)
    run.save(update_fields=["result"])

    vex = SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX).order_by("-created_at").first()
    if vex is not None:
        ReleaseArtifact.objects.get_or_create(release=release, sbom=vex)


def _show_vex_file(page: Page, document: dict, subtitle: str, pause_ms: int = 5000) -> None:
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
    """Upload a VEX through the header's ⋮ menu modal, via the dry-run preview.

    The upload surface lives in a modal behind the component header's
    meatball menu now, with a real artifact-type select; a VEX file gets a
    dry-run preview before anything is stored, and applying it is what
    persists — both worth having on camera.
    """
    more_actions = page.get_by_role("button", name="More actions")
    more_actions.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, more_actions)
    pace(page, 600)
    hover_and_click(page, page.get_by_role("menuitem", name="Upload artifact"))
    pace(page, 1000)

    type_select = page.locator("#upload-bom-type")
    type_select.wait_for(state="visible", timeout=10_000)
    type_select.select_option("vex")
    pace(page, 1000)

    file_input = page.locator("#upload-sbom input[type='file']")
    with page.expect_response(lambda r: "/vex-preview" in r.url and r.status == 200, timeout=15_000):
        file_input.set_input_files(
            files=[{"name": VEX_FILENAME, "mimeType": "application/json", "buffer": _vex_bytes(document)}]
        )
    page.locator("text=Preview — nothing stored yet").first.wait_for(state="visible", timeout=10_000)
    pace(page, 2500)

    apply_btn = page.locator("button:has-text('Apply this VEX')")
    with page.expect_response(
        lambda r: "/api/v1/sboms/upload-file/" in r.url and r.status == 201,
        timeout=15_000,
    ):
        hover_and_click(page, apply_btn)
    pace(page, 1500)


def _show_component_posture(page: Page, component_url: str, struck_cves: list[str], hold_ms: int = 4000) -> None:
    """Land on the component's vulnerabilities table and show the VEX effect.

    The table strikes a suppressed finding's severity badge through, so the
    proof on camera is each cleared CVE's row rendering with line-through.
    """
    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    anchor = page.locator(f"tr:has-text('{CRITICAL_CVE}')").first
    anchor.wait_for(state="visible", timeout=15_000)
    pace(page, 1500)
    smooth_scroll(page, anchor, 1500)
    for cve in struck_cves:
        struck = page.locator(f"tr:has-text('{cve}') .line-through").first
        struck.wait_for(state="visible", timeout=10_000)
    pace(page, hold_ms)


def _show_trust_center(page: Page, public_url: str, show_download: bool) -> None:
    """Land on the public Trust Center release page and reveal the VEX-applied posture."""
    page.goto(public_url)
    page.wait_for_load_state("networkidle")

    posture_heading = page.locator("h4:has-text('Vulnerability Posture')")
    posture_heading.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, posture_heading, 2000)

    suppression_note = page.locator("text=suppressed by VEX").first
    suppression_note.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, suppression_note, 3000)

    if show_download:
        vex_download = page.locator("a[title='Download latest VEX (CycloneDX)']").first
        vex_download.wait_for(state="visible", timeout=10_000)
        smooth_scroll(page, vex_download, 1200)
        vex_download.hover()
        pace(page, 2500)


@pytest.mark.django_db(transaction=True)
def vex_lifecycle(recording_page: Page, vex_release: dict, s3_short_circuit: None) -> None:
    page = recording_page

    component = vex_release["component"]
    release = vex_release["release"]
    run = vex_release["run"]
    product = vex_release["product"]
    component_url = reverse("core:component_details", kwargs={"component_id": component.id})
    public_url = reverse(
        "core:release_details_public",
        kwargs={"product_id": product.id, "release_id": release.id},
    )

    start_on_dashboard(page)

    # ── 1. The vulnerability — the component's scan flagged a critical ───
    navigate_to_components(page)
    click_into_row(page, COMPONENT_NAME)
    critical_row = page.locator(f"tr:has-text('{CRITICAL_CVE}')").first
    critical_row.wait_for(state="visible", timeout=15_000)
    pace(page, 1500)
    smooth_scroll(page, critical_row, 4000)

    # ── 2. VEX v1 — show the file, upload it, watch the critical clear ───
    _show_vex_file(page, VEX_V1, "CycloneDX VEX · version 1 — clears the critical", 5500)

    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    pace(page, 800)
    _upload_vex(page, VEX_V1)

    _apply_vex(component, release, run, VEX_V1)
    _show_component_posture(page, component_url, [CRITICAL_CVE])  # critical struck through
    _show_trust_center(page, public_url, show_download=False)  # 1 finding suppressed

    # ── 3. VEX v2 — re-issue a newer version that also clears the high ───
    _show_vex_file(page, VEX_V2, "CycloneDX VEX · version 2 — re-issued, also clears the high", 5500)

    page.goto(component_url)
    page.wait_for_load_state("networkidle")
    pace(page, 800)
    _upload_vex(page, VEX_V2)

    _apply_vex(component, release, run, VEX_V2)
    _show_component_posture(page, component_url, [CRITICAL_CVE, HIGH_CVE])  # both struck through
    _show_trust_center(page, public_url, show_download=True)  # 2 findings suppressed
