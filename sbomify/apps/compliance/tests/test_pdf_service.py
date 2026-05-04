"""Tests for the markdown→PDF service used by the CRA bundle export.

Covers:
  - ``markdown_to_pdf`` returns valid PDF bytes for normal markdown
  - The rendered PDF preserves embedded ``data:image/png;base64,``
    signatures (regression for CRA Annex V Section 8 — the auditor's
    PDF copy must show the signature, not just the markdown source)
  - ``markdown_to_pdf`` returns ``None`` when WeasyPrint is missing
    (graceful degradation for distroless/stripped runtimes)
  - ``markdown_to_pdf`` returns ``None`` when rendering raises
  - The bundle export ships a ``.pdf`` alongside every ``.md`` and
    skips PDF generation for non-markdown files (security.txt)
  - The bundle export still produces a valid ZIP when WeasyPrint
    can't render — the ``.md`` source is the regulatory artefact;
    the ``.pdf`` is a convenience rendering and its absence is benign
"""

from __future__ import annotations

import base64
import io
import zipfile
from unittest.mock import patch

import pytest

from sbomify.apps.compliance.services.document_generation_service import regenerate_all
from sbomify.apps.compliance.services.export_service import build_export_package
from sbomify.apps.compliance.services.pdf_service import markdown_to_pdf
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile

# Same 1×1 PNG used in test_doc_signature.py — the smallest valid
# image we can stuff into a ``data:image/png;base64,`` URL while
# still satisfying WeasyPrint's PNG-decoding pass.
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)
_TINY_PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(_TINY_PNG_BYTES).decode("ascii")


@pytest.fixture(autouse=True)
def _disable_billing(settings):
    """The CRA endpoints sit behind a Business-plan billing gate. Test
    teams don't have a subscription so disable the gate at the
    settings level — same pattern as ``test_doc_signature.py``."""
    settings.BILLING = False


class TestMarkdownToPdf:
    def test_returns_pdf_bytes_for_simple_markdown(self):
        pdf = markdown_to_pdf("# Hello\n\nA paragraph.", title="Smoke Test")
        assert pdf is not None
        # PDF magic bytes — a real PDF always starts with ``%PDF-``.
        # We do not parse the PDF here because pulling in a parser just
        # to assert structure adds a dependency for negligible value;
        # the magic-bytes + size sanity check is enough to catch the
        # "WeasyPrint silently returned an empty buffer" regression.
        assert pdf.startswith(b"%PDF-")
        assert len(pdf) > 500  # any non-empty document is well over 500 bytes

    def test_embeds_signature_data_url(self):
        """The DoC carries the manufacturer signature as a base64 PNG.
        WeasyPrint must accept the ``data:image/png;base64,`` URL —
        if it doesn't, the auditor's PDF will be unsigned even though
        the markdown source has the right ``![Signature](...)`` line.

        We assert the rendered PDF is large enough to imply the image
        bytes are present (PDFs without the embedded image come out
        ~2 KB; with it, several KB extra). Decoding the PDF stream to
        verify the exact image bytes would require a PDF parser and
        gives no extra signal — the regression we're guarding against
        is "WeasyPrint refused the data URL", which manifests as a
        thrown exception or a same-size output.
        """
        md_no_image = "# Sig Test\n\nSomething."
        md_with_image = f"# Sig Test\n\n![Signature]({_TINY_PNG_DATA_URL})"

        no_image = markdown_to_pdf(md_no_image, title="Sig Test")
        with_image = markdown_to_pdf(md_with_image, title="Sig Test")

        assert no_image is not None
        assert with_image is not None
        # The image-bearing PDF must be strictly larger — if WeasyPrint
        # silently dropped the data URL, the two outputs would be the
        # same size give-or-take a few timestamp bytes.
        assert len(with_image) > len(no_image)

    def test_returns_none_when_weasyprint_unavailable(self):
        """Simulate a runtime where WeasyPrint is not installed (e.g.
        distroless prod that never picked up the libpango .so files).
        The function must log + return ``None`` instead of raising —
        the bundle export depends on this contract to keep shipping
        the ``.md`` copy when the ``.pdf`` rendering can't run.
        """
        with patch.dict(
            "sys.modules",
            {"weasyprint": None},  # forces ImportError on ``from weasyprint import HTML``
        ):
            assert markdown_to_pdf("# Anything", title="x") is None

    def test_wrap_html_escapes_title_fully(self):
        """The previous title sanitization only escaped ``</`` so a
        title carrying ``<``, ``>``, or ``&`` would still escape into
        the ``<title>`` element. Run the wrapper directly and verify
        the escape covers all three."""
        from sbomify.apps.compliance.services.pdf_service import _wrap_html

        out = _wrap_html("<p>body</p>", title='Risky <script>"&" Title')
        # Raw ``<`` MUST NOT appear inside the ``<title>`` element.
        # We assert on the substring after ``<title>`` so the matcher
        # doesn't trip on ``<title>`` itself.
        title_open = out.index("<title>") + len("<title>")
        title_close = out.index("</title>")
        title_body = out[title_open:title_close]
        assert "<script>" not in title_body
        assert "&lt;script&gt;" in title_body
        assert "&amp;" in title_body

    def test_returns_none_when_render_raises(self):
        """A WeasyPrint runtime failure (broken font config, malformed
        HTML, OOM during layout) must not propagate — the caller
        relies on ``None`` to mean "skip the .pdf, keep the .md".
        """
        from sbomify.apps.compliance.services import pdf_service

        class _BrokenHTML:
            def __init__(self, *_, **__):
                raise RuntimeError("font config blew up")

        # Patch the symbol the function imports lazily inside its
        # try/except so the import succeeds but ``HTML(...)`` raises.
        with patch.object(pdf_service, "markdown_to_html", lambda _: "<p>x</p>"):
            with patch.dict("sys.modules", {"weasyprint": type("M", (), {"HTML": _BrokenHTML})}):
                assert markdown_to_pdf("# x", title="x") is None


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="PDF Test Product", team=team)


@pytest.fixture
def assessment_with_docs(sample_team_with_owner_member, sample_user, product):
    team = sample_team_with_owner_member.team
    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    ContactEntity.objects.create(
        profile=profile,
        name="PDF Acme Corp",
        email="info@pdf.test",
        address="1 PDF Way",
        is_manufacturer=True,
    )
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    with patch("sbomify.apps.core.object_store.S3Client"):
        regenerate_all(result.value)
    return result.value


@pytest.fixture
def capturing_s3():
    """Mirrors the helper in test_export_service: yields the captured
    upload bytes so the test can extract the ZIP and inspect it."""
    captured: dict[str, bytes] = {}

    class _Capture:
        def upload_data_as_file(self, bucket, key, data):
            captured["bytes"] = data

        def get_file_data(self, bucket, key):
            return b""

        def get_sbom_data(self, filename):
            return b""

    with patch("sbomify.apps.compliance.services.export_service.S3Client") as mock_s3_cls:
        mock_s3_cls.return_value = _Capture()
        yield captured


@pytest.mark.django_db
class TestDownloadDocumentPdfEndpoint:
    """Direct ``GET /api/v1/compliance/cra/<id>/documents/<kind>/download``
    coverage. Endpoint reuses ``markdown_to_pdf``; tests focus on the
    HTTP contract (status, Content-Type, attachment header, filename
    convention, 503 fallback when renderer is unavailable)."""

    def test_returns_pdf_with_attachment_disposition(
        self, sample_team_with_owner_member, sample_user
    ):
        from django.test import Client

        from sbomify.apps.compliance.services.document_generation_service import regenerate_all
        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.teams.models import ContactEntity, ContactProfile

        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="DL Acme",
            email="info@dl.test",
            address="1 DL Way",
            is_manufacturer=True,
        )
        product = Product.objects.create(name="Download Test", team=team)
        ares = get_or_create_assessment(product.id, sample_user, team)
        with patch("sbomify.apps.core.object_store.S3Client"):
            regenerate_all(ares.value)

        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team, sample_user)

        with patch("sbomify.apps.core.object_store.S3Client"):
            resp = client.get(
                f"/api/v1/compliance/cra/{ares.value.id}/documents/declaration_of_conformity/download"
            )

        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        disposition = resp["Content-Disposition"]
        assert disposition.startswith("attachment;")
        # Filename slug must match the bundle layout (kebab-case .pdf)
        # so a manually-downloaded copy lands in Downloads with the
        # same name an auditor sees inside the bundle ZIP.
        assert 'filename="declaration-of-conformity.pdf"' in disposition
        assert resp.content.startswith(b"%PDF-")

    def test_503_when_pdf_renderer_unavailable(
        self, sample_team_with_owner_member, sample_user
    ):
        """Distroless prod without Pango: ``markdown_to_pdf`` returns
        ``None`` and the endpoint must surface that as a 503 with a
        ``pdf_renderer_unavailable`` error_code so the client can fall
        back to the markdown preview without a confusing 500."""
        from django.test import Client

        from sbomify.apps.compliance.services.document_generation_service import regenerate_all
        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.teams.models import ContactEntity, ContactProfile

        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="DL Acme",
            email="info@dl.test",
            is_manufacturer=True,
        )
        product = Product.objects.create(name="Download 503", team=team)
        ares = get_or_create_assessment(product.id, sample_user, team)
        with patch("sbomify.apps.core.object_store.S3Client"):
            regenerate_all(ares.value)

        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team, sample_user)

        with patch("sbomify.apps.compliance.services.pdf_service.markdown_to_pdf", return_value=None):
            with patch("sbomify.apps.core.object_store.S3Client"):
                resp = client.get(
                    f"/api/v1/compliance/cra/{ares.value.id}/documents/declaration_of_conformity/download"
                )

        assert resp.status_code == 503
        body = resp.json()
        assert body["error_code"] == "pdf_renderer_unavailable"


@pytest.mark.django_db
class TestBundlePdfIntegration:
    """End-to-end coverage of the bundle's MD+PDF pairing."""

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_every_markdown_doc_has_sibling_pdf(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """For every ``.md`` in the manifest, the same path with a
        ``.pdf`` extension must also be present and hashed."""
        mock_get_content.return_value = b"# Test Document\n\nSome content."

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        files = result.value.manifest["files"]
        md_paths = {f["path"] for f in files if f["path"].endswith(".md")}
        pdf_paths = {f["path"] for f in files if f["path"].endswith(".pdf")}

        assert md_paths, "expected at least one .md in the manifest"
        for md in md_paths:
            sibling_pdf = md[: -len(".md")] + ".pdf"
            assert sibling_pdf in pdf_paths, (
                f"missing sibling PDF for {md!r} — bundle should ship both copies"
            )

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_security_txt_does_not_get_pdf_sibling(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """``security.txt`` is plain text per RFC 9116 — rendering it
        through markdown→PDF would produce a misleading artefact and
        falsely imply the file is a markdown document. Must be skipped.
        """
        mock_get_content.return_value = b"Contact: mailto:security@example.com\n"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        files = result.value.manifest["files"]
        paths = [f["path"] for f in files]
        assert any(p.endswith("/security.txt") for p in paths)
        assert not any(p.endswith("/security.pdf") for p in paths)

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_pdf_files_are_in_zip_and_well_formed(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """Open the ZIP and check the PDF entries are real PDFs."""
        mock_get_content.return_value = b"# Test\n\nBody."

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        with zipfile.ZipFile(io.BytesIO(capturing_s3["bytes"])) as zf:
            pdf_names = [n for n in zf.namelist() if n.endswith(".pdf")]
            assert pdf_names, "expected at least one .pdf inside the ZIP"
            for name in pdf_names:
                blob = zf.read(name)
                assert blob.startswith(b"%PDF-"), (
                    f"{name!r} is not a valid PDF — magic bytes missing"
                )

    @patch("sbomify.apps.compliance.services.export_service.markdown_to_pdf", return_value=None)
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_bundle_succeeds_when_pdf_renderer_unavailable(
        self, mock_get_content, mock_render, assessment_with_docs, sample_user, capturing_s3
    ):
        """Graceful degradation: when ``markdown_to_pdf`` returns
        ``None`` (WeasyPrint missing in distroless prod), the bundle
        export still ships every ``.md`` and the manifest is hash-
        verifiable. The ``.pdf`` rendering is a convenience, not a
        regulatory requirement."""
        mock_get_content.return_value = b"# Test\n\nBody."

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        files = result.value.manifest["files"]
        md_paths = [f["path"] for f in files if f["path"].endswith(".md")]
        pdf_paths = [f["path"] for f in files if f["path"].endswith(".pdf")]
        assert md_paths, "MD source must always ship — it's the regulatory artefact"
        assert not pdf_paths, "PDF rendering should be skipped when renderer unavailable"

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_pdf_manifest_entries_match_zip_bytes(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """Per-file SHA-256 in the manifest must match the actual PDF
        bytes inside the ZIP — same contract as for the .md entries.
        Without this, the documented ``jq … | sha256sum -c -`` workflow
        would print FAILED for every PDF entry."""
        import hashlib
        import re

        mock_get_content.return_value = b"# Hash check\n\nContent."

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        with zipfile.ZipFile(io.BytesIO(capturing_s3["bytes"])) as zf:
            prefix_re = re.compile(r"^cra-package-[^/]+/")
            for entry in result.value.manifest["files"]:
                if not entry["path"].endswith(".pdf"):
                    continue
                relative = prefix_re.sub("", entry["path"])
                actual = hashlib.sha256(zf.read(entry["path"])).hexdigest()
                assert entry["sha256"] == actual, (
                    f"manifest SHA for {relative!r} drifted from ZIP bytes"
                )
