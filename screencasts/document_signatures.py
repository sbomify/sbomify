"""Record the document-signature screencast.

Pairs with the ``how-do-i-use-signature-files`` FAQ on sbomify.com.

Drives: a terminal card with the two API calls a release pipeline makes
(attach a cosign signature bundle, attach a SLSA provenance attestation) →
those calls really run against the API → Components → the component → its
1.0.0 version → the SBOM page with the Signed and Provenance badges and the
SBOM Verification assessment passing.

The two uploads go through the real ``/api/v1/sboms/sbom/<id>/signature`` and
``/provenance`` endpoints in-process, with the S3 writes stubbed (the stack runs
no object store) and the verification enqueue stubbed. The verification result
is seeded through the ORM: running the real plugin would need the SBOM bytes and
a real Sigstore bundle from object storage, which this stack does not have. The
seeded run carries the same findings a passing run produces.
"""

import base64
import html as html_lib
import json
import uuid
from datetime import datetime, timezone

import pytest
from django.test import Client
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    caption,
    clear_caption,
    hover_and_click,
    pace,
    setup_authenticated_client_session,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.plugins.builtins.verification import SBOMVerificationPlugin
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason

# The first component in ``PIED_PIPER_COMPONENTS`` — the natural lead
# in the recording's narrative because the badges read most clearly on
# a "library" component (a thing you would actually sign and ship).
SIGNED_COMPONENT_NAME = "Compression Core Library"


def _verification_result(plugin_name: str, plugin_version: str) -> dict:
    """Build the AssessmentResult JSON for a passing sbom-verification run.

    The card reads ``run.result["summary"]`` to compute its overall
    status, so the dict matches the schema produced by the real
    plugin (see ``sbomify/apps/plugins/sdk/results.py``). All five
    canonical findings are reported as ``pass``; the rolled-up
    ``verification:attestation`` summary finding is included so
    BSI / FDA / NTIA's ``requires_one_of: attestation`` clause
    finds a satisfying signal.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    findings = [
        {
            "id": fid,
            "title": title,
            "description": desc,
            "severity": "info",
            "status": "pass",
        }
        for fid, title, desc in (
            (
                "verification:digest:integrity",
                "SBOM digest integrity",
                "Recomputed SHA-256 matches the stored hash.",
            ),
            (
                "verification:signature:present",
                "Signature attached",
                "A detached signature is stored alongside the SBOM.",
            ),
            (
                "verification:signature:valid",
                "Signature verified",
                "The stored cosign-bundle signature verifies against the SBOM bytes.",
            ),
            (
                "verification:provenance:present",
                "Provenance attached",
                "A SLSA provenance attestation is stored alongside the SBOM.",
            ),
            (
                "verification:provenance:digest",
                "Provenance digest match",
                "The provenance subject digest matches the SBOM hash.",
            ),
            (
                "verification:attestation",
                "Attestation summary",
                "At least one cryptographic source verified for this SBOM.",
            ),
        )
    ]
    return {
        "schema_version": "1.0",
        "plugin_name": plugin_name,
        "plugin_version": plugin_version,
        "category": "attestation",
        "assessed_at": now,
        "summary": {
            "total_findings": len(findings),
            "pass_count": len(findings),
            "fail_count": 0,
            "warning_count": 0,
            "error_count": 0,
        },
        "findings": findings,
    }


SBOM_SHA256 = "9f2c4e7a1b3d5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8"


@pytest.fixture
def signing_setup(pied_piper_with_sboms: dict, mocker) -> dict:
    """Give the SBOM a hash to sign, stub the S3 writes and the verification enqueue."""
    sbom = pied_piper_with_sboms["sboms"][SIGNED_COMPONENT_NAME]
    sbom.sha256_hash = SBOM_SHA256
    sbom.save(update_fields=["sha256_hash"])

    mocker.patch(
        "sbomify.apps.sboms.apis.StorageClient.upload_sbom_signature",
        side_effect=lambda self_id, digest, data: f"signatures/{digest}.sig",
        autospec=False,
    )
    mocker.patch(
        "sbomify.apps.sboms.apis.StorageClient.upload_sbom_provenance",
        side_effect=lambda self_id, digest, data: f"provenance/{digest}.intoto.jsonl",
        autospec=False,
    )
    mocker.patch("sbomify.apps.sboms.apis._trigger_verification")
    return pied_piper_with_sboms


def _seed_verification_run(sbom) -> None:
    """The passing sbom-verification run the upload would trigger."""
    plugin_name = "sbom-verification"
    plugin_version = SBOMVerificationPlugin.VERSION
    now = datetime.now(tz=timezone.utc)
    AssessmentRun.objects.create(
        id=uuid.uuid4(),
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version=plugin_version,
        plugin_config_hash="0" * 64,
        category="attestation",
        run_reason=RunReason.ON_UPLOAD.value,
        status="completed",
        started_at=now,
        completed_at=now,
        input_content_digest="0" * 64,
        result=_verification_result(plugin_name, plugin_version),
        result_schema_version="1.0",
    )


def _terminal(page: Page, lines: list[str]) -> None:
    """Draw a terminal window holding the pipeline's commands."""
    body = "\n".join(html_lib.escape(line) for line in lines)
    page.set_content(
        f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ margin: 0; min-height: 100vh; background: #0A0A23; display: flex;
             align-items: center; justify-content: center;
             font-family: ui-monospace, "SF Mono", Menlo, monospace; }}
      .win {{ width: 1180px; background: #14142e; border: 1px solid #2b2b52;
             border-radius: 12px; overflow: hidden; box-shadow: 0 24px 60px rgba(0,0,0,.5); }}
      .bar {{ display: flex; gap: 8px; padding: 12px 16px; background: #1c1c3d;
             border-bottom: 1px solid #2b2b52; color: #e6e6f0; font-size: 14px; align-items: center; }}
      .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
      pre {{ margin: 0; padding: 22px 24px; color: #c8c8e0; font-size: 17px; line-height: 1.6;
            white-space: pre-wrap; min-height: 420px; }}
    </style></head><body><div class="win">
      <div class="bar"><span class="dot" style="background:#ff5f57"></span>
        <span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
        <span style="margin-left:8px">release pipeline</span></div>
      <pre id="term">{body}</pre>
    </div></body></html>""",
        wait_until="load",
    )


def _append(page: Page, line: str) -> None:
    page.evaluate("(line) => { document.getElementById('term').textContent += '\\n' + line; }", line)


@pytest.mark.django_db(transaction=True)
def document_signatures(recording_page: Page, signing_setup: dict, sample_user, deletable_team) -> None:
    page = recording_page
    auto_dismiss_toasts(page)
    sbom = signing_setup["sboms"][SIGNED_COMPONENT_NAME]
    api = Client()
    setup_authenticated_client_session(api, deletable_team, sample_user)

    start_on_dashboard(page, pause_ms=600)
    caption(
        page,
        "Here is how to attach a signature and build provenance to an SBOM, so anyone can check it is genuine.",
        block=False,
    )
    pace(page, 1500)
    clear_caption(page)

    # ── 1. The pipeline's two calls ──────────────────────────────────────
    base = f"https://app.sbomify.com/api/v1/sboms/sbom/{sbom.id}"
    _terminal(
        page,
        [
            "$ cosign sign-blob --bundle sbom.cdx.json.bundle sbom.cdx.json",
            "",
            f"$ curl -X POST {base}/signature \\",
            '    -H "Authorization: Bearer $SBOMIFY_TOKEN" \\',
            '    -H "X-Signature-Type: cosign-bundle" \\',
            "    --data-binary @sbom.cdx.json.bundle",
        ],
    )
    caption(page, "After uploading the SBOM, your pipeline signs it, for example with cosign.")
    caption(page, "Then it posts the signature bundle to the SBOM's signature endpoint.", block=False)
    response = api.post(
        f"/api/v1/sboms/sbom/{sbom.id}/signature",
        data=b"cosign-bundle-bytes",
        content_type="application/octet-stream",
        HTTP_X_SIGNATURE_TYPE="cosign-bundle",
    )
    assert response.status_code == 201, response.content
    pace(page, 1200)
    _append(page, '{"detail": "Signature uploaded"}')
    pace(page, 600)

    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "sbom.cdx.json", "digest": {"sha256": SBOM_SHA256}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {"buildDefinition": {"buildType": "https://example.com/pied-piper/build"}},
    }
    envelope = {
        "payloadType": "application/vnd.in-toto+json",
        "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
        "signatures": [],
    }
    _append(page, "")
    _append(page, f"$ curl -X POST {base}/provenance \\")
    _append(page, '    -H "Authorization: Bearer $SBOMIFY_TOKEN" \\')
    _append(page, "    --data-binary @provenance.intoto.jsonl")
    caption(
        page,
        "A SLSA provenance attestation goes to the provenance endpoint. Its subject must match the SBOM's hash.",
        block=False,
    )
    pace(page, 2500)
    response = api.post(
        f"/api/v1/sboms/sbom/{sbom.id}/provenance",
        data=json.dumps(envelope),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    _append(page, '{"detail": "Provenance uploaded"}')
    _seed_verification_run(sbom)
    pace(page, 1500)

    # ── 2. The SBOM in the app ───────────────────────────────────────────
    clear_caption(page)
    page.goto("/components/")
    page.wait_for_load_state("networkidle")
    link = page.locator("main").get_by_role("link", name=SIGNED_COMPONENT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    caption(page, "In sbomify, open the component, then the version you signed.", block=False)
    hover_and_click(page, link)
    page.wait_for_load_state("networkidle")
    version_link = page.locator("main").get_by_role("link", name="1.0.0").first
    version_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    hover_and_click(page, version_link)
    page.wait_for_load_state("networkidle")

    signed = page.locator("main").get_by_text("Signed", exact=True).first
    signed.wait_for(state="visible", timeout=15_000)
    provenance = page.locator("main").get_by_text("Provenance", exact=True).first
    signed.hover()
    caption(page, "The SBOM now carries a Signed badge and a Provenance badge.", block=False)
    pace(page, 1500)
    provenance.hover()
    pace(page, 800)

    passed = page.locator("main").get_by_text("All passed").first
    passed.wait_for(state="visible", timeout=20_000)
    smooth_scroll(page, passed, 300)
    passed.hover()
    caption(page, "The SBOM Verification assessment checks them, and every check passed.", block=False)
    show_met = page.get_by_role("button", name="Show 6 met requirements")
    pace(page, 1500)
    hover_and_click(page, show_met)
    pace(page, 600)
    caption(page, "Open the met requirements to see each one: the digest, the signature and the provenance.")
    pace(page, 800)
