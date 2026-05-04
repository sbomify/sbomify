"""Record the CRA Compliance Wizard screencast.

Drives the full wizard end-to-end: Dashboard → Products → Pied Piper
product → Continue Assessment → walk every panel of every step
(Steps 1–5) → exercise Step 3's three tabs (checklist, vulnerability,
incident) → land on Step 5 with the Export Compliance Bundle CTA in
view. The recording's job is to give the FAQ a visual companion that
covers what each step actually contains, not just the headline of
each step — so we scroll every named section into the viewport and
linger long enough for a viewer to read the heading.

The screencast pairs with the FAQ article at
``how-do-i-use-cra-compliance``. We pre-create the CRAScopeScreening,
OSCAL catalog/result and CRAAssessment via ORM rather than driving
the scope-screening checkboxes, because the screening uses an Alpine
x-model with a default that is reactive at init time — clicking the
visual label is racy on first paint and a flaky gate would invalidate
the whole recording.

To keep the stepper visually honest we update ``completed_steps`` and
``current_step`` on the assessment as the recording moves between
steps, then ``page.goto()`` directly. ``CRAStepView`` accepts any step
number, so we do not need to click stepper links (which only render
for steps already in ``completed_steps``); driving the database
mirrors what the user would see after pressing Save & Continue.
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
def pied_piper_with_cra_assessment(pied_piper_with_sboms: dict) -> dict:
    """Extend pied_piper_with_sboms with a CRAAssessment ready for the wizard.

    Pre-creates the scope screening (cra_applies=True), an OSCAL catalog
    and assessment result, and a CRAAssessment linked to the product so
    the wizard shell renders Step 1 immediately. Returns the same dict
    plus an 'assessment' key.
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
        # Fresh state — the recording advances completed_steps as it
        # moves through the wizard so the stepper shows the realistic
        # in-progress shape (current step blue, completed green, rest
        # muted) rather than implying everything is already done.
        completed_steps=[],
        current_step=1,
    )

    return {**pied_piper_with_sboms, "assessment": assessment}


def _suppress_error_toasts(page: Page) -> None:
    """Continuously dismiss any toast notifications during the recording.

    The product detail page lazy-loads several HTMX panels (Releases,
    Identifiers, Vulnerability Trends). In the screencast environment
    a few of those endpoints fail and pop "Failed to load …" toasts
    that have nothing to do with the wizard flow. We register a
    100 ms interval that drains the toast container so transient
    errors never make it into the recording.
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
def cra_compliance(recording_page: Page, pied_piper_with_cra_assessment: dict) -> None:
    page = recording_page

    _suppress_error_toasts(page)
    start_on_dashboard(page)

    # ── 1. Navigate to Products ──────────────────────────────────────────
    navigate_to_products(page)

    # ── 2. Click into Pied Piper ─────────────────────────────────────────
    product_link = page.locator(f"span.text-text:text-is('{PIED_PIPER_PRODUCT_NAME}')")
    product_link.wait_for(state="visible", timeout=15_000)
    pace(page, 500)
    hover_and_click(page, product_link)
    page.wait_for_load_state("networkidle")
    pace(page, 1500)

    # ── 3. Show the CRA Compliance card ──────────────────────────────────
    # The card sits mid-page among the product detail panels. With an
    # assessment present the CTA reads "Continue Assessment" — that is
    # the resume path most users will see day-to-day.
    continue_btn = page.locator("a:has-text('Continue Assessment')").first
    continue_btn.wait_for(state="visible", timeout=15_000)
    continue_btn.scroll_into_view_if_needed()
    pace(page, 2000)

    # ── 4. Open the wizard ──────────────────────────────────────────────
    hover_and_click(page, continue_btn)
    page.wait_for_load_state("networkidle")
    pace(page, 2000)

    # ── 5. Step 1: Product Profile ──────────────────────────────────────
    # Walk every named section so the recording captures the full shape
    # of the first step. The wizard is sticky-headed; scrolling each h2
    # into view brings the next panel above the fold without the
    # navigation flicker of a fresh page load.
    step_1_sections = [
        "Product Information",
        "CRA Classification",
        "Harmonised Standards Applicability",
        "Target EU Markets",
        "Support Period",
        "Intended Use",
    ]
    first_step_1 = page.locator(f"h2:has-text('{step_1_sections[0]}')").first
    first_step_1.wait_for(state="visible", timeout=15_000)
    pace(page, 2500)
    for heading in step_1_sections[1:]:
        page.locator(f"h2:has-text('{heading}')").first.scroll_into_view_if_needed()
        pace(page, 2000)

    # ── 6. Scroll back up so the stepper is fully visible ───────────────
    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 1500)

    # ── 7. Advance to Step 2 (SBOM Compliance) ──────────────────────────
    # Mark Step 1 complete and advance current_step before navigating —
    # the stepper then renders Step 1 with a green check and Step 2 as
    # the active blue marker, matching what the user would see after
    # pressing Save & Continue from Step 1.
    assessment = pied_piper_with_cra_assessment["assessment"]
    assessment.completed_steps = [1]
    assessment.current_step = 2
    assessment.save(update_fields=["completed_steps", "current_step"])
    page.goto(f"/compliance/cra/{assessment.id}/step/2/")
    page.wait_for_load_state("networkidle")
    pace(page, 2000)

    # ── 8. Step 2: SBOM Compliance ──────────────────────────────────────
    # "SBOM Compliance Summary" is the rolled-up BSI TR-03183 status
    # across the product; "Components" lists each component with its
    # individual findings. Walking both gives viewers the per-product /
    # per-component shape the FAQ describes.
    for heading in ("SBOM Compliance Summary", "Components"):
        loc = page.locator(f"h2:has-text('{heading}')").first
        loc.wait_for(state="visible", timeout=15_000)
        loc.scroll_into_view_if_needed()
        pace(page, 2500)

    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 1500)

    # ── 9. Advance to Step 3 (Security & Vulnerability) ─────────────────
    # Step 3 has three tabs (Annex I checklist, vulnerability disclosure,
    # incident reporting) all driven from one Alpine ``activeTab``
    # state. The recording exercises each tab so the FAQ can refer
    # back to specific sections without saying "click somewhere on
    # this page".
    assessment.completed_steps = [1, 2]
    assessment.current_step = 3
    assessment.save(update_fields=["completed_steps", "current_step"])
    page.goto(f"/compliance/cra/{assessment.id}/step/3/")
    page.wait_for_load_state("networkidle")
    pace(page, 2000)

    # The default tab is "Security Checklist" — Annex I controls.
    # Linger long enough for the viewer to take in the structure, then
    # click the other two tabs in turn. Tab button labels and the
    # ``activeTab`` state names differ ("Vulnerability Handling" vs
    # ``activeTab === 'vulnerability'``); we drive on the visible
    # button text because that is what the viewer actually sees.
    checklist_tab = page.locator("button:has-text('Security Checklist')").first
    if checklist_tab.count():
        checklist_tab.scroll_into_view_if_needed()
    pace(page, 2500)
    page.evaluate("window.scrollBy({ top: 250, behavior: 'smooth' })")
    pace(page, 2000)

    vuln_tab = page.locator("button:has-text('Vulnerability Handling')").first
    vuln_tab.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, vuln_tab)
    pace(page, 2500)
    page.locator("h2:has-text('Vulnerability Disclosure')").first.scroll_into_view_if_needed()
    pace(page, 2000)

    incident_tab = page.locator("button:has-text('Incident Reporting')").first
    incident_tab.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, incident_tab)
    pace(page, 2500)
    page.locator("h2:has-text('Incident Reporting (Article 14)')").first.scroll_into_view_if_needed()
    pace(page, 2000)

    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 1500)

    # ── 10. Advance to Step 4 (User Information) ────────────────────────
    # Annex II inputs that drive the "User Instructions" generated
    # document. Walk every named section so the FAQ can call out what
    # the operator has to fill in here.
    assessment.completed_steps = [1, 2, 3]
    assessment.current_step = 4
    assessment.save(update_fields=["completed_steps", "current_step"])
    page.goto(f"/compliance/cra/{assessment.id}/step/4/")
    page.wait_for_load_state("networkidle")
    pace(page, 2000)

    step_4_sections = [
        "Product Type",
        "Update & Distribution",
        "Support Contact",
        "Data & Decommissioning",
    ]
    first_step_4 = page.locator(f"h2:has-text('{step_4_sections[0]}')").first
    first_step_4.wait_for(state="visible", timeout=15_000)
    pace(page, 2500)
    for heading in step_4_sections[1:]:
        page.locator(f"h2:has-text('{heading}')").first.scroll_into_view_if_needed()
        pace(page, 2000)

    page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    pace(page, 1500)

    # ── 11. Advance to Step 5 (Review & Export) ─────────────────────────
    # Step 5 is what the FAQ leads with as the deliverable. Walk every
    # panel: Compliance Summary (rolled-up posture), Export (the
    # bundle CTA), Last Export Bundle (manifest preview), Documents
    # (per-document staleness + preview/generate buttons).
    assessment.completed_steps = [1, 2, 3, 4]
    assessment.current_step = 5
    assessment.save(update_fields=["completed_steps", "current_step"])
    page.goto(f"/compliance/cra/{assessment.id}/step/5/")
    page.wait_for_load_state("networkidle")
    pace(page, 2000)

    summary_heading = page.locator("h2:has-text('Compliance Summary')").first
    summary_heading.wait_for(state="visible", timeout=15_000)
    pace(page, 2500)

    # Highlight the Export Compliance Bundle button — hover only, do
    # not click. Clicking would kick off a real export that the
    # screencast environment cannot complete (no S3, no signing). The
    # FAQ's "What is in the export bundle" section unpacks what the
    # button produces.
    export_heading = page.locator("h2:has-text('Export')").first
    export_heading.scroll_into_view_if_needed()
    pace(page, 2000)

    export_btn = page.locator("button:has-text('Export Compliance Bundle')").first
    export_btn.wait_for(state="visible", timeout=10_000)
    export_btn.scroll_into_view_if_needed()
    pace(page, 800)
    box = export_btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pace(page, 2500)

    # The "Last Export Bundle" card appears only when a previous
    # export exists for this assessment. In the screencast environment
    # there is no prior export, so we fall back to a no-op when the
    # heading is absent — keeps the recording resilient to test data
    # shape without fabricating an unrealistic bundle row.
    bundle_card = page.locator("h2:has-text('Last Export Bundle')").first
    if bundle_card.count():
        bundle_card.scroll_into_view_if_needed()
        pace(page, 2500)

    documents_heading = page.locator("h2:has-text('Documents')").first
    documents_heading.scroll_into_view_if_needed()
    pace(page, 2500)
    # One extra scroll so the bottom of the document list (Declaration
    # of Conformity row + the Back link) is in view at the closing
    # frame, mirroring how a user would end the wizard pass.
    page.evaluate("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })")
    pace(page, 2500)
