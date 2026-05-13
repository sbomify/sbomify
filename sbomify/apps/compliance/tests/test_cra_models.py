"""Tests for CRA compliance models."""

import pytest
from django.db import IntegrityError, transaction

from sbomify.apps.compliance.models import (
    CRAAssessment,
    CRAExportPackage,
    CRAGeneratedDocument,
    OSCALAssessmentResult,
    OSCALCatalog,
)
from sbomify.apps.core.models import Product


@pytest.fixture
def catalog():
    return OSCALCatalog.objects.create(
        name="BSI TR-03183-1",
        version="1.0",
        catalog_json={"metadata": {"title": "BSI TR-03183-1"}},
    )


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Test Product", team=team)


@pytest.fixture
def oscal_result(catalog, sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return OSCALAssessmentResult.objects.create(
        catalog=catalog,
        team=team,
        title="CRA OSCAL Result",
    )


@pytest.fixture
def cra_assessment(sample_team_with_owner_member, product, oscal_result):
    team = sample_team_with_owner_member.team
    return CRAAssessment.objects.create(
        team=team,
        product=product,
        oscal_assessment_result=oscal_result,
    )


@pytest.mark.django_db
class TestCRAAssessment:
    def test_create_assessment(self, cra_assessment, product, oscal_result):
        assert cra_assessment.pk is not None
        assert len(cra_assessment.pk) == 12
        assert cra_assessment.product == product
        assert cra_assessment.oscal_assessment_result == oscal_result
        assert cra_assessment.created_at is not None
        assert cra_assessment.updated_at is not None

    def test_defaults(self, cra_assessment):
        assert cra_assessment.status == "draft"
        assert cra_assessment.current_step == 1
        assert cra_assessment.completed_steps == []
        assert cra_assessment.completed_at is None
        assert cra_assessment.intended_use == ""
        assert cra_assessment.target_eu_markets == []
        assert cra_assessment.support_period_end is None
        assert cra_assessment.product_category == "default"
        assert cra_assessment.is_open_source_steward is False
        assert cra_assessment.conformity_assessment_procedure == "module_a"
        assert cra_assessment.vdp_url == ""
        assert cra_assessment.acknowledgment_timeline_days is None
        assert cra_assessment.csirt_contact_email == ""
        assert cra_assessment.security_contact_url == ""
        assert cra_assessment.csirt_country == ""
        assert cra_assessment.enisa_srp_registered is False
        assert cra_assessment.incident_response_plan_url == ""
        assert cra_assessment.incident_response_notes == ""
        assert cra_assessment.update_frequency == ""
        assert cra_assessment.update_method == ""
        assert cra_assessment.update_channel_url == ""
        assert cra_assessment.support_email == ""
        assert cra_assessment.support_url == ""
        assert cra_assessment.support_phone == ""
        assert cra_assessment.support_hours == ""
        assert cra_assessment.data_deletion_instructions == ""
        assert cra_assessment.created_by is None

    def test_one_assessment_per_product(self, cra_assessment, sample_team_with_owner_member, catalog):
        """OneToOneField on product ensures only one assessment per product."""
        team = sample_team_with_owner_member.team
        oscal2 = OSCALAssessmentResult.objects.create(catalog=catalog, team=team, title="Second OSCAL Result")
        with pytest.raises(IntegrityError), transaction.atomic():
            CRAAssessment.objects.create(
                team=team,
                product=cra_assessment.product,
                oscal_assessment_result=oscal2,
            )

    def test_product_category_choices(self):
        choices = CRAAssessment.ProductCategory
        assert choices.DEFAULT == "default"
        assert choices.CLASS_I == "class_i"
        assert choices.CLASS_II == "class_ii"
        assert choices.CRITICAL == "critical"
        assert len(choices.choices) == 4

    def test_conformity_procedure_choices(self):
        choices = CRAAssessment.ConformityProcedure
        assert choices.MODULE_A == "module_a"
        assert choices.MODULE_B_C == "module_b_c"
        assert choices.MODULE_H == "module_h"
        assert choices.EUCC == "eucc"
        assert len(choices.choices) == 4

    def test_wizard_status_choices(self):
        choices = CRAAssessment.WizardStatus
        assert choices.DRAFT == "draft"
        assert choices.IN_PROGRESS == "in_progress"
        assert choices.COMPLETE == "complete"
        # ``STALE`` was added in issue #921 — kept in this enumeration
        # so the stale-flag can ride the same ``status`` column without
        # a parallel boolean.
        assert choices.STALE == "stale"
        assert len(choices.choices) == 4

    def test_str(self, cra_assessment):
        assert "CRA Assessment for" in str(cra_assessment)
        assert "(draft)" in str(cra_assessment)

    def test_product_cascade_delete(self, cra_assessment, product):
        pk = cra_assessment.pk
        product.delete()
        assert not CRAAssessment.objects.filter(pk=pk).exists()

    def test_team_cascade_delete(self, catalog):
        from sbomify.apps.teams.models import Team

        team = Team.objects.create(name="cascade-test-team")
        product = Product.objects.create(name="Cascade Product", team=team)
        oscal = OSCALAssessmentResult.objects.create(catalog=catalog, team=team, title="Cascade OSCAL")
        assessment = CRAAssessment.objects.create(team=team, product=product, oscal_assessment_result=oscal)
        pk = assessment.pk
        team.delete()
        assert not CRAAssessment.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestCRAGeneratedDocument:
    def test_create_document(self, cra_assessment):
        doc = CRAGeneratedDocument.objects.create(
            assessment=cra_assessment,
            document_kind="vdp",
            storage_key="compliance/docs/vdp-123.pdf",
            content_hash="a" * 64,
        )
        assert doc.pk is not None
        assert len(doc.pk) == 12
        assert doc.assessment == cra_assessment
        assert doc.document_kind == "vdp"
        assert doc.storage_key == "compliance/docs/vdp-123.pdf"
        assert doc.content_hash == "a" * 64
        assert doc.version == 1
        assert doc.is_stale is False
        assert doc.generated_at is not None

    def test_unique_assessment_document_kind(self, cra_assessment):
        CRAGeneratedDocument.objects.create(
            assessment=cra_assessment,
            document_kind="vdp",
            storage_key="key1",
            content_hash="a" * 64,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            CRAGeneratedDocument.objects.create(
                assessment=cra_assessment,
                document_kind="vdp",
                storage_key="key2",
                content_hash="b" * 64,
            )

    def test_different_kinds_same_assessment(self, cra_assessment):
        doc1 = CRAGeneratedDocument.objects.create(
            assessment=cra_assessment,
            document_kind="vdp",
            storage_key="key1",
            content_hash="a" * 64,
        )
        doc2 = CRAGeneratedDocument.objects.create(
            assessment=cra_assessment,
            document_kind="security_txt",
            storage_key="key2",
            content_hash="b" * 64,
        )
        assert doc1.pk != doc2.pk

    def test_document_kind_choices(self):
        choices = CRAGeneratedDocument.DocumentKind
        assert len(choices.choices) == 9
        expected = {
            "vdp",
            "security_txt",
            "risk_assessment",
            "early_warning",
            "full_notification",
            "final_report",
            "user_instructions",
            "decommissioning_guide",
            "declaration_of_conformity",
        }
        assert {c[0] for c in choices.choices} == expected

    def test_assessment_cascade_delete(self, cra_assessment):
        doc = CRAGeneratedDocument.objects.create(
            assessment=cra_assessment,
            document_kind="vdp",
            storage_key="key",
            content_hash="a" * 64,
        )
        pk = doc.pk
        cra_assessment.delete()
        assert not CRAGeneratedDocument.objects.filter(pk=pk).exists()

    def test_str(self, cra_assessment):
        doc = CRAGeneratedDocument.objects.create(
            assessment=cra_assessment,
            document_kind="vdp",
            storage_key="key",
            content_hash="a" * 64,
        )
        assert "Vulnerability Disclosure Policy" in str(doc)


@pytest.mark.django_db
class TestCRAExportPackage:
    def test_create_export_package(self, cra_assessment, sample_user):
        pkg = CRAExportPackage.objects.create(
            assessment=cra_assessment,
            storage_key="compliance/exports/pkg-123.zip",
            content_hash="b" * 64,
            manifest={"files": ["vdp.pdf", "security.txt"]},
            created_by=sample_user,
        )
        assert pkg.pk is not None
        assert len(pkg.pk) == 12
        assert pkg.assessment == cra_assessment
        assert pkg.storage_key == "compliance/exports/pkg-123.zip"
        assert pkg.content_hash == "b" * 64
        assert pkg.manifest == {"files": ["vdp.pdf", "security.txt"]}
        assert pkg.created_at is not None
        assert pkg.created_by == sample_user

    def test_create_without_user(self, cra_assessment):
        pkg = CRAExportPackage.objects.create(
            assessment=cra_assessment,
            storage_key="key",
            content_hash="c" * 64,
            manifest={},
        )
        assert pkg.created_by is None

    def test_assessment_cascade_delete(self, cra_assessment):
        pkg = CRAExportPackage.objects.create(
            assessment=cra_assessment,
            storage_key="key",
            content_hash="d" * 64,
            manifest={},
        )
        pk = pkg.pk
        cra_assessment.delete()
        assert not CRAExportPackage.objects.filter(pk=pk).exists()

    def test_str(self, cra_assessment):
        pkg = CRAExportPackage.objects.create(
            assessment=cra_assessment,
            storage_key="key",
            content_hash="e" * 64,
            manifest={},
        )
        assert "Export package" in str(pkg)
        assert str(pkg.pk) in str(pkg)
