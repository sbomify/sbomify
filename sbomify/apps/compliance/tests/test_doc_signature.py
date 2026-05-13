"""Tests for the manufacturer signature flow on the CRA DoC.

Covers:
  - ``CRAAssessment.is_signed`` property
  - ``GET /api/v1/compliance/cra/<id>/signature`` returns current state
  - ``PUT /api/v1/compliance/cra/<id>/signature`` validates payload,
    persists fields, sets signed_at + signed_by, and marks the
    existing DoC ``CRAGeneratedDocument`` as stale
  - DoC template renders filled signature when present and falls
    back to underscore placeholders when not
  - Markdown image renderer accepts the signature data URL and
    rejects javascript: schemes
"""

from __future__ import annotations

import base64
import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAGeneratedDocument,
    CRAScopeScreening,
    OSCALAssessmentResult,
    OSCALCatalog,
)
from sbomify.apps.core.models import Product
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

pytestmark = pytest.mark.django_db


# A valid 1x1 PNG — small enough to fit comfortably under the API cap
# and big enough to satisfy the data-URL prefix check.
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)
_TINY_PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(_TINY_PNG_BYTES).decode("ascii")


@pytest.fixture(autouse=True)
def _disable_billing(settings):
    settings.BILLING = False


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Sig Test Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, product):
    team = sample_team_with_owner_member.team
    CRAScopeScreening.objects.create(product=product, team=team, has_data_connection=True)
    catalog = OSCALCatalog.objects.create(
        name="BSI TR-03183-1",
        version="1.0",
        catalog_json={"metadata": {"title": "stub"}},
    )
    oscal_result = OSCALAssessmentResult.objects.create(catalog=catalog, team=team, title="Sig Test")
    return CRAAssessment.objects.create(
        team=team,
        product=product,
        oscal_assessment_result=oscal_result,
        status=CRAAssessment.WizardStatus.IN_PROGRESS,
    )


@pytest.fixture
def web_client(sample_team_with_owner_member, sample_user):
    client = Client()
    client.force_login(sample_user)
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
    return client


def _put(client: Client, assessment_id: str, payload: dict) -> tuple[int, dict]:
    resp = client.put(
        f"/api/v1/compliance/cra/{assessment_id}/signature",
        data=json.dumps(payload),
        content_type="application/json",
    )
    body = resp.json() if resp["Content-Type"].startswith("application/json") else {}
    return resp.status_code, body


class TestSignatureProperty:
    def test_is_signed_false_until_all_fields_present(self, assessment):
        assert not assessment.is_signed
        assessment.signature_place = "Berlin"
        assessment.signature_name = "Rana"
        assessment.signature_function = "Maintainer"
        # Image still empty
        assert not assessment.is_signed
        assessment.signature_image = _TINY_PNG_DATA_URL
        assert assessment.is_signed

    def test_is_signed_rejects_whitespace_only_text(self, assessment):
        """If a field gets populated outside the API (admin shell,
        manual SQL, future migration) with whitespace only, the
        property must NOT report the assessment as signed — otherwise
        the DoC template would render with a blank place/name/etc."""
        assessment.signature_place = "   "
        assessment.signature_name = "Rana"
        assessment.signature_function = "Maintainer"
        assessment.signature_image = _TINY_PNG_DATA_URL
        assert not assessment.is_signed

    def test_is_signed_rejects_image_prefix_with_no_payload(self, assessment):
        """Image string starting with the data-URL prefix but carrying
        no base64 payload (a stub) must NOT count as signed. Mirrors
        the API-layer rejection."""
        assessment.signature_place = "Berlin"
        assessment.signature_name = "Rana"
        assessment.signature_function = "Maintainer"
        assessment.signature_image = "data:image/png;base64,"
        assert not assessment.is_signed


class TestSignatureGet:
    def test_unsigned_returns_empty_strings(self, assessment, web_client):
        resp = web_client.get(f"/api/v1/compliance/cra/{assessment.id}/signature")
        assert resp.status_code == 200
        body = resp.json()
        assert body["place"] == ""
        assert body["is_signed"] is False
        assert body["signed_at"] is None


class TestSignaturePut:
    def test_happy_path_persists_and_marks_doc_stale(self, assessment, sample_user, web_client):
        # Existing DoC document for this assessment — should flip to stale.
        doc = CRAGeneratedDocument.objects.create(
            assessment=assessment,
            document_kind=CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY,
            storage_key=f"compliance/{assessment.id}/declaration_of_conformity.md",
            content_hash="0" * 64,
            is_stale=False,
        )

        status, body = _put(
            web_client,
            assessment.id,
            {
                "place": "Berlin, Germany",
                "name": "Rana Aurangzaib",
                "function": "Lead Maintainer",
                "image": _TINY_PNG_DATA_URL,
            },
        )
        assert status == 200, body
        assert body["is_signed"] is True
        assert body["signed_at"] is not None

        assessment.refresh_from_db()
        assert assessment.signature_place == "Berlin, Germany"
        assert assessment.signature_name == "Rana Aurangzaib"
        assert assessment.signature_function == "Lead Maintainer"
        assert assessment.signature_image == _TINY_PNG_DATA_URL
        assert assessment.signed_at is not None
        assert assessment.signed_by_id == sample_user.id

        doc.refresh_from_db()
        assert doc.is_stale is True

    def test_rejects_blank_text_field(self, assessment, web_client):
        status, body = _put(
            web_client,
            assessment.id,
            {"place": "  ", "name": "Rana", "function": "Maintainer", "image": _TINY_PNG_DATA_URL},
        )
        assert status == 400
        assert body["error_code"] == "signature_incomplete"

    def test_rejects_overlong_text_field(self, assessment, web_client):
        status, body = _put(
            web_client,
            assessment.id,
            {
                "place": "x" * 256,
                "name": "Rana",
                "function": "Maintainer",
                "image": _TINY_PNG_DATA_URL,
            },
        )
        assert status == 400
        assert body["error_code"] == "signature_field_too_long"

    def test_rejects_non_png_data_url(self, assessment, web_client):
        status, body = _put(
            web_client,
            assessment.id,
            {
                "place": "Berlin",
                "name": "Rana",
                "function": "Maintainer",
                "image": "javascript:alert(1)",
            },
        )
        assert status == 400
        assert body["error_code"] == "signature_invalid_image"

    def test_rejects_oversized_image(self, assessment, web_client):
        # Build a PNG-prefixed payload whose *decoded* size exceeds the
        # 64 KB cap. The previous form padded the base64 string with
        # ``A`` only, which now fails the earlier PNG-magic check
        # before the size cap fires; constructing real PNG-magic-prefixed
        # bytes exercises the size-cap branch we actually care about.
        big_bytes = _TINY_PNG_BYTES + b"\x00" * (70 * 1024)
        big = "data:image/png;base64," + base64.b64encode(big_bytes).decode("ascii")
        status, body = _put(
            web_client,
            assessment.id,
            {"place": "Berlin", "name": "Rana", "function": "Maintainer", "image": big},
        )
        assert status == 400
        assert body["error_code"] == "signature_image_too_large"

    def test_rejects_empty_base64_payload(self, assessment, web_client):
        """A bare prefix with no base64 body must be rejected — the
        previous validation accepted it because the string still
        ``startswith`` the prefix."""
        status, body = _put(
            web_client,
            assessment.id,
            {
                "place": "Berlin",
                "name": "Rana",
                "function": "Maintainer",
                "image": "data:image/png;base64,",
            },
        )
        assert status == 400
        assert body["error_code"] == "signature_invalid_image"

    def test_rejects_invalid_base64(self, assessment, web_client):
        """Bytes that look like base64 but contain illegal characters
        (e.g. control bytes from a corrupted upload) must be rejected
        before the PNG-magic check."""
        status, body = _put(
            web_client,
            assessment.id,
            {
                "place": "Berlin",
                "name": "Rana",
                "function": "Maintainer",
                "image": "data:image/png;base64,!!!not-base64!!!",
            },
        )
        assert status == 400
        assert body["error_code"] == "signature_invalid_image"

    def test_rejects_non_png_bytes(self, assessment, web_client):
        """Valid base64 of arbitrary bytes (e.g. JPEG, HTML, plain
        text) must be rejected. Without the PNG-magic check the DoC
        renderer / WeasyPrint would later trip on the wrong format."""
        # ``Hello, world!`` is plainly not a PNG.
        not_png = base64.b64encode(b"Hello, world!").decode("ascii")
        status, body = _put(
            web_client,
            assessment.id,
            {
                "place": "Berlin",
                "name": "Rana",
                "function": "Maintainer",
                "image": "data:image/png;base64," + not_png,
            },
        )
        assert status == 400
        assert body["error_code"] == "signature_invalid_image"


class TestDoCTemplateSignatureBlock:
    def test_renders_underscores_when_unsigned(self, assessment):
        from sbomify.apps.compliance.services.document_generation_service import get_document_preview

        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)

        assert result.ok
        text = result.value or ""
        # Underscores remain — none of the four fields were captured.
        assert "**Place:** _______________" in text
        assert "**Name:** _______________" in text
        assert "**Function:** _______________" in text
        assert "**Signature:** _______________" in text

    def test_renders_filled_block_when_signed(self, assessment):
        from sbomify.apps.compliance.services.document_generation_service import get_document_preview

        assessment.signature_place = "Berlin, Germany"
        assessment.signature_name = "Rana Aurangzaib"
        assessment.signature_function = "Lead Maintainer"
        assessment.signature_image = _TINY_PNG_DATA_URL
        assessment.save()

        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)

        assert result.ok
        text = result.value or ""
        assert "**Place:** Berlin, Germany" in text
        assert "**Name:** Rana Aurangzaib" in text
        assert "**Function:** Lead Maintainer" in text
        # The signature line emits a Markdown image (rendered into <img>
        # by the public reader) rather than an underscore placeholder.
        assert f"![Signature]({_TINY_PNG_DATA_URL})" in text
        assert "**Signature:** _______________" not in text


class TestImageRendering:
    def test_signature_data_url_renders_as_img(self):
        from sbomify.apps.compliance.views._public_helpers import inline_markup

        out = inline_markup(f"![Signature]({_TINY_PNG_DATA_URL})")
        assert '<img src="data:image/png;base64,' in out
        assert 'alt="Signature"' in out

    def test_javascript_image_url_is_rejected(self):
        from sbomify.apps.compliance.views._public_helpers import inline_markup

        out = inline_markup("![evil](javascript:alert(1))")
        assert "<img" not in out
        assert "javascript:" not in out

    def test_http_image_url_renders(self):
        from sbomify.apps.compliance.views._public_helpers import inline_markup

        out = inline_markup("![logo](https://example.com/logo.png)")
        assert '<img src="https://example.com/logo.png"' in out

    def test_alt_and_link_text_are_html_escaped(self):
        """Direct callers (tests, future helpers) might pass un-escaped
        markdown into ``inline_markup`` — defensively HTML-escape the
        alt/link text and the URL inside ``<img>`` / ``<a>`` so a
        literal ``"`` or ``>`` can't break out of the attribute / tag
        even when the caller skipped the outer ``html.escape`` pass."""
        from sbomify.apps.compliance.views._public_helpers import inline_markup

        out = inline_markup('[click "me" >](https://example.com)')
        # Must NOT carry a raw ``"`` inside the link text (would break
        # the attribute) or a raw ``>`` (would close the opening tag).
        assert 'click "me"' not in out
        assert "click &quot;me&quot;" in out
        assert "&gt;" in out

        # Same for image alt: ``"alt with quote"`` must be escaped.
        img = inline_markup('![alt "x"](https://example.com/x.png)')
        assert 'alt with raw "' not in img
        assert "&quot;" in img
