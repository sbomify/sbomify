"""Tests for the CRA export service — ZIP packaging."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.compliance.models import CRAExportPackage
from sbomify.apps.compliance.services._manufacturer_policy import (
    is_placeholder_manufacturer as _is_placeholder_manufacturer,
)
from sbomify.apps.compliance.services.document_generation_service import regenerate_all
from sbomify.apps.compliance.services.export_service import (
    _article_14_reporting_readme,
    _get_generated_doc_content,
    _get_sbom_content,
    _integrity_readme,
    build_export_package,
    get_download_url,
)
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Export Test Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product):
    team = sample_team_with_owner_member.team

    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Acme Corp",
        email="info@acme.test",
        address="123 Test St",
        is_manufacturer=True,
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Security Lead",
        email="security@acme.test",
        is_security_contact=True,
    )

    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.fixture
def assessment_with_docs(assessment):
    """Assessment with all documents generated.

    Function-scoped because ``assessment`` itself is function-scoped
    (the CRA wizard creates a fresh OSCALAssessmentResult + 21
    findings per test). Upgrading to class/module scope would require
    re-working the wizard fixture to cache the OSCAL rows — tracked as
    a follow-up. Today's overhead is ~9 mocked S3 writes per test
    that uses this fixture; with ``S3Client`` patched at the import
    site, each ``generate_document`` short-circuits at the upload and
    the total cost is bounded to ORM work."""
    with patch("sbomify.apps.core.object_store.S3Client"):
        regenerate_all(assessment)
    return assessment


@pytest.fixture
def capturing_s3():
    """Zero-boilerplate S3 stub that captures bytes uploaded by
    ``build_export_package``.

    Replaces the 4× inlined ``class _Capture`` dance that preceded
    it — yields ``(captured, s3_cls_mock)`` where ``captured["bytes"]``
    holds the last ZIP uploaded and ``s3_cls_mock`` is the patched
    ``S3Client`` class (so tests that also need to mock doc fetches
    can patch on top). Request-scoped to the test, so every use gets
    a fresh captured dict.
    """
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
        yield captured, mock_s3_cls


@pytest.mark.django_db
class TestBuildExportPackage:
    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_creates_package_record(self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user):
        mock_get_content.return_value = b"mock document content"

        result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok
        package = result.value
        assert isinstance(package, CRAExportPackage)
        assert package.content_hash
        assert package.manifest is not None
        assert package.manifest["cra_regulation"] == "EU 2024/2847"
        assert package.manifest["product"]["name"] == "Export Test Product"
        assert package.manifest["manufacturer"]["name"] == "Acme Corp"

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_manifest_contains_file_entries(self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user):
        mock_get_content.return_value = b"mock document content"

        result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok
        files = result.value.manifest["files"]
        paths = [f["path"] for f in files]

        # OSCAL files always present
        assert any("oscal/catalog.json" in p for p in paths)
        assert any("oscal/assessment-results.json" in p for p in paths)
        # Manifest is NOT included in its own files list to avoid
        # inconsistency between the DB manifest and the in-ZIP manifest.
        assert not any("metadata/manifest.json" in p for p in paths)

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_manifest_files_have_sha256(self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user):
        mock_get_content.return_value = b"mock document content"

        result = build_export_package(assessment_with_docs, sample_user)

        # Assert every entry carries a *valid* 64-char lowercase hex
        # digest, not just a 64-char string. A previous weaker form
        # (``len(...) == 64``) would have passed for "a" * 64.
        import re as _re

        _hex64 = _re.compile(r"^[0-9a-f]{64}$")
        for file_entry in result.value.manifest["files"]:
            assert "sha256" in file_entry
            assert _hex64.match(file_entry["sha256"]), (
                f"sha256 field is not 64-char lowercase hex: {file_entry['sha256']!r}"
            )

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_oscal_catalog_in_package(self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user):
        """OSCAL catalog JSON should be included in the package."""
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        # Verify catalog is referenced in manifest
        files = result.value.manifest["files"]
        catalog_entries = [f for f in files if "catalog.json" in f["path"]]
        assert len(catalog_entries) == 1

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_product_category_in_manifest(self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user):
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.value.manifest["product_category"] == "default"
        assert result.value.manifest["conformity_procedure"] == "module_a"

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_bundle_contains_harmonised_standards_reference(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """The bundle must embed the harmonised-standards mapping so
        downstream auditors don't need to chase it in the sbomify repo."""
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        paths = [f["path"] for f in result.value.manifest["files"]]
        assert any("metadata/harmonised-standards.json" in p for p in paths)

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_bundle_contains_article_14_reporting_readme(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """README documents the 2026-09-11 deadline + SRP submission
        channel so operators don't misread Article 14 obligations."""
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        paths = [f["path"] for f in result.value.manifest["files"]]
        assert any("article-14/README_REPORTING.md" in p for p in paths)

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_manifest_declares_integrity_metadata(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """Manifest self-describes its integrity regime: hash algorithm
        plus the paths of manifest.sha256 and INTEGRITY.md."""
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        integrity = result.value.manifest.get("integrity")
        assert integrity is not None
        assert integrity["hash_algorithm"] == "sha256"
        assert integrity["manifest_hash_file"] == "metadata/manifest.sha256"
        assert integrity["verification_doc"] == "metadata/INTEGRITY.md"

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_bundle_contains_manifest_self_hash_and_integrity_doc(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """ZIP must physically carry ``manifest.sha256`` and
        ``INTEGRITY.md`` — verified by extracting the uploaded bytes."""
        import hashlib
        import io
        import zipfile

        captured, _ = capturing_s3
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok
        assert "bytes" in captured, "S3 upload was not invoked"

        with zipfile.ZipFile(io.BytesIO(captured["bytes"])) as zf:
            names = zf.namelist()
            assert any(n.endswith("metadata/manifest.sha256") for n in names)
            assert any(n.endswith("metadata/INTEGRITY.md") for n in names)
            manifest_name = next(n for n in names if n.endswith("metadata/manifest.json"))
            sha_name = next(n for n in names if n.endswith("metadata/manifest.sha256"))

            expected = hashlib.sha256(zf.read(manifest_name)).hexdigest()
            assert expected in zf.read(sha_name).decode("utf-8")

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_bundle_survives_missing_harmonised_standards_file(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """If the bundled reference JSON somehow vanishes at runtime
        (broken install, packaging bug) the export must still produce
        a valid bundle — the reader returns None, we log, and the
        embedded reference copy is simply omitted from the ZIP."""
        mock_get_content.return_value = b"mock content"

        # Patch the shared reader used by export_service to simulate
        # a missing / unreadable shipped JSON. The path itself moved
        # into ``services._reference_data`` in the centralisation pass,
        # so this is the correct seam for the "missing file" scenario.
        with patch(
            "sbomify.apps.compliance.services.export_service.read_harmonised_standards_bytes",
            return_value=None,
        ):
            result = build_export_package(assessment_with_docs, sample_user)

        assert result.ok
        paths = [f["path"] for f in result.value.manifest["files"]]
        assert not any("harmonised-standards.json" in p for p in paths)
        # Article 14 + integrity files still present — demonstrating
        # graceful degradation rather than all-or-nothing export.
        assert any("README_REPORTING.md" in p for p in paths)

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_manifest_format_version_bump(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """Manifest format bumped to 1.2 when the per-document PDF
        rendering shipped — downstream consumers that pin on the version
        can decide whether to expect a sibling ``.pdf`` next to each
        ``.md`` in the manifest's files array."""
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.value.manifest["format_version"] == "1.2"

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_manifest_sha256_round_trips_through_shasum(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """Regression: ``sha256sum -c metadata/manifest.sha256`` run from
        the extracted bundle root MUST verify ``metadata/manifest.json``."""
        import hashlib
        import io
        import zipfile

        captured, _ = capturing_s3
        mock_get_content.return_value = b"mock content"
        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        with zipfile.ZipFile(io.BytesIO(captured["bytes"])) as zf:
            manifest_name = next(n for n in zf.namelist() if n.endswith("metadata/manifest.json"))
            sha_name = next(n for n in zf.namelist() if n.endswith("metadata/manifest.sha256"))
            manifest_bytes = zf.read(manifest_name)
            sha_line = zf.read(sha_name).decode().strip()
            expected_hash = hashlib.sha256(manifest_bytes).hexdigest()

            # Line format: "<sha>  <relative-path>"
            recorded_hash, recorded_path = sha_line.split("  ", 1)
            assert recorded_hash == expected_hash
            # Path must be resolvable from the extracted bundle root —
            # i.e. "metadata/manifest.json". Anything else (plain
            # "manifest.json", absolute path, missing directory) breaks
            # the documented `sha256sum -c metadata/manifest.sha256`
            # command when invoked from the bundle root.
            assert recorded_path == "metadata/manifest.json"

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_per_file_manifest_entries_verify_against_actual_zip_contents(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """Regression for the INTEGRITY.md ``jq … | sha256sum -c -``
        workflow: after stripping the ``cra-package-<slug>/`` prefix,
        each manifest entry's hash must match the ZIP's bytes for that
        relative path. This exercises the exact workflow the README
        tells operators to run — not an approximation."""
        import hashlib
        import io
        import re
        import zipfile

        captured, _ = capturing_s3
        mock_get_content.return_value = b"mock payload"
        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        with zipfile.ZipFile(io.BytesIO(captured["bytes"])) as zf:
            prefix_re = re.compile(r"^cra-package-[^/]+/")
            for entry in result.value.manifest["files"]:
                recorded = entry["sha256"]
                full_path = entry["path"]
                relative = prefix_re.sub("", full_path)
                actual = hashlib.sha256(zf.read(full_path)).hexdigest()
                assert recorded == actual, (
                    f"manifest entry for {relative!r} declares "
                    f"{recorded}, but the ZIP bytes hash to {actual}"
                )

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_integrity_readme_cites_the_expected_hash(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """INTEGRITY.md cites the manifest SHA-256 verbatim, so a
        diligent auditor can cross-check the value declared in the
        README against the value in manifest.sha256."""
        import io
        import zipfile

        captured, _ = capturing_s3
        mock_get_content.return_value = b"mock content"
        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        with zipfile.ZipFile(io.BytesIO(captured["bytes"])) as zf:
            readme_name = next(n for n in zf.namelist() if n.endswith("metadata/INTEGRITY.md"))
            sha_name = next(n for n in zf.namelist() if n.endswith("metadata/manifest.sha256"))
            readme = zf.read(readme_name).decode()
            declared = zf.read(sha_name).decode().split()[0]
            assert declared in readme, "INTEGRITY.md must echo the SHA from manifest.sha256"
            assert "sha256sum -c metadata/manifest.sha256" in readme
            assert "cosign" in readme  # signing guidance reference

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_article_14_readme_cites_deadline_and_srp_url(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """Readme carries the 2026-09-11 deadline + the EC reporting
        portal URL verbatim so operators can't miss either."""
        import io
        import zipfile

        captured, _ = capturing_s3
        mock_get_content.return_value = b"mock content"
        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        with zipfile.ZipFile(io.BytesIO(captured["bytes"])) as zf:
            name = next(n for n in zf.namelist() if n.endswith("article-14/README_REPORTING.md"))
            content = zf.read(name).decode()
            assert "2026-09-11" in content
            assert "ENISA" in content
            assert "Article 14" in content
            assert "digital-strategy.ec.europa.eu/en/policies/cra-reporting" in content
            # Deadlines table — all four rows present.
            for deadline in ("≤24 h", "≤72 h", "≤14 d", "≤1 mo"):
                assert deadline in content

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_bundle_skips_unknown_doc_kind(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """A CRAGeneratedDocument with an unmapped kind (forward-compat
        ingestion of newer DB rows) must be silently skipped, not
        crash the export."""
        from sbomify.apps.compliance.models import CRAGeneratedDocument

        # Inject a doc with a kind the export map doesn't know.
        CRAGeneratedDocument.objects.create(
            assessment=assessment_with_docs,
            document_kind="unknown_future_kind",
            storage_key="compliance/whatever.md",
            content_hash="a" * 64,
            version=1,
            is_stale=False,
        )
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok
        paths = [f["path"] for f in result.value.manifest["files"]]
        assert not any("unknown_future_kind" in p for p in paths)

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_get_generated_doc_returning_none_does_not_break_bundle(
        self, mock_get_content, mock_s3_cls, assessment_with_docs, sample_user
    ):
        """Fetch failures from S3 (network blip, missing object) must
        not fail the whole export — the document is simply omitted
        from the manifest."""
        # Simulate all documents failing to fetch.
        mock_get_content.return_value = None

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok
        # No document files in manifest, but OSCAL + integrity + Article 14
        # README + harmonised-standards are still present.
        paths = [f["path"] for f in result.value.manifest["files"]]
        assert any("oscal/catalog.json" in p for p in paths)
        assert any("harmonised-standards.json" in p for p in paths)
        assert not any("vulnerability-disclosure-policy.md" in p for p in paths)

    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_sbom_packaged_with_annex_vii_reference(
        self, mock_get_content, assessment_with_docs, sample_user, capturing_s3
    ):
        """End-to-end: a real ``Product → Project → Component → SBOM``
        chain produces an SBOM file in the ZIP, a manifest entry with
        ``cra_reference`` "Annex VII, §2", and the ``{slug}-{id}.cdx.json``
        naming convention (covers the export_service branch that runs
        the ``SBOM.objects`` join, the ``_FORMAT_EXT_MAP`` extension
        pick, and the ``Annex VII, §2`` literal)."""
        import io
        import zipfile

        from sbomify.apps.core.models import Component, Project
        from sbomify.apps.sboms.models import SBOM

        product = assessment_with_docs.product
        team = assessment_with_docs.team

        # Hang a Component off the Product via a Project. The export
        # service discovers SBOMs via ``components__projects__products``.
        project = Project.objects.create(name="CRA Export Project", team=team)
        component = Component.objects.create(name="Export Test Component", team=team)
        project.components.add(component)
        product.projects.add(project)

        # Give the component an SBOM that the export will find. The
        # export service only wires the SBOM *path* into the ZIP; it
        # does not re-read the actual bytes from storage during this
        # test, so capturing_s3's stub get_sbom_data returning b""
        # is enough for the manifest + path assertions below.
        SBOM.objects.create(
            name="export-test-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.6",
            version="1.0.0",
            sbom_filename="export-test-sbom.cdx.json",
        )

        captured, _ = capturing_s3
        # Return non-empty bytes so the write-to-zip branch fires.
        # capturing_s3's get_sbom_data returns b"" by default which
        # short-circuits the branch; patch it on the stub for this test.
        captured_s3_instance = capturing_s3[1].return_value
        captured_s3_instance.get_sbom_data = lambda filename: b'{"bomFormat":"CycloneDX"}'
        mock_get_content.return_value = b"mock content"

        result = build_export_package(assessment_with_docs, sample_user)
        assert result.ok

        # Manifest entry assertions — lines 258-266 of export_service.
        sbom_entries = [
            f for f in result.value.manifest["files"]
            if "/sboms/" in f["path"] and f["path"].endswith(".cdx.json")
        ]
        assert len(sbom_entries) == 1, f"expected exactly one SBOM entry, got {sbom_entries}"
        entry = sbom_entries[0]
        assert entry["cra_reference"] == "Annex VII, §2", (
            f"SBOM must be tagged Annex VII, §2 — got {entry['cra_reference']!r}"
        )
        # Naming convention: cra-package-<slug>/sboms/<comp-slug>-<comp-id>.cdx.json
        assert entry["path"].endswith(f"{component.id}.cdx.json"), entry["path"]
        assert "export-test-component" in entry["path"]

        # And the ZIP actually carries the file at that path.
        with zipfile.ZipFile(io.BytesIO(captured["bytes"])) as zf:
            assert entry["path"] in zf.namelist()

    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_manifest_flags_placeholder_manufacturer(
        self, mock_get_content, mock_s3_cls, sample_team_with_owner_member, sample_user
    ):
        """Manifest surface carries ``is_placeholder`` so a downstream
        consumer (notified body, auditor, CI gate) can reject a bundle
        that still has a stub manufacturer."""
        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="ABC",  # obvious placeholder
            email="info@abc.test",
            address="",
            is_manufacturer=True,
        )
        p = Product.objects.create(name="Placeholder Export", team=team)
        ares = get_or_create_assessment(p.id, sample_user, team)
        with patch("sbomify.apps.core.object_store.S3Client"):
            regenerate_all(ares.value)
        mock_get_content.return_value = b"mock content"

        result = build_export_package(ares.value, sample_user)
        assert result.ok
        mfr = result.value.manifest["manufacturer"]
        assert mfr["is_placeholder"] is True


@pytest.mark.django_db
class TestBuildExportPackageFailurePaths:
    """Covers the non-happy paths in ``build_export_package``.

    Previously uncovered because every earlier test exercised the
    successful upload branch only. These tests pin the 502 error
    contract and the bundle-prefix fallback to product.id."""

    def test_s3_upload_failure_returns_502(self, assessment_with_docs, sample_user):
        """Simulate the final ZIP upload to S3 failing. The function
        must convert the boto exception into a clean
        ``ServiceResult.failure(502)`` — no stack leak."""

        class _FailingS3:
            def upload_data_as_file(self, bucket, key, data):
                raise RuntimeError("S3 unavailable")

            def get_file_data(self, bucket, key):
                return b""

            def get_sbom_data(self, filename):
                return b""

        with patch("sbomify.apps.compliance.services.export_service.S3Client") as mock_s3_cls:
            mock_s3_cls.return_value = _FailingS3()
            result = build_export_package(assessment_with_docs, sample_user)

        assert not result.ok
        assert result.status_code == 502
        assert "storage" in (result.error or "").lower()

    def test_bundle_prefix_falls_back_to_product_id_when_slug_empty(
        self, sample_team_with_owner_member, sample_user
    ):
        """Product name made of punctuation only: ``slugify`` returns
        empty, so the bundle root would be ``cra-package-/``. The
        fallback to ``product.id`` keeps the slug segment non-empty,
        matching ``get_download_url``'s filename contract."""
        team = sample_team_with_owner_member.team
        profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="Acme Labs",
            email="legal@acme.test",
            is_manufacturer=True,
        )
        p = Product.objects.create(name="---", team=team)  # slugifies to ""
        ares = get_or_create_assessment(p.id, sample_user, team)
        assert ares.ok

        with patch("sbomify.apps.core.object_store.S3Client"):
            regenerate_all(ares.value)

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
            result = build_export_package(ares.value, sample_user)

        assert result.ok
        # Inspect the manifest — every file path must live under
        # ``cra-package-<product_id>/``, never ``cra-package-/``.
        import json
        import zipfile
        from io import BytesIO

        zf = zipfile.ZipFile(BytesIO(captured["bytes"]))
        manifest_name = f"cra-package-{p.id}/metadata/manifest.json"
        assert manifest_name in zf.namelist(), (
            f"Bundle prefix did not fall back to product.id; expected {manifest_name!r}"
        )
        manifest = json.loads(zf.read(manifest_name))
        for entry in manifest["files"]:
            assert entry["path"].startswith(f"cra-package-{p.id}/")


class TestIntegrityReadmeFormatVersion:
    """``_integrity_readme`` must quote the same ``format_version`` as
    the manifest itself. Regression guard against drift when the
    schema bumps."""

    def test_readme_version_matches_constant(self):
        from sbomify.apps.compliance.services.export_service import _MANIFEST_FORMAT_VERSION

        readme = _integrity_readme("deadbeef" * 8)
        assert f"**{_MANIFEST_FORMAT_VERSION}**" in readme

    def test_readme_uses_metadata_prefixed_paths(self):
        """Follow-up to the Copilot review: README must refer to
        ``metadata/manifest.json`` (full relative path), not bare
        ``manifest.json``, so operators running the commands from the
        bundle root don't get confused."""
        readme = _integrity_readme("deadbeef" * 8)
        assert "`metadata/manifest.json`" in readme
        assert "`metadata/manifest.sha256`" in readme
        assert "`metadata/INTEGRITY.md`" in readme

    def test_readme_references_downstream_signing(self):
        """README carries the "About signatures" section pointing
        operators at ``cosign sign-blob`` / ``gpg --detach-sign`` as
        the downstream-signing path. Bundle signing itself is not
        implemented in-tree."""
        readme = _integrity_readme("deadbeef" * 8)
        assert "About signatures" in readme
        assert "cosign sign-blob" in readme


@pytest.mark.django_db
class TestGetDownloadUrl:
    def test_generates_presigned_url(self, mock_s3_client):
        mock_package = MagicMock()
        mock_package.storage_key = "compliance/exports/test/abc.zip"

        result = get_download_url(mock_package)

        assert result.ok
        assert result.value == "https://s3.example.com/presigned"

    def test_presigned_url_contract(self, mock_s3_client):
        """Regression for the #909 contract: regulated-evidence URLs
        must be short-lived (900 s), forced to download (not inline),
        and typed as application/zip. The product slug + content-hash
        prefix ends up in the filename so bundles are distinguishable
        on disk."""
        mock_package = MagicMock()
        mock_package.storage_key = "compliance/exports/test/abc.zip"
        mock_package.content_hash = "abcdef0123456789"  # >= 12 chars
        mock_package.assessment.product.name = "Lithium Edge Gateway"
        mock_package.assessment.product.id = "prod-fallback-id"

        result = get_download_url(mock_package)

        assert result.ok
        call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
        assert call_kwargs["ExpiresIn"] == 900
        params = call_kwargs["Params"]
        assert params["ResponseContentType"] == "application/zip"
        disposition = params["ResponseContentDisposition"]
        assert disposition.startswith("attachment; ")
        assert 'filename="cra-package-lithium-edge-gateway-abcdef012345.zip"' in disposition

    def test_presigned_url_filename_falls_back_to_product_id(self, mock_s3_client):
        """When the product name slugifies to an empty string (e.g. a
        name containing only punctuation), the filename falls back to
        the product id so the slug segment stays non-empty."""
        mock_package = MagicMock()
        mock_package.storage_key = "compliance/exports/test/abc.zip"
        mock_package.content_hash = "0011223344556677"
        mock_package.assessment.product.name = "---"
        mock_package.assessment.product.id = "prod-abc123"

        result = get_download_url(mock_package)

        assert result.ok
        disposition = mock_s3_client.generate_presigned_url.call_args.kwargs["Params"][
            "ResponseContentDisposition"
        ]
        assert 'filename="cra-package-prod-abc123-001122334455.zip"' in disposition

    def test_handles_s3_error(self):
        mock_package = MagicMock()
        mock_package.storage_key = "bad-key"

        with patch("boto3.client") as mock_client_fn:
            mock_client_fn.side_effect = Exception("S3 error")

            result = get_download_url(mock_package)

        assert not result.ok
        assert result.status_code == 500


class TestExportHelpers:
    """Unit-level coverage for the small helpers used by the export
    pipeline. Keeps them under test without needing the full build /
    S3 / ZIP round-trip."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, True),
            ("", True),
            ("   ", True),
            ("ABC", True),
            ("xyz", True),
            ("TEST", True),
            ("  foo  ", True),
            ("Acme Corp", False),
            ("Contoso GmbH", False),
            ("abc123", False),
        ],
    )
    def test_is_placeholder_manufacturer(self, value, expected):
        assert _is_placeholder_manufacturer(value) is expected

    def test_integrity_readme_interpolates_hash(self):
        """The one-argument builder echoes the hash + standard sha256sum
        verification line. Guarantees the rendered README isn't a
        hard-coded stub."""
        content = _integrity_readme("a" * 64)
        assert "a" * 64 in content
        assert "sha256sum -c metadata/manifest.sha256" in content
        assert "manifest.json" in content

    def test_integrity_readme_per_file_command_runs_from_bundle_root(self):
        """Regression: the per-file verification command must be
        runnable from the extracted bundle root without any `cd ..`
        trickery. The README instructs stripping the ``cra-package-*/``
        prefix and piping straight into ``sha256sum -c -`` — no
        intermediate /tmp file, no parent-directory hop."""
        content = _integrity_readme("a" * 64)
        # Workflow uses a single pipeline ending in `sha256sum -c -`.
        assert "sha256sum -c -" in content
        # The prefix-stripping jq expression is there — this is the
        # exact fragment that makes paths resolve against the bundle
        # root (the cwd the README tells operators to run from).
        assert 'sub("^cra-package-[^/]*/"; "")' in content
        # Correcting a prior bug: the README no longer contains the
        # broken ``cd ..`` form.
        assert "cd .." not in content

    def test_integrity_readme_clarifies_what_manifest_excludes(self):
        """The README was previously claiming the manifest covers
        'every artefact in the ZIP', which wasn't true — manifest.json,
        manifest.sha256, and INTEGRITY.md are deliberately excluded.
        The new copy has to spell that out so auditors don't chase a
        non-existent gap."""
        content = _integrity_readme("a" * 64)
        assert "NOT listed" in content or "not listed" in content
        for primitive in ("manifest.json", "manifest.sha256", "INTEGRITY.md"):
            assert primitive in content

    def test_article_14_reporting_readme_contains_all_deadlines(self):
        """Readme enumerates all four Article 14 deadlines."""
        content = _article_14_reporting_readme()
        for token in ("≤24 h", "≤72 h", "≤14 d", "≤1 mo", "2026-09-11", "ENISA"):
            assert token in content

    def test_article_14_readme_references_ec_portal(self):
        """Readme points operators at the EC CRA reporting page."""
        content = _article_14_reporting_readme()
        assert "digital-strategy.ec.europa.eu/en/policies/cra-reporting" in content


class TestGetGeneratedDocContent:
    """Error-path coverage for the S3 fetch helper."""

    def test_returns_none_on_s3_failure(self):
        """A broken S3 fetch must return None (so the caller omits the
        doc from the bundle) rather than raising."""
        from sbomify.apps.compliance.models import CRAGeneratedDocument

        mock_doc = MagicMock(spec=CRAGeneratedDocument)
        mock_doc.storage_key = "compliance/missing.md"
        s3 = MagicMock()
        s3.get_file_data.side_effect = Exception("boom")

        assert _get_generated_doc_content(mock_doc, s3_client=s3) is None

    def test_returns_bytes_on_success(self):
        from sbomify.apps.compliance.models import CRAGeneratedDocument

        mock_doc = MagicMock(spec=CRAGeneratedDocument)
        mock_doc.storage_key = "compliance/ok.md"
        s3 = MagicMock()
        s3.get_file_data.return_value = b"payload"

        assert _get_generated_doc_content(mock_doc, s3_client=s3) == b"payload"

    def test_creates_default_s3_client_when_none_provided(self):
        """When no client is passed, the helper constructs its own."""
        from sbomify.apps.compliance.models import CRAGeneratedDocument

        mock_doc = MagicMock(spec=CRAGeneratedDocument)
        mock_doc.storage_key = "compliance/ok.md"

        with patch("sbomify.apps.compliance.services.export_service.S3Client") as mock_s3_cls:
            inst = MagicMock()
            inst.get_file_data.return_value = b"payload"
            mock_s3_cls.return_value = inst

            result = _get_generated_doc_content(mock_doc)

        assert result == b"payload"
        mock_s3_cls.assert_called_once_with("DOCUMENTS")


class TestGetSbomContent:
    """SBOM fetch helper — covers the missing-filename shortcut and
    the S3-failure fallback."""

    def test_returns_none_when_sbom_filename_missing(self):
        sbom = MagicMock()
        sbom.sbom_filename = None
        assert _get_sbom_content(sbom) is None

    def test_returns_none_on_s3_failure(self):
        sbom = MagicMock()
        sbom.sbom_filename = "lithium.cdx.json"
        s3 = MagicMock()
        s3.get_sbom_data.side_effect = Exception("boom")

        assert _get_sbom_content(sbom, s3_client=s3) is None

    def test_returns_bytes_on_success(self):
        sbom = MagicMock()
        sbom.sbom_filename = "lithium.cdx.json"
        s3 = MagicMock()
        s3.get_sbom_data.return_value = b"{...}"

        assert _get_sbom_content(sbom, s3_client=s3) == b"{...}"

    def test_creates_default_s3_client_when_none_provided(self):
        sbom = MagicMock()
        sbom.sbom_filename = "lithium.cdx.json"

        with patch("sbomify.apps.compliance.services.export_service.S3Client") as mock_s3_cls:
            inst = MagicMock()
            inst.get_sbom_data.return_value = b"{...}"
            mock_s3_cls.return_value = inst

            result = _get_sbom_content(sbom)

        assert result == b"{...}"
        mock_s3_cls.assert_called_once_with("SBOMS")
