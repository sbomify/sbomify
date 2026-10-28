"""Record the Trust Center gated access screencast.

Two people, one recording page. The browser context's session cookie is swapped
between them, so the video stays one continuous take:

1. **Visitor** (Dana, signed in, not a member). Trust Center → the gated SOC 2
   report → Request access → sign the workspace NDA → request pending.
2. **Admin** (the workspace owner). Settings → Trust Center tab → Access
   requests: the pending request with its NDA signature → Approve.
3. **Visitor** again: the report now reads Access granted.

Seeding: a public Trust Center with one public product, a public "Company NDA"
document wired as the workspace NDA, and a gated (approval plus NDA) SOC 2
Type II report. Documents live in a dict-backed S3, so the NDA preview renders
and the signature hashes the real stored bytes.
"""

from typing import Any
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from playwright.sync_api import BrowserContext, Page

from conftest import (
    hover_and_click,
    narrate,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    smooth_scroll,
    type_text,
)
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

WORKSPACE_NAME = "Pied Piper"
VISITOR_NAME = "Dana Whitfield"
VISITOR_EMAIL = "dana.whitfield@example.com"
REPORT_COMPONENT = "SOC 2 Type II Report"

NDA_TEXT = """MUTUAL NON-DISCLOSURE AGREEMENT

Between Pied Piper, Inc. ("Pied Piper") and the person signing below ("Recipient").

1. Confidential Information. Any report, audit result or security document
   Pied Piper shares through its Trust Center is Confidential Information.

2. Use. Recipient uses Confidential Information only to evaluate Pied Piper
   as a supplier, and shares it only with colleagues who need it for that.

3. Protection. Recipient protects Confidential Information with at least the
   care it uses for its own, and never less than reasonable care.

4. Term. These obligations last three years from the date of signature.

5. Return. On request, Recipient deletes or returns all Confidential
   Information and any copies.

Signed electronically through the Pied Piper Trust Center.
"""

SOC2_TEXT = "Pied Piper, Inc. SOC 2 Type II report. Confidential, shared under NDA.\n"


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[tuple[str, str], bytes] = {}

    def _put(self: StorageClient, bucket_name: str, object_name: str, data: bytes) -> None:
        store[(bucket_name, object_name)] = data

    def _get(self: StorageClient, bucket_name: str, object_name: str) -> bytes | None:
        return store.get((bucket_name, object_name))

    monkeypatch.setattr(StorageClient, "upload_data_as_file", _put)
    monkeypatch.setattr(StorageClient, "get_file_data", _get)


def _document(component: Component, name: str, body: str, doc_type: str, subcategory: str | None = None) -> Document:
    data = body.encode()
    filename = StorageClient("DOCUMENTS").upload_document(data)
    return Document.objects.create(
        name=name,
        version="2026",
        document_filename=filename,
        component=component,
        source="manual_upload",
        content_type="text/plain",
        file_size=len(data),
        document_type=doc_type,
        compliance_subcategory=subcategory,
    )


@pytest.fixture
def gated_trust_center(pied_piper_product: dict, sample_user: Any, fake_s3: None) -> dict:
    team: Team = pied_piper_product["product"].team
    team.name = WORKSPACE_NAME
    team.is_public = True
    team.save(update_fields=["name", "is_public"])
    sample_user.first_name = "Richard"
    sample_user.last_name = "Hendricks"
    sample_user.save(update_fields=["first_name", "last_name"])

    product = pied_piper_product["product"]
    product.is_public = True
    product.save(update_fields=["is_public"])
    Component.objects.filter(pk__in=[c.pk for c in pied_piper_product["components"].values()]).update(
        visibility=Component.Visibility.PUBLIC
    )

    nda_component = Component.objects.create(
        team=team,
        name="Company NDA",
        component_type=Component.ComponentType.DOCUMENT,
        is_global=True,
        visibility=Component.Visibility.PUBLIC,
    )
    nda = _document(nda_component, "Pied Piper Mutual NDA", NDA_TEXT, Document.DocumentType.NDA)
    team.branding_info = {**(team.branding_info or {}), "company_nda_document_id": nda.id}
    team.save(update_fields=["branding_info"])

    report = Component.objects.create(
        team=team,
        name=REPORT_COMPONENT,
        component_type=Component.ComponentType.DOCUMENT,
        is_global=True,
        visibility=Component.Visibility.GATED,
        gating_mode=Component.GatingMode.APPROVAL_PLUS_NDA,
    )
    _document(
        report,
        "SOC 2 Type II Report 2026",
        SOC2_TEXT,
        Document.DocumentType.COMPLIANCE,
        Document.ComplianceSubcategory.SOC2_TYPE2,
    )

    visitor = get_user_model().objects.create_user(
        username="dana.whitfield",
        email=VISITOR_EMAIL,
        password="unused-in-screencast",  # nosec B106
        first_name="Dana",
        last_name="Whitfield",
    )
    return {"team": team, "report": report, "visitor": visitor}


def _session_cookie(browser_base_url: str, session_key: str) -> dict[str, Any]:
    return {
        "name": "sessionid",
        "value": session_key,
        "domain": urlparse(browser_base_url).hostname,
        "path": "/",
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }


def _visitor_cookie(browser_base_url: str, visitor: Any) -> dict[str, Any]:
    client = Client()
    client.force_login(visitor)
    return _session_cookie(browser_base_url, client.session.session_key)


def _switch_session(context: BrowserContext, cookie: dict[str, Any]) -> None:
    context.clear_cookies()
    context.add_cookies([cookie])


@pytest.mark.django_db(transaction=True)
def access_requests(
    gated_trust_center: dict,
    recording_context: BrowserContext,
    recording_page: Page,
    browser_base_url: str,
) -> None:
    page = recording_page
    context = recording_context
    team = gated_trust_center["team"]
    report = gated_trust_center["report"]

    admin_cookie = next(c for c in context.cookies() if c["name"] == "sessionid")
    visitor_cookie = _visitor_cookie(browser_base_url, gated_trust_center["visitor"])

    trust_center_url = reverse("core:workspace_public", kwargs={"workspace_key": team.key})
    report_url = reverse("core:component_details_public", kwargs={"component_id": report.id})

    # ── 1. The visitor asks for access ───────────────────────────────────
    _switch_session(context, visitor_cookie)
    page.goto(trust_center_url)
    page.wait_for_load_state("networkidle")
    pace(page, 800)
    narrate(page, "intro")
    settle(page)
    narrate(page, "first_visitor_s")
    settle(page)
    credential = page.locator(f"a[href*='{report.id}']").first
    smooth_scroll(page, credential, 300)
    hover_and_click(page, credential)
    page.wait_for_load_state("networkidle")
    request_btn = page.get_by_role("link", name="Request Access")
    request_btn.wait_for(state="visible", timeout=15_000)
    pace(page, 600)
    narrate(page, "report_gated_dana")
    settle(page)
    hover_and_click(page, request_btn)
    page.wait_for_load_state("networkidle")

    submit = page.get_by_role("button", name="Request access")
    submit.wait_for(state="visible", timeout=15_000)
    pace(page, 600)
    narrate(page, "workspace_asks_nda")
    settle(page)
    hover_and_click(page, submit)
    page.wait_for_load_state("networkidle")

    name_input = page.locator("#signed_name")
    name_input.wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    narrate(page, "dana_reads_nda")
    hover_and_click(page, name_input)
    type_text(name_input, VISITOR_NAME, delay=70)
    pace(page, 400)
    hover_and_click(page, page.locator("#consent"))
    pace(page, 600)
    narrate(page, "sbomify_records_signature")
    settle(page)
    hover_and_click(page, page.get_by_role("button", name="Sign NDA and submit request"))
    page.wait_for_load_state("networkidle")
    pace(page, 1500)
    narrate(page, "request_waits_workspace")
    settle(page)

    # ── 2. The admin approves it ─────────────────────────────────────────
    _switch_session(context, admin_cookie)
    page.goto("/dashboard")
    page.wait_for_load_state("networkidle")
    pace(page, 600)
    narrate(page, "admin_s_side")
    settle(page)
    navigate_to_settings(page)
    navigate_to_settings_tab(page, "trust-center")

    wrapper = page.locator("#access-requests-wrapper")
    row = wrapper.locator("tr", has_text=VISITOR_EMAIL)
    row.wait_for(state="visible", timeout=15_000)
    smooth_scroll(page, row, 800)
    narrate(page, "access_requests_trust")
    settle(page)

    hover_and_click(page, row.get_by_role("button", name="Request actions"))
    pace(page, 500)
    narrate(page, "approve_request")
    with page.expect_response(lambda r: "access-requests" in r.url and r.request.method == "POST"):
        hover_and_click(page, page.get_by_role("menuitem", name="Approve"))
    approved = wrapper.locator("tr", has_text=VISITOR_EMAIL)
    approved.wait_for(state="visible", timeout=15_000)
    page.get_by_text("Approved requests").wait_for(state="visible", timeout=10_000)
    smooth_scroll(page, approved, 800)
    narrate(page, "dana_moves_approved")
    settle(page)

    # ── 3. The visitor has access ────────────────────────────────────────
    _switch_session(context, visitor_cookie)
    page.goto(report_url)
    page.wait_for_load_state("networkidle")
    page.get_by_text("Access Granted").wait_for(state="visible", timeout=15_000)
    pace(page, 800)
    narrate(page, "back_trust_center")
    settle(page)
    pace(page, 800)
