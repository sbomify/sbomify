"""Record the document-signature screencast.

Drives: Dashboard → Components → click into the Compression Core
Library component → SBOM list with the new "Signed" + "Provenance"
badges visible → linger on the badges → close on the SBOM
Verification plugin's "All Passed" Assessment Results card. Pairs
with the ``how-do-i-use-signature-files`` FAQ on sbomify.com.

The recording does NOT call the signature upload API or run the
real plugin pipeline — POSTing bundle bytes from inside Playwright
or waiting on an asynchronous Dramatiq plugin run would couple the
recording to S3 / signature-store / worker wiring that flakes in
the test environment. Instead the fixture seeds the visible state
directly via ORM:

- ``signature_blob_key`` / ``signature_type`` / ``provenance_blob_key``
  on the target SBOM — drive the Signed / Provenance badges.
- A completed ``AssessmentRun`` for the ``sbom-verification`` plugin
  whose result the plugin itself produces, with only its Sigstore and
  storage reads stood in for (see ``_verification_result``). The
  Assessment Results card and the green Signed chip both read it, so the
  closing frame is exactly what a real signed-and-attested SBOM shows.

The visible UX is indistinguishable from a real upload-then-scan
flow, the recording stays deterministic, and we cover the worker
wait state in the FAQ rather than baking a flaky polling loop into
the screencast.
"""

import base64
import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from playwright.sync_api import Page

from conftest import (
    auto_dismiss_toasts,
    click_into_row,
    hover_and_click,
    navigate_to_components,
    pace,
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


@pytest.fixture
def pied_piper_with_signed_sbom(pied_piper_with_sboms: dict) -> dict:
    """Seed signature + provenance blobs and a passing verification run.

    The component-detail template renders the ``Signed`` badge when
    ``signature_blob_key`` is non-empty and the ``Provenance`` badge
    when ``provenance_blob_key`` is non-empty. Setting both lets the
    recording show the two-badge layout the FAQ talks about without
    standing up actual S3 storage for the signature bytes.

    The Assessment Results card on the SBOM detail page reads
    completed ``AssessmentRun`` rows for the SBOM and renders the
    "All Passed" badge when every run's summary reports zero
    failures. We pre-create one for the ``sbom-verification``
    plugin so the closing frame of the recording shows the
    operator-visible payoff of attaching the artefacts.
    """
    sbom = pied_piper_with_sboms["sboms"][SIGNED_COMPONENT_NAME]
    sbom.signature_blob_key = f"signatures/{sbom.id}/cosign-bundle.sig"
    sbom.signature_type = "cosign-bundle"
    sbom.provenance_blob_key = f"provenance/{sbom.id}/build-provenance.intoto.jsonl"
    sbom.save(
        update_fields=[
            "signature_blob_key",
            "signature_type",
            "provenance_blob_key",
        ]
    )

    # The plugin name and version come from the plugin's own result, so
    # the card sees the identifier a production run would emit.
    # ``RunReason.ON_UPLOAD``
    # is the canonical enum value the UI's ``format_run_reason``
    # helper translates to "Upload"; the previous ``"sbom_uploaded"``
    # literal didn't round-trip through that mapping.
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

    return pied_piper_with_sboms


@pytest.mark.django_db(transaction=True)
def document_signatures(recording_page: Page, pied_piper_with_signed_sbom: dict) -> None:
    page = recording_page

    # Component detail + SBOM detail pages lazy-load HTMX panels
    # (release history, vulnerability summary, notification websocket)
    # that fail in the screencast environment and pop "Failed to load
    # …" toasts unrelated to the signature flow. The shared
    # ``auto_dismiss_toasts`` helper attaches a MutationObserver that
    # drains those toasts the moment they are appended — observers
    # only fire on real DOM mutations, so there is no polling
    # overhead and no interval to clean up.
    auto_dismiss_toasts(page)
    start_on_dashboard(page)

    # ── 1. Components page ──────────────────────────────────────────────
    # The Components sidebar entry leads to the table that lists every
    # component in the workspace. We open it first so a viewer sees the
    # path the FAQ prose describes ("Components → click into the
    # component → SBOM list with badges").
    navigate_to_components(page)
    pace(page, 1500)

    # ── 2. Click into the signed component ──────────────────────────────
    click_into_row(page, SIGNED_COMPONENT_NAME)
    pace(page, 1500)

    # ── 3. Open the SBOM detail page ────────────────────────────────────
    # The Signed / Provenance badges live on the *SBOM* detail page,
    # not the component overview. The component overview shows a
    # "BOMs" section that is HTMX-loaded; once the table arrives the
    # SBOM filename is a link to ``/components/<id>/sboms/<sbom-id>/``.
    # The SBOM names are slugified from the component name in the
    # fixture (``com.piedpiper/<component-slug>``); ``Compression Core
    # Library`` slugifies to ``compression-core-library``.
    sbom_link = page.locator("a:has-text('com.piedpiper/compression-core-library')").first
    sbom_link.wait_for(state="visible", timeout=15_000)
    sbom_link.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 1500)
    hover_and_click(page, sbom_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 4. Linger on the badges ────────────────────────────────────────
    # The "Signed" (green padlock) + "Provenance" (blue shield) badges
    # render inline next to the SBOM metadata block. They show the
    # moment the page loads — no interaction needed — so we just
    # scroll the badge row into view and pause for the FAQ tie-in.
    sbom_signed_badge = page.locator("span.text-success:has-text('Signed')").first
    sbom_signed_badge.wait_for(state="visible", timeout=15_000)
    sbom_signed_badge.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 2500)

    provenance_badge = page.locator("span.text-info:has-text('Provenance')").first
    provenance_badge.wait_for(state="visible", timeout=10_000)
    provenance_badge.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 2500)

    # ── 5. Wait for the SBOM Verification result to render ──────────────
    # The Assessment Results card is HTMX-loaded after the page
    # paint. ``All Passed`` is the headline pill that lights up when
    # the seeded ``sbom-verification`` AssessmentRun's summary
    # reports zero failures across every finding — the same outcome
    # a real signed-and-attested SBOM produces once the worker
    # finishes.
    all_passed = page.locator("span:has-text('All Passed')").first
    all_passed.wait_for(state="visible", timeout=20_000)
    all_passed.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 2500)

    # Hover the All Passed pill so the closing frame anchors on the
    # operator-visible outcome the FAQ promises.
    box = all_passed.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pace(page, 2500)
