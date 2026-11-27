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
comes from the plugin itself (see ``_verification_result``), with only its
Sigstore and storage reads stood in for, because this stack has no object store
and no Sigstore bundle. The card and the Signed chip both read that run.
"""

import base64
import hashlib
import html as html_lib
import json
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import Client
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    hover_and_click,
    narrate,
    pace,
    settle,
    setup_authenticated_client_session,
    smooth_scroll,
    start_on_dashboard,
)
from sbomify.apps.plugins.builtins.verification import SBOMVerificationPlugin
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.plugins.sdk.enums import RunReason

# The first component in ``PIED_PIPER_COMPONENTS`` — the natural lead
# in the recording's narrative because the badges read most clearly on
# a "library" component (a thing you would actually sign and ship).
SIGNED_COMPONENT_NAME = "Compression Core Library"


def _verification_result() -> dict:
    """Build the result a real sbom-verification run gives a signed SBOM.

    The findings come from the plugin itself, so their ids, titles and count
    are the ones the app shows, not a copy that drifts. Only the two network
    checks are stood in for: the Sigstore verification reports the keyless
    GitHub Actions signer a release workflow would have, and the stored
    provenance is a DSSE envelope whose subject is the SBOM digest. The
    SBOM carries no repository link, so the GitHub attestation lookup is
    the informational "no VCS" note rather than a network call.
    """
    plugin = SBOMVerificationPlugin()
    sbom_bytes = b"{}"
    digest = hashlib.sha256(sbom_bytes).hexdigest()
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "sbom.cdx.json", "digest": {"sha256": digest}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {},
    }
    envelope = {
        "payloadType": "application/vnd.in-toto+json",
        "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
        "signatures": [],
    }
    signed = plugin._signature_verified(
        {
            "identity": "https://github.com/piedpiper/compression-core/.github/workflows/release.yml@refs/tags/v1.0.0",
            "issuer": "https://token.actions.githubusercontent.com",
        },
        "sigstore",
    )
    context = SBOMContext(
        sha256_hash=digest,
        signature_blob_key="signature",
        signature_type="cosign-bundle",
        provenance_blob_key="provenance",
    )
    with tempfile.TemporaryDirectory() as workdir:
        sbom_path = Path(workdir) / "sbom.json"
        sbom_path.write_bytes(sbom_bytes)
        with (
            patch.object(plugin, "_check_signature_valid", return_value=signed),
            patch.object(plugin, "_fetch_blob", return_value=json.dumps(envelope).encode()),
        ):
            return plugin.assess("screencast", sbom_path, context=context).to_dict()


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
    result = _verification_result()
    now = datetime.now(tz=timezone.utc)
    AssessmentRun.objects.create(
        id=uuid.uuid4(),
        sbom=sbom,
        plugin_name=result["plugin_name"],
        plugin_version=result["plugin_version"],
        plugin_config_hash="0" * 64,
        category="attestation",
        run_reason=RunReason.ON_UPLOAD.value,
        status="completed",
        started_at=now,
        completed_at=now,
        input_content_digest="0" * 64,
        result=result,
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

    # The opening line plays over the dashboard loading.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=600)
    pace(page, 1500)

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
    narrate(page, "after_uploading_sbom")
    settle(page)
    narrate(page, "posts_signature_bundle")
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
    narrate(page, "slsa_provenance_attestation")
    pace(page, 2500)
    response = api.post(
        f"/api/v1/sboms/sbom/{sbom.id}/provenance",
        data=json.dumps(envelope),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    _append(page, '{"detail": "Provenance uploaded"}')
    _seed_verification_run(sbom)
    # Stay on the pipeline until the provenance line has been said.
    settle(page)

    # ── 2. The SBOM in the app ───────────────────────────────────────────
    page.goto("/components/")
    page.wait_for_load_state("networkidle")
    link = page.locator("main").get_by_role("link", name=SIGNED_COMPONENT_NAME, exact=True).first
    link.wait_for(state="visible", timeout=15_000)
    narrate(page, "sbomify_open_component")
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
    narrate(page, "sbom_carries_signed")
    pace(page, 1500)
    provenance.hover()
    pace(page, 800)

    passed = page.locator("main").get_by_text("All passed").first
    passed.wait_for(state="visible", timeout=20_000)
    smooth_scroll(page, passed, 300)
    passed.hover()
    narrate(page, "sbom_verification_assessment")
    show_met = page.get_by_role("button", name=re.compile(r"^Show \d+ met requirements"))
    pace(page, 1500)
    hover_and_click(page, show_met)
    pace(page, 600)
    narrate(page, "open_met_requirements")
