"""Record the CRA Declaration of Conformity signature screencast.

Drives: Dashboard → Products → Pied Piper → Continue Assessment →
Step 5 (Review & Export) → fill the Annex V Section 8 fields (Place /
Name / Function) → draw a signature on the canvas → Save → click
Generate Declaration of Conformity → Preview the rendered DoC with
the embedded signature → Download Declaration of Conformity (PDF).

Pairs with the ``how-do-i-use-signature-files`` FAQ on sbomify.com.
The recording is the visual companion to the merged manufacturer-
signature feature (PR sbomify/sbomify#935), which is the reason the
issue #878 deliverable lives on the CRA wizard rather than on the
plain SBOM badges.

Mouse-driven signature drawing is intentional — the FAQ talks about
this exact affordance ("digitally captured signature embedded in the
DoC as a PNG"), and the recording would lose its punch if we used
``pad.fromData()`` to inject a pre-built signature via JS. We simulate
a few short strokes with ``page.mouse.move()`` so the canvas registers
real strokes through ``signature_pad``'s event handlers.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    hover_and_click,
    navigate_to_products,
    pace,
    start_on_dashboard,
)
from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAScopeScreening,
    OSCALAssessmentResult,
    OSCALCatalog,
)


@pytest.fixture
def pied_piper_with_completed_cra(pied_piper_with_sboms: dict) -> dict:
    """Pre-build a completed-but-unsigned CRA assessment for Pied Piper.

    The signature card on Step 5 renders regardless of the wizard's
    progress, but jumping straight to ``/step/5/`` on a fresh assessment
    looks half-finished — the stepper would show all four prior steps
    grey. Marking the prior steps complete makes the closing wizard
    state visually honest.

    We deliberately do not pre-set the signature fields: the recording
    captures the operator filling in Place / Name / Function and
    drawing the signature live, then saving. That is the headline UX
    the FAQ describes.
    """
    product = pied_piper_with_sboms["product"]
    team = product.team

    CRAScopeScreening.objects.create(
        product=product,
        team=team,
        has_data_connection=True,
        is_own_use_only=False,
        is_testing_version=False,
        is_covered_by_other_legislation=False,
        is_dual_use=False,
    )

    catalog = OSCALCatalog.objects.create(
        name="BSI TR-03183-1",
        version="1.0",
        catalog_json={"metadata": {"title": "BSI TR-03183-1 (screencast stub)"}},
    )
    oscal_result = OSCALAssessmentResult.objects.create(
        catalog=catalog,
        team=team,
        title="CRA OSCAL Result",
    )
    assessment = CRAAssessment.objects.create(
        team=team,
        product=product,
        oscal_assessment_result=oscal_result,
        completed_steps=[1, 2, 3, 4],
        current_step=5,
    )

    return {**pied_piper_with_sboms, "assessment": assessment}


def _suppress_error_toasts(page: Page) -> None:
    """Drain any lazy-load toast errors during the recording."""
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


def _draw_signature(page: Page) -> None:
    """Draw a short signature on the ``signature_pad`` canvas.

    ``signature_pad`` listens for ``pointerdown`` / ``pointermove`` /
    ``pointerup`` on the canvas. ``page.mouse`` issues real synthetic
    pointer events, so a sequence of small moves registers as a
    stroke. We trace two short looping waves rather than a single
    straight line so the closing frame shows a recognisable
    handwritten-looking shape rather than a stray scribble.
    """
    canvas = page.locator("canvas[aria-label*='Signature pad']").first
    canvas.wait_for(state="visible", timeout=10_000)
    canvas.scroll_into_view_if_needed()
    pace(page, 600)

    box = canvas.bounding_box()
    if not box:
        return

    # Anchor strokes inside the canvas with a comfortable margin so
    # the signature does not run off the edge.
    left = box["x"] + box["width"] * 0.15
    right = box["x"] + box["width"] * 0.85
    base_y = box["y"] + box["height"] * 0.55

    # First stroke — a relaxed sine wave from left to right.
    page.mouse.move(left, base_y)
    page.mouse.down()
    steps = 24
    import math

    for i in range(1, steps + 1):
        t = i / steps
        x = left + (right - left) * t
        y = base_y + math.sin(t * math.pi * 2) * (box["height"] * 0.18)
        page.mouse.move(x, y, steps=2)
    page.mouse.up()
    pace(page, 300)

    # Second stroke — a short underline a touch below the wave so the
    # canvas reads as a deliberate signature, not a single squiggle.
    underline_left = box["x"] + box["width"] * 0.30
    underline_right = box["x"] + box["width"] * 0.70
    underline_y = box["y"] + box["height"] * 0.80
    page.mouse.move(underline_left, underline_y)
    page.mouse.down()
    page.mouse.move(underline_right, underline_y, steps=10)
    page.mouse.up()
    pace(page, 400)


@pytest.mark.django_db(transaction=True)
def document_signatures(recording_page: Page, pied_piper_with_completed_cra: dict) -> None:
    page = recording_page

    _suppress_error_toasts(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Products → Pied Piper ────────────────────────────
    navigate_to_products(page)
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 2. Open the wizard at Step 5 (Review & Export) ──────────────────
    continue_btn = page.locator("a:has-text('Continue Assessment')").first
    continue_btn.wait_for(state="visible", timeout=15_000)
    continue_btn.scroll_into_view_if_needed()
    pace(page, 1500)
    hover_and_click(page, continue_btn)
    page.wait_for_load_state("networkidle")

    assessment = pied_piper_with_completed_cra["assessment"]
    page.goto(f"/compliance/cra/{assessment.id}/step/5/")
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 3. Scroll the signature card into view ──────────────────────────
    sign_heading = page.locator("h2:has-text('Sign the Declaration of Conformity')").first
    sign_heading.wait_for(state="visible", timeout=15_000)
    sign_heading.scroll_into_view_if_needed()
    pace(page, 1800)

    # ── 4. Fill Place / Name / Function ─────────────────────────────────
    # Real keystrokes (``type``) rather than a fast ``fill`` call so
    # the recording captures the typing animation a viewer expects on
    # a form-fill demo. Locating by placeholder rather than the
    # ``x-model`` expression because the Function field is bound to
    # ``roleFunction`` (the JS reserved word ``function`` cannot be
    # used as an Alpine state key) and the placeholder is a more
    # stable handle for the recording.
    place = page.locator("input[placeholder='City, country']").first
    place.click()
    place.type("Berlin, Germany", delay=40)
    pace(page, 400)

    name = page.locator("input[placeholder='Full legal name']").first
    name.click()
    name.type("Rana Aurangzaib", delay=40)
    pace(page, 400)

    role = page.locator("input[placeholder='Role / title']").first
    role.click()
    role.type("Lead Maintainer", delay=40)
    pace(page, 400)

    # Belt-and-suspenders: ``page.type`` fires input events, but
    # Alpine's two-way binding has occasionally been observed to lag
    # on the third field in this form (the ``roleFunction`` reactive
    # property is initialised to ``""`` but landed at ``null`` once
    # in CI). Force the bound state from the input value directly so
    # the save handler's ``trim()`` check passes deterministically.
    page.evaluate(
        """
        () => {
            const root = document.querySelector('[x-data*="craDocSignature"]');
            const ctx = window.Alpine?.$data(root);
            if (!ctx) return;
            const v = (sel) => root.querySelector(sel)?.value || '';
            ctx.place = v("input[placeholder='City, country']");
            ctx.name = v("input[placeholder='Full legal name']");
            ctx.roleFunction = v("input[placeholder='Role / title']");
        }
        """
    )
    pace(page, 200)

    # ── 5. Draw the signature ───────────────────────────────────────────
    _draw_signature(page)
    pace(page, 800)

    # Belt-and-suspenders: Playwright's mouse events do not always
    # surface as ``pointerdown`` / ``pointermove`` events on every
    # browser channel, and ``signature_pad`` requires pointer events
    # to register strokes. If the mouse pass left ``pad.toData()``
    # empty we inject a deterministic two-stroke signature directly
    # so the recording moves on instead of stalling on an empty-pad
    # rejection. Either pass produces a visible signature on the
    # canvas in the recording.
    pad_strokes = page.evaluate(
        """
        () => {
            const root = document.querySelector('[x-data*="craDocSignature"]');
            const ctx = window.Alpine?.$data(root);
            return ctx?.pad ? ctx.pad.toData().length : 0;
        }
        """
    )
    if not pad_strokes:
        page.evaluate(
            """
            () => {
                const root = document.querySelector('[x-data*="craDocSignature"]');
                const ctx = window.Alpine?.$data(root);
                if (!ctx?.pad) return;
                const c = root.querySelector('canvas');
                const w = c.offsetWidth || 600;
                const h = c.offsetHeight || 160;
                const baseY = h * 0.55;
                const left = w * 0.15;
                const right = w * 0.85;
                const wave = [];
                for (let i = 0; i <= 24; i++) {
                    const t = i / 24;
                    wave.push({
                        x: left + (right - left) * t,
                        y: baseY + Math.sin(t * Math.PI * 2) * h * 0.18,
                        time: Date.now() + i * 16,
                        pressure: 0.5,
                    });
                }
                const underline = [];
                const uL = w * 0.30;
                const uR = w * 0.70;
                const uY = h * 0.80;
                for (let i = 0; i <= 10; i++) {
                    underline.push({
                        x: uL + (uR - uL) * (i / 10),
                        y: uY,
                        time: Date.now() + 600 + i * 20,
                        pressure: 0.5,
                    });
                }
                ctx.pad.fromData([
                    { dotSize: 1.5, minWidth: 0.6, maxWidth: 2.0, penColor: 'black', points: wave },
                    { dotSize: 1.5, minWidth: 0.6, maxWidth: 2.0, penColor: 'black', points: underline },
                ]);
            }
            """
        )
        pace(page, 600)

    # ── 6. Save the signature ───────────────────────────────────────────
    save_btn = page.locator("button:has-text('Save signature')").first
    save_btn.scroll_into_view_if_needed()
    pace(page, 400)

    # Drive the PUT directly via JS rather than relying on the @click
    # button handler. The toast-suppression init script registers a
    # 100 ms drain interval that competes with Alpine's listener
    # attachment on slow first-paint and intermittently swallows the
    # save click. Building the payload here and PUTing it through
    # ``fetch`` keeps the recording deterministic while exercising
    # the exact same API path the click would. The button hover is
    # preserved so the visible UX in the recording is unchanged.
    with page.expect_response(lambda r: "/signature" in r.url and r.request.method == "PUT", timeout=15_000) as info:
        box = save_btn.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.evaluate(
            """
            async () => {
                const root = document.querySelector('[x-data*="craDocSignature"]');
                const ctx = window.Alpine?.$data(root);
                if (!ctx || !ctx.pad || ctx.pad.isEmpty()) return;
                const image = ctx.pad.toDataURL('image/png');
                const csrf = document.cookie.split('; ')
                    .find((r) => r.startsWith('csrftoken='))
                    ?.split('=')[1] || '';
                const resp = await fetch(
                    `/api/v1/compliance/cra/${ctx.assessmentId}/signature`,
                    {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrf,
                        },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            place: ctx.place.trim(),
                            name: ctx.name.trim(),
                            function: ctx.roleFunction.trim(),
                            image,
                        }),
                    },
                );
                if (resp.ok) {
                    const body = await resp.json();
                    ctx.image = body.image || image;
                    ctx.signedAt = body.signed_at;
                    ctx.isSigned = !!body.is_signed;
                }
            }
            """
        )
    response = info.value
    if response.status != 200:
        body = response.text()
        raise AssertionError(f"Signature save failed: HTTP {response.status} body={body!r}")

    page.wait_for_load_state("networkidle")
    # The "Last signed …" timestamp appears once the API round-trip
    # completes; waiting on its visibility makes the recording wait
    # for the success toast / state flip rather than racing it.
    last_signed = page.locator("text=Last signed").first
    last_signed.wait_for(state="visible", timeout=10_000)
    pace(page, 1800)

    # ── 7. Refresh the DoC so it embeds the new signature ──────────────
    refresh_btn = page.locator("button:has-text('Refresh Stale Documents')").first
    refresh_btn.scroll_into_view_if_needed()
    pace(page, 600)
    hover_and_click(page, refresh_btn)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 8. Preview the signed Declaration of Conformity ────────────────
    preview_btn = page.locator("button[data-testid='preview-doc-btn']").first
    preview_btn.scroll_into_view_if_needed()
    pace(page, 400)
    hover_and_click(page, preview_btn)
    # The preview modal is HTMX-loaded; wait for the rendered body
    # before lingering so the closing frame is not mid-fetch.
    preview_body = page.locator("#preview-modal-title").first
    preview_body.wait_for(state="visible", timeout=15_000)
    pace(page, 2500)

    # Close the modal so the next button hover is unobstructed.
    close_modal_btn = page.locator("button[aria-label='Close preview']").first
    if close_modal_btn.count():
        hover_and_click(page, close_modal_btn)
    else:
        page.keyboard.press("Escape")
    pace(page, 800)

    # ── 9. Hover the Download (PDF) button so the FAQ tie-in is visible ─
    # Hover only — clicking would trigger a real download that the
    # screencast environment cannot complete (WeasyPrint Pango deps
    # are dev-only). The button itself is what the FAQ points to.
    download_btn = page.locator("button[data-testid='download-doc-pdf-btn']").first
    download_btn.scroll_into_view_if_needed()
    pace(page, 400)
    box = download_btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pace(page, 2000)
