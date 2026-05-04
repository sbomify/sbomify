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
  with five passing findings — drives the Assessment Results card's
  "All Passed" badge so the closing frame shows the same visible
  outcome a real signed-and-attested SBOM would produce.

The visible UX is indistinguishable from a real upload-then-scan
flow, the recording stays deterministic, and we cover the worker
wait state in the FAQ rather than baking a flaky polling loop into
the screencast.
"""

import uuid
from datetime import datetime, timezone

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
from sbomify.apps.plugins.models import AssessmentRun

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

    plugin_name = "sbom-verification"
    plugin_version = "1.0.0"
    now = datetime.now(tz=timezone.utc)
    AssessmentRun.objects.create(
        id=uuid.uuid4(),
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version=plugin_version,
        plugin_config_hash="0" * 64,
        category="attestation",
        run_reason="sbom_uploaded",
        status="completed",
        started_at=now,
        completed_at=now,
        input_content_digest="0" * 64,
        result=_verification_result(plugin_name, plugin_version),
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
    sbom_link.scroll_into_view_if_needed()
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
    sbom_signed_badge.scroll_into_view_if_needed()
    pace(page, 2500)

    provenance_badge = page.locator("span.text-info:has-text('Provenance')").first
    provenance_badge.wait_for(state="visible", timeout=10_000)
    provenance_badge.scroll_into_view_if_needed()
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
    all_passed.scroll_into_view_if_needed()
    pace(page, 2500)

    # Hover the All Passed pill so the closing frame anchors on the
    # operator-visible outcome the FAQ promises.
    box = all_passed.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pace(page, 2500)
