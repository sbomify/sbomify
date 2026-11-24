"""Tests for the CRA staleness service and signals."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sbomify.apps.compliance.models import CRAGeneratedDocument
from sbomify.apps.compliance.services.document_generation_service import regenerate_all
from sbomify.apps.compliance.services.staleness_service import check_staleness, mark_stale_documents
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Staleness Test Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product):
    team = sample_team_with_owner_member.team
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.fixture
def assessment_with_docs(assessment):
    """Assessment with all 9 documents generated."""
    with patch("sbomify.apps.core.object_store.StorageClient"):
        regenerate_all(assessment)
    return assessment


pytestmark = pytest.mark.django_db


class TestMarkStaleDocuments:
    def test_marks_product_related_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "product")

        assert count == 5  # vdp, risk_assessment, user_instructions, declaration, security_txt
        stale = CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs, is_stale=True)
        stale_kinds = set(stale.values_list("document_kind", flat=True))
        assert "vdp" in stale_kinds
        assert "risk_assessment" in stale_kinds
        assert "declaration_of_conformity" in stale_kinds

    def test_marks_manufacturer_contact_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "manufacturer_contact")
        assert count == 9  # all 9 doc kinds reference manufacturer data

    def test_marks_security_contact_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "security_contact")
        assert count == 6  # security_txt, vdp, user_instructions, early_warning, full_notification, final_report

    def test_marks_sbom_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "sbom")
        assert count == 1  # risk_assessment

    def test_marks_vuln_handling_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "vuln_handling")
        assert count == 2  # vdp, security_txt

    def test_marks_article_14_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "article_14")
        assert count == 3  # early_warning, full_notification, final_report

    def test_marks_user_info_docs_stale(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "user_info")
        assert count == 2  # user_instructions, decommissioning_guide

    def test_does_not_mark_already_stale(self, assessment_with_docs):
        mark_stale_documents(assessment_with_docs, "product")
        # Second call should not re-mark already stale docs
        count = mark_stale_documents(assessment_with_docs, "product")
        assert count == 0

    def test_unknown_source_marks_nothing(self, assessment_with_docs):
        count = mark_stale_documents(assessment_with_docs, "unknown")
        assert count == 0

    def test_no_generated_docs_marks_nothing(self, assessment):
        # No docs generated yet
        count = mark_stale_documents(assessment, "product")
        assert count == 0


class TestCheckStaleness:
    def test_returns_empty_when_no_stale_docs(self, assessment_with_docs):
        result = check_staleness(assessment_with_docs)

        assert result.ok
        data = result.value
        assert data["stale_documents"] == []
        assert data["stale_steps"] == []
        assert data["has_new_sbom"] is False

    def test_returns_stale_documents(self, assessment_with_docs):
        mark_stale_documents(assessment_with_docs, "product")

        result = check_staleness(assessment_with_docs)

        assert result.ok
        data = result.value
        assert "vdp" in data["stale_documents"]
        assert "risk_assessment" in data["stale_documents"]

    def test_stale_steps_empty_by_design(self, assessment_with_docs):
        """stale_steps is intentionally empty — reverse-mapping from docs to steps
        is unreliable due to overlapping doc kinds across sources."""
        mark_stale_documents(assessment_with_docs, "vuln_handling")

        result = check_staleness(assessment_with_docs)

        assert result.ok
        assert result.value["stale_steps"] == []

    def test_no_docs_returns_empty(self, assessment):
        result = check_staleness(assessment)

        assert result.ok
        assert result.value["stale_documents"] == []


class TestSignals:
    """Test that Django signals fire and mark documents stale."""

    def test_product_save_marks_docs_stale(self, assessment_with_docs):
        product = assessment_with_docs.product
        product.name = "Updated Product Name"
        product.save()

        stale_count = CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs, is_stale=True).count()
        assert stale_count == 5

    def test_product_create_does_not_trigger(self, sample_team_with_owner_member):
        """Creating a product should not trigger staleness (no assessment exists)."""
        team = sample_team_with_owner_member.team
        Product.objects.create(name="New Product", team=team)
        # No error = success; nothing to mark stale

    def test_contact_entity_save_marks_docs_stale(self, assessment_with_docs):
        team = assessment_with_docs.team
        profile = ContactProfile.objects.create(name="Test Profile", team=team)
        entity = ContactEntity.objects.create(
            profile=profile,
            name="Acme Corp",
            email="info@acme.test",
            address="123 St",
            is_manufacturer=True,
        )

        # Now update
        entity.name = "Acme Corp Updated"
        entity.save()

        stale_count = CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs, is_stale=True).count()
        assert stale_count == 9  # all 9 doc kinds reference manufacturer data

    def test_non_manufacturer_entity_does_not_trigger(self, assessment_with_docs):
        team = assessment_with_docs.team
        profile = ContactProfile.objects.create(name="Other", team=team)
        entity = ContactEntity.objects.create(
            profile=profile,
            name="Supplier",
            email="supplier@test.com",
            is_manufacturer=False,
            is_supplier=True,
        )
        entity.name = "Updated Supplier"
        entity.save()

        stale_count = CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs, is_stale=True).count()
        assert stale_count == 0

    def test_security_contact_save_marks_docs_stale(self, assessment_with_docs):
        team = assessment_with_docs.team
        profile = ContactProfile.objects.create(name="Sec", team=team)
        entity = ContactEntity.objects.create(
            profile=profile,
            name="Entity",
            email="entity@test.com",
            is_manufacturer=False,
            is_supplier=True,
        )
        contact = ContactProfileContact.objects.create(
            entity=entity,
            name="Security Lead",
            email="security@test.com",
            is_security_contact=True,
        )
        # Reset stale flags from contact creation signals
        CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs).update(is_stale=False)

        # Update the contact — should mark 6 docs stale
        contact.email = "new-security@test.com"
        contact.save()

        stale_count = CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs, is_stale=True).count()
        assert stale_count == 6  # security_txt, vdp, user_instructions, early_warning, full_notification, final_report

    def test_non_security_contact_does_not_trigger(self, assessment_with_docs):
        team = assessment_with_docs.team
        profile = ContactProfile.objects.create(name="Other", team=team)
        entity = ContactEntity.objects.create(
            profile=profile,
            name="Entity",
            email="entity@test.com",
            is_manufacturer=False,
            is_supplier=True,
        )
        contact = ContactProfileContact.objects.create(
            entity=entity,
            name="Sales",
            email="sales@test.com",
            is_security_contact=False,
        )
        # Reset any stale flags from contact creation
        CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs).update(is_stale=False)

        contact.email = "new-sales@test.com"
        contact.save()

        stale_count = CRAGeneratedDocument.objects.filter(assessment=assessment_with_docs, is_stale=True).count()
        assert stale_count == 0


class TestOnAssessmentSaveSignal:
    """Test that assessment field changes trigger correct staleness."""

    def test_vuln_handling_field_marks_docs_stale(self, assessment_with_docs):
        assessment = assessment_with_docs
        assessment.vdp_url = "https://updated.example.com/vdp"
        assessment.save(update_fields=["vdp_url"])
        # VDP and security.txt should be stale
        stale_docs = CRAGeneratedDocument.objects.filter(assessment=assessment, is_stale=True)
        stale_kinds = set(stale_docs.values_list("document_kind", flat=True))
        assert "vdp" in stale_kinds
        assert "security_txt" in stale_kinds

    def test_wizard_state_save_does_not_mark_stale(self, assessment_with_docs):
        assessment = assessment_with_docs
        # Reset all docs to not stale
        CRAGeneratedDocument.objects.filter(assessment=assessment).update(is_stale=False)
        assessment.current_step = 3
        assessment.save(update_fields=["current_step", "status", "completed_steps", "updated_at"])
        stale_count = CRAGeneratedDocument.objects.filter(assessment=assessment, is_stale=True).count()
        assert stale_count == 0
