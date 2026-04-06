"""Tests for the CRA document generation service."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sbomify.apps.compliance.models import (
    CRAGeneratedDocument,
    OSCALFinding,
)
from sbomify.apps.compliance.services.document_generation_service import (
    generate_document,
    get_document_preview,
    regenerate_all,
    regenerate_stale,
)
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Doc Gen Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product):
    team = sample_team_with_owner_member.team

    # Create manufacturer contact
    profile = ContactProfile.objects.create(name="Default", team=team, is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Acme Corp",
        email="info@acme.test",
        address="123 Test St, Berlin",
        is_manufacturer=True,
        website_urls=["https://acme.test"],
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Security Lead",
        email="security@acme.test",
        is_security_contact=True,
    )

    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    a = result.value
    a.intended_use = "Home automation"
    a.target_eu_markets = ["DE", "FR"]
    a.vdp_url = "https://acme.test/vdp"
    a.update_frequency = "quarterly"
    a.support_email = "support@acme.test"
    a.data_deletion_instructions = "Factory reset the device."
    a.save()
    return a


@pytest.mark.django_db
class TestGenerateDocument:
    """Test document generation for each kind."""

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_vdp(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "vdp"
        assert doc.version == 1
        assert doc.is_stale is False
        assert doc.content_hash
        assert doc.storage_key.endswith(".md")

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_security_txt(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "security_txt"
        assert doc.storage_key.endswith(".txt")

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_risk_assessment(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "risk_assessment"

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_declaration_of_conformity(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)

        assert result.ok
        doc = result.value
        assert doc.document_kind == "declaration_of_conformity"

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_all_9_kinds(self, mock_s3_cls, assessment):
        for kind, _ in CRAGeneratedDocument.DocumentKind.choices:
            result = generate_document(assessment, kind)
            assert result.ok, f"Failed to generate {kind}: {result.error}"

    def test_rejects_invalid_kind(self, assessment):
        result = generate_document(assessment, "bogus")
        assert not result.ok
        assert result.status_code == 400


@pytest.mark.django_db
class TestVersioning:
    """Test document version increments and stale flag resets."""

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_version_increments_on_regeneration(self, mock_s3_cls, assessment):
        result1 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result1.ok
        assert result1.value.version == 1

        result2 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result2.ok
        assert result2.value.version == 2
        assert result2.value.id == result1.value.id  # Same record, updated

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_stale_flag_resets_on_regeneration(self, mock_s3_cls, assessment):
        result = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result.ok

        # Manually mark as stale
        doc = result.value
        doc.is_stale = True
        doc.save()

        # Regenerate
        result2 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert result2.ok
        assert result2.value.is_stale is False

    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_content_hash_changes_when_data_changes(self, mock_s3_cls, assessment):
        result1 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        hash1 = result1.value.content_hash

        # Change assessment data
        assessment.vdp_url = "https://acme.test/new-vdp"
        assessment.save()

        result2 = generate_document(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        hash2 = result2.value.content_hash

        assert hash1 != hash2


@pytest.mark.django_db
class TestSecurityTxtFormat:
    """Test that security.txt follows RFC 9116 format."""

    def test_contains_contact_field(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        content = result.value
        assert "Contact: mailto:security@acme.test" in content

    def test_contains_policy_field(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        content = result.value
        assert "Policy: https://acme.test/vdp" in content

    def test_contains_preferred_languages(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.SECURITY_TXT)

        assert result.ok
        content = result.value
        assert "Preferred-Languages:" in content
        # DE -> de, FR -> fr, plus en always included
        assert "de" in content
        assert "en" in content
        assert "fr" in content


@pytest.mark.django_db
class TestDeclarationOfConformity:
    """Test declaration includes all Annex V required fields."""

    def test_contains_product_identification(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Doc Gen Product" in content

    def test_contains_manufacturer_details(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Acme Corp" in content
        assert "123 Test St, Berlin" in content

    def test_contains_responsibility_statement(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "sole responsibility of the manufacturer" in content

    def test_contains_conformity_statement(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Regulation (EU) 2024/2847" in content

    def test_contains_signature_block(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY)
        content = result.value
        assert "Signature:" in content


@pytest.mark.django_db
class TestRiskAssessment:
    """Test risk assessment includes control findings."""

    def test_includes_control_findings_tables(self, assessment):
        # Set some findings
        findings = list(
            OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).order_by(
                "control__sort_order"
            )[:2]
        )
        findings[0].status = "satisfied"
        findings[0].notes = "Implemented"
        findings[0].save()

        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.RISK_ASSESSMENT)
        content = result.value
        assert "Security by Design" in content
        assert "Vulnerability Handling" in content
        assert "Satisfied" in content


@pytest.mark.django_db
class TestRegenerateAll:
    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_all_document_kinds(self, mock_s3_cls, assessment):
        result = regenerate_all(assessment)

        assert result.ok
        assert result.value == 9
        assert CRAGeneratedDocument.objects.filter(assessment=assessment).count() == 9


@pytest.mark.django_db
class TestRegenerateStale:
    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_regenerates_only_stale_documents(self, mock_s3_cls, assessment):
        # Generate all
        regenerate_all(assessment)

        # Mark only 2 as stale
        CRAGeneratedDocument.objects.filter(assessment=assessment, document_kind__in=["vdp", "security_txt"]).update(
            is_stale=True
        )

        result = regenerate_stale(assessment)
        assert result.ok
        assert result.value == 2

        # Verify none are stale now
        assert CRAGeneratedDocument.objects.filter(assessment=assessment, is_stale=True).count() == 0


@pytest.mark.django_db
class TestGetDocumentPreview:
    def test_returns_rendered_string(self, assessment):
        result = get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.VDP)

        assert result.ok
        assert isinstance(result.value, str)
        assert "Vulnerability Disclosure Policy" in result.value
        assert "Doc Gen Product" in result.value

    def test_does_not_persist(self, assessment):
        get_document_preview(assessment, CRAGeneratedDocument.DocumentKind.VDP)
        assert CRAGeneratedDocument.objects.filter(assessment=assessment).count() == 0

    def test_invalid_kind_returns_error(self, assessment):
        result = get_document_preview(assessment, "bogus")
        assert not result.ok
