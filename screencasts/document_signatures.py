"""Record the document-signature screencast.

Drives: Dashboard → Components → click into the Compression Core Library
component → SBOM list with the new "Signed" + "Provenance" badges
visible → linger so a viewer can read the FAQ tie-in. Pairs with the
``how-do-i-use-signature-files`` FAQ on sbomify.com.

The recording does NOT call the signature upload API live — POSTing
the bundle bytes from inside Playwright would couple the recording to
S3 / signature-store wiring that flakes in the test environment.
Instead we set ``signature_blob_key`` and ``signature_type`` on the
target SBOM via ORM in the fixture, which is the only thing the
component-detail template actually reads to render the badges. The
visible result is identical to a real upload, and the recording
stays deterministic.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    click_into_row,
    hover_and_click,
    navigate_to_components,
    pace,
    start_on_dashboard,
)

# The first component in ``PIED_PIPER_COMPONENTS`` — the natural lead
# in the recording's narrative because the badges read most clearly on
# a "library" component (a thing you would actually sign and ship).
SIGNED_COMPONENT_NAME = "Compression Core Library"


@pytest.fixture
def pied_piper_with_signed_sbom(pied_piper_with_sboms: dict) -> dict:
    """Mark one SBOM as signed + provenance-attested via ORM.

    The component-detail template renders the ``Signed`` badge when
    ``signature_blob_key`` is non-empty and the ``Provenance`` badge
    when ``provenance_blob_key`` is non-empty. Setting both lets the
    recording show the two-badge layout the FAQ talks about without
    standing up actual S3 storage for the signature bytes.

    The blob-key values are deliberately placeholder strings: the
    component-detail view does not dereference them, it only checks
    truthiness. Anything that round-trips through Django's text-field
    serializer works.
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
    return pied_piper_with_sboms


def _suppress_error_toasts(page: Page) -> None:
    """Drain any toast notifications during the recording.

    The component detail page lazy-loads several HTMX panels (release
    history, vulnerability summary). In the screencast environment a
    handful of those endpoints fail and pop "Failed to load …" toasts
    that have nothing to do with the signature flow. A 100 ms drain
    interval keeps those transient errors out of the recording.
    """
    page.add_init_script(
        """
        (() => {
            const drain = () => {
                const container = document.getElementById('toast-container');
                if (container) {
                    const data = window.Alpine?.$data(container);
                    if (data && Array.isArray(data.toasts)) data.toasts = [];
                }
                document.querySelectorAll('.tw-toast').forEach((el) => el.remove());
            };
            setInterval(drain, 100);
        })();
        """
    )


@pytest.mark.django_db(transaction=True)
def document_signatures(recording_page: Page, pied_piper_with_signed_sbom: dict) -> None:
    page = recording_page

    _suppress_error_toasts(page)
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

    # ── 5. Hover the Signed badge ──────────────────────────────────────
    # Move the cursor over the badge so the recording closes on the
    # piece of UI the FAQ tells viewers to look for. Hovering (rather
    # than clicking) keeps the badge as a passive indicator rather
    # than implying it opens a panel — it does not.
    box = sbom_signed_badge.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pace(page, 2000)

    # ── 6. Show the Plugins entry as the natural next step ──────────────
    # The FAQ closes on a pointer to the SBOM Verification plugin
    # which actually validates the signature. Hovering the sidebar
    # link makes that hand-off visible without leaving the recording
    # mid-load on a plugin-config page that has its own screencast.
    plugins_link = page.locator("nav a:has-text('Plugins')").first
    plugins_link.scroll_into_view_if_needed()
    plugins_box = plugins_link.bounding_box()
    if plugins_box:
        page.mouse.move(plugins_box["x"] + plugins_box["width"] / 2, plugins_box["y"] + plugins_box["height"] / 2)
    pace(page, 2000)

    # Final hold so the closing frame is not mid-transition.
    pace(page, 1000)


# Suppress unused-import warning for ``hover_and_click`` — kept so
# follow-up edits that need a real click on the badge don't have to
# re-import. Same pattern other screencasts use.
_ = hover_and_click
