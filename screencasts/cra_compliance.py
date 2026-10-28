"""Record the CRA compliance screencast.

Drives the whole flow through the real UI: sidebar Compliance → Start
assessment → pick the product → scope screening → the five wizard steps
(each advanced with its own "Save and continue") → sign the Declaration of
Conformity → export the compliance bundle → mark the assessment complete →
the public product page, where the vulnerability disclosure policy and the
Declaration of Conformity are now published.

Preconditions that are not the subject of the video are seeded with the ORM:
a manufacturer in the workspace Parties (the wizard refuses a placeholder
manufacturer), product lifecycle dates (which pre-fill the support period),
and all but the first two Annex I controls already answered, so Step 3 shows
the viewer answering the last two rather than twenty-one.

The screencast stack runs no S3, so :func:`cra_fake_s3` backs the object
store with a dict. Everything above the store (document generation, the
export ZIP and its manifest, the public pages reading the documents back)
runs for real.
"""

import re
from datetime import date

import pytest
from playwright.sync_api import Page

from conftest import (
    PIED_PIPER_PRODUCT_NAME,
    auto_dismiss_toasts,
    hover_and_click,
    narrate,
    pace,
    rewrite_localhost_urls,
    settle,
    sidebar_link,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)
from sbomify.apps.compliance.models import CRAAssessment, OSCALFinding
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact

MINIMAL_CYCLONEDX = b'{"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": []}'


@pytest.fixture
def cra_fake_s3(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], bytes]:
    """Back :class:`StorageClient` with an in-process dict.

    Generated documents and the export ZIP are written here and read back by
    the wizard and the public pages. SBOM reads return a minimal CycloneDX
    body so the bundle carries one SBOM per component, and the presigned
    download URL points at ``about:blank`` (the popup it opens is closed).
    """
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: StorageClient, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: StorageClient, bucket_name: str, object_name: str) -> bytes | None:
        return store.get((bucket_name, object_name))

    monkeypatch.setattr(StorageClient, "upload_data_as_file", _put)
    monkeypatch.setattr(StorageClient, "get_file_data", _get)
    monkeypatch.setattr(StorageClient, "get_sbom_data", lambda self, name: MINIMAL_CYCLONEDX)
    monkeypatch.setattr(StorageClient, "generate_presigned_url", lambda self, *a, **kw: "about:blank")
    return store


@pytest.fixture
def cra_ready_workspace(pied_piper_with_sboms: dict) -> dict:
    """Manufacturer, security contact and lifecycle dates the wizard reads."""
    product = pied_piper_with_sboms["product"]
    team = product.team
    # The shared fixture names the workspace "Test Business Team", which shows
    # in the sidebar and the public page footer.
    team.name = "Pied Piper"
    team.save(update_fields=["name"])

    profile = ContactProfile.objects.create(team=team, name="Pied Piper", is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Pied Piper B.V.",
        email="compliance@example.com",
        address="Keizersgracht 100, 1015 AA Amsterdam, Netherlands",
        website_urls=["https://piedpiper.example.com"],
        is_manufacturer=True,
        is_supplier=True,
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Richard Hendricks",
        email="security@example.com",
        is_security_contact=True,
    )

    # Published up front: any later product save marks every CRA document
    # stale, and a stale Declaration of Conformity is hidden from the public
    # page the video ends on.
    team.is_public = True
    team.save(update_fields=["is_public"])
    product.release_date = date(2026, 3, 15)
    product.end_of_support = date(2031, 3, 15)
    product.is_public = True
    product.save(update_fields=["release_date", "end_of_support", "is_public"])
    Component.objects.filter(products=product).update(visibility=Component.Visibility.PUBLIC)
    return pied_piper_with_sboms


def _answer_all_but_first_two(assessment: CRAAssessment) -> None:
    findings = list(
        OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
        .order_by("control__sort_order")
        .values_list("pk", flat=True)
    )
    OSCALFinding.objects.filter(pk__in=findings[2:]).update(status=OSCALFinding.FindingStatus.SATISFIED)


def _save_and_continue(page: Page, step: int, label: str = "Save and continue") -> None:
    """Press the step's own continue button and wait for the next step.

    The steps do not share a label: step 2 says "Continue", step 3
    "Save & Continue", steps 1 and 4 "Save and continue".
    """
    btn = page.get_by_role("button", name=label, exact=True)
    smooth_scroll(page, btn, 500)
    hover_and_click(page, btn)
    page.wait_for_url(re.compile(rf".*/cra/[^/]+/step/{step}/?$"), timeout=20_000)
    page.wait_for_load_state("networkidle")
    pace(page, 900)


@pytest.mark.django_db(transaction=True)
# Requested as marks so they run before ``recording_page`` builds the session:
# the sidebar reads the workspace name from it.
@pytest.mark.usefixtures("cra_fake_s3", "cra_ready_workspace")
def cra_compliance(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page
    product = pied_piper_with_sboms["product"]

    # The bundle download opens a new tab; it is not part of the story.
    page.context.on("page", lambda popup: popup.close())

    auto_dismiss_toasts(page)
    # The opening line plays over the splash while the dashboard loads.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=0)

    # ── CRA overview → Start assessment ───────────────────────────────────
    narrate(page, "compliance_lists_every")
    hover_and_click(page, sidebar_link(page, "Compliance"))
    page.wait_for_load_state("networkidle")
    pace(page, 800)

    start_btn = page.get_by_role("button", name="Start assessment").first
    start_btn.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, start_btn)
    pace(page, 700)

    product_select = page.locator("#cra-product-choice")
    product_select.wait_for(state="visible", timeout=10_000)
    hover_and_click(page, product_select)
    product_select.select_option(label=PIED_PIPER_PRODUCT_NAME)
    pace(page, 600)

    hover_and_click(page, page.get_by_role("button", name="Start scope screening"))
    page.wait_for_url("**/cra/scope/**", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 600)

    # ── Scope screening ───────────────────────────────────────────────────
    narrate(page, "first_scope_screening")
    for question in (
        "Manufactured exclusively for own use",
        "Covered by exempted EU legislation",
        "Dual-use (civilian + defense)",
    ):
        smooth_scroll(page, page.get_by_text(question, exact=True), 900)

    verdict = page.get_by_role("heading", name="CRA applies to this product")
    verdict.wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, verdict, 600)
    narrate(page, "pied_piper_has")
    save_screening = page.get_by_role("button", name="Save & Continue to Wizard")
    smooth_scroll(page, save_screening, 400)

    # Spoken from the save onward: the answers are stored and step one opens.
    narrate(page, "answers_saved_audit")
    hover_and_click(page, save_screening)
    page.wait_for_url(re.compile(r".*/cra/[^/]+/step/1/?$"), timeout=20_000)
    page.wait_for_load_state("networkidle")

    assessment = CRAAssessment.objects.get(product=product)
    _answer_all_but_first_two(assessment)

    # ── Step 1: product profile ───────────────────────────────────────────
    category = page.locator("#product-category")
    smooth_scroll(page, category, 500)
    narrate(page, "pick_product_category")
    hover_and_click(page, category)
    category.select_option("default")
    pace(page, 500)
    module_a = page.locator("input[name='conformity_procedure']").first
    if not module_a.is_checked():
        hover_and_click(page, module_a)
    pace(page, 600)

    all_markets = page.locator("label[for='all-markets']")
    smooth_scroll(page, all_markets, 500)
    narrate(page, "choose_eu_markets")
    hover_and_click(page, all_markets)
    pace(page, 900)
    smooth_scroll(page, page.locator("#support-period-end"), 1200)

    intended_use = page.locator("#intended-use")
    smooth_scroll(page, intended_use, 400)
    hover_and_click(page, intended_use)
    type_text(intended_use, "Middle-out compression for enterprise data pipelines.", delay=25)
    pace(page, 300)

    eu_yes = page.get_by_test_id("eu-established-yes")
    smooth_scroll(page, eu_yes, 400)
    narrate(page, "record_manufacturer_established")
    hover_and_click(page, eu_yes)
    pace(page, 600)
    _save_and_continue(page, 2)

    # ── Step 2: SBOM compliance ───────────────────────────────────────────
    narrate(page, "step_two_confirms")
    components_heading = page.get_by_role("heading", name="Components")
    components_heading.wait_for(state="visible", timeout=15_000)
    pace(page, 1500)
    smooth_scroll(page, components_heading, 1800)
    narrate(page, "four_components_four")
    _save_and_continue(page, 3, "Continue")

    # ── Step 3: security requirements ─────────────────────────────────────
    narrate(page, "step_three_annex")
    satisfied = page.locator("#panel-checklist label").filter(has=page.locator("input[value='satisfied']"))
    satisfied.first.wait_for(state="visible", timeout=15_000)
    pace(page, 1200)
    narrate(page, "last_two_answers")
    for i in range(2):
        hover_and_click(page, satisfied.nth(i))
        pace(page, 900)

    narrate(page, "vulnerability_handling_sets")
    hover_and_click(page, page.locator("#tab-vulnerability"))
    pace(page, 500)
    narrate(page, "incident_reporting_names")
    hover_and_click(page, page.locator("#tab-incident"))
    pace(page, 500)
    csirt = page.locator("#csirt-country")
    hover_and_click(page, csirt)
    csirt.select_option("NL")
    pace(page, 900)
    _save_and_continue(page, 4, "Save & Continue")

    # ── Step 4: user information ──────────────────────────────────────────
    narrate(page, "step_four_collects")
    product_type = page.locator("#product-type")
    product_type.wait_for(state="visible", timeout=15_000)
    hover_and_click(page, product_type)
    product_type.select_option("library")
    pace(page, 900)
    deletion = page.locator("#data-deletion")
    smooth_scroll(page, deletion, 400)
    hover_and_click(page, deletion)
    type_text(deletion, "Remove the library from your build and delete its cache directory.", delay=25)
    pace(page, 400)
    _save_and_continue(page, 5)

    # ── Step 5: sign, export, complete ────────────────────────────────────
    narrate(page, "step_five_review")

    signature_heading = page.get_by_role("heading", name="Sign the Declaration of Conformity")
    smooth_scroll(page, signature_heading, 500)
    narrate(page, "sign_declaration_conformity")
    sign_card = page.locator("[x-data='craDocSignature()']")
    for placeholder, value in (
        ("City, country", "Amsterdam, Netherlands"),
        ("Full legal name", "Richard Hendricks"),
        ("Role / title", "Chief Executive Officer"),
    ):
        field = sign_card.get_by_placeholder(placeholder)
        hover_and_click(page, field)
        type_text(field, value, delay=25)
    canvas = sign_card.locator("canvas")
    smooth_scroll(page, canvas, 400)
    box = canvas.bounding_box()
    if box:
        x0, y0, w, h = box["x"], box["y"], box["width"], box["height"]
        points = [(0.12, 0.65), (0.18, 0.3), (0.24, 0.7), (0.3, 0.35), (0.36, 0.6), (0.44, 0.4), (0.52, 0.62)]
        page.mouse.move(x0 + w * points[0][0], y0 + h * points[0][1])
        page.mouse.down()
        for px, py in points[1:]:
            page.mouse.move(x0 + w * px, y0 + h * py, steps=8)
        page.mouse.up()
    pace(page, 400)
    with page.expect_response(lambda r: "/signature" in r.url and r.request.method in ("PUT", "POST")):
        hover_and_click(page, sign_card.get_by_role("button", name="Save signature"))
    pace(page, 900)

    # Generate every document from its own card. The DoC is generated after
    # the signature is saved, so it carries the signature.
    documents = page.get_by_role("heading", name="Documents", exact=True)
    smooth_scroll(page, documents, 400)
    narrate(page, "generate_documents_disclosure")
    generate_buttons = page.locator("button[aria-label^='Generate ']")
    for i in range(generate_buttons.count()):
        with page.expect_response(lambda r: "/generate/" in r.url, timeout=30_000):
            hover_and_click(page, generate_buttons.nth(i), pause_ms=120)
        pace(page, 250)
    page.locator("text=Not generated").first.wait_for(state="detached", timeout=15_000)
    narrate(page, "every_document_current")

    # The export button only re-reads its readiness on load.
    page.reload()
    page.wait_for_load_state("networkidle")

    export_btn = page.get_by_role("button", name="Export compliance bundle")
    smooth_scroll(page, export_btn, 400)
    narrate(page, "export_compliance_bundle")
    with page.expect_response(lambda r: r.url.endswith("/export") and r.status == 201, timeout=60_000):
        hover_and_click(page, export_btn)
    page.wait_for_load_state("networkidle")
    pace(page, 900)

    complete_btn = page.get_by_role("button", name="Mark Assessment Complete")
    smooth_scroll(page, complete_btn, 400)
    narrate(page, "mark_assessment_complete")
    hover_and_click(page, complete_btn)
    page.wait_for_load_state("networkidle")
    pace(page, 1200)

    bundle = page.get_by_role("heading", name="Last Export Bundle")
    bundle.wait_for(state="visible", timeout=15_000)
    narrate(page, "bundle_lists_each")
    smooth_scroll(page, bundle, 600)

    # ── The public product page ───────────────────────────────────────────
    narrate(page, "product_s_public")
    page.goto(f"/public/product/{product.id}/")
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    vdp_link = page.get_by_role("link", name="Vulnerability disclosure policy")
    vdp_link.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, vdp_link, 600)

    narrate(page, "vulnerability_disclosure_policy")
    hover_and_click(page, vdp_link)
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 800)
    page.mouse.wheel(0, 600)
    settle(page)

    page.go_back()
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    doc_link = page.get_by_role("link", name="View declaration")
    smooth_scroll(page, doc_link, 400)
    narrate(page, "signed_eu_declaration")
    hover_and_click(page, doc_link)
    page.wait_for_load_state("networkidle")
    rewrite_localhost_urls(page)
    pace(page, 800)
    page.mouse.wheel(0, 900)
    pace(page, 800)
    narrate(page, "cra_scope_public")
