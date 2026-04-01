"""Tests for the CRA compliance wizard service."""

from __future__ import annotations

import datetime

import pytest

from sbomify.apps.compliance.models import (
    CRAAssessment,
    OSCALAssessmentResult,
    OSCALFinding,
)
from sbomify.apps.compliance.services.wizard_service import (
    get_assessment_by_id,
    get_assessment_list_for_team,
    get_compliance_summary,
    get_or_create_assessment,
    get_step_context,
    save_step_data,
)
from sbomify.apps.core.models import Product
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    """Create a Product for testing."""
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="CRA Test Product", team=team)


@pytest.fixture
def product_with_contacts(sample_team_with_owner_member, product):
    """Product with manufacturer contact and security contact."""
    team = sample_team_with_owner_member.team
    profile = ContactProfile.objects.create(name="Default Profile", team=team, is_default=True)
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Acme Corp",
        email="info@acme.test",
        address="123 Test St",
        is_manufacturer=True,
        website_urls=["https://acme.test"],
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Security Lead",
        email="security@acme.test",
        is_security_contact=True,
    )
    return product


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product):
    """Create a CRAAssessment for testing."""
    team = sample_team_with_owner_member.team
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.mark.django_db
class TestGetOrCreateAssessment:
    def test_creates_assessment_with_ar_and_findings(self, sample_team_with_owner_member, sample_user, product):
        team = sample_team_with_owner_member.team
        result = get_or_create_assessment(product.id, sample_user, team)

        assert result.ok
        assessment = result.value
        assert assessment.product == product
        assert assessment.team == team
        assert assessment.oscal_assessment_result is not None
        assert assessment.status == CRAAssessment.WizardStatus.DRAFT
        assert assessment.current_step == 1
        assert assessment.completed_steps == []

        # Verify OSCAL AR + 21 findings
        ar = assessment.oscal_assessment_result
        assert ar.status == OSCALAssessmentResult.AssessmentStatus.IN_PROGRESS
        assert OSCALFinding.objects.filter(assessment_result=ar).count() == 21

    def test_returns_existing_assessment(self, sample_team_with_owner_member, sample_user, product):
        team = sample_team_with_owner_member.team
        result1 = get_or_create_assessment(product.id, sample_user, team)
        result2 = get_or_create_assessment(product.id, sample_user, team)

        assert result1.ok and result2.ok
        assert result1.value.id == result2.value.id
        assert CRAAssessment.objects.filter(product=product).count() == 1

    def test_auto_fills_from_contacts(self, sample_team_with_owner_member, sample_user, product_with_contacts):
        team = sample_team_with_owner_member.team
        result = get_or_create_assessment(product_with_contacts.id, sample_user, team)

        assert result.ok
        assessment = result.value
        assert assessment.csirt_contact_email == "security@acme.test"
        assert assessment.support_email == "info@acme.test"

    def test_auto_fills_support_period_from_product(self, sample_team_with_owner_member, sample_user):
        import datetime

        team = sample_team_with_owner_member.team
        product = Product.objects.create(
            name="Dated Product",
            team=team,
            end_of_support=datetime.date(2028, 12, 31),
        )

        result = get_or_create_assessment(product.id, sample_user, team)
        assert result.ok
        assert result.value.support_period_end == datetime.date(2028, 12, 31)

    def test_fails_for_nonexistent_product(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        result = get_or_create_assessment("nonexistent", sample_user, team)

        assert not result.ok
        assert result.status_code == 404

    def test_fails_for_wrong_team(self, sample_team_with_owner_member, sample_user, product):
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other Team")
        result = get_or_create_assessment(product.id, sample_user, other_team)

        assert not result.ok
        assert result.status_code == 404


@pytest.mark.django_db
class TestGetStepContext:
    def test_step_1_returns_product_data(self, assessment):
        result = get_step_context(assessment, 1)

        assert result.ok
        data = result.value
        assert "product" in data
        assert data["product"]["name"] == "CRA Test Product"
        assert "intended_use" in data
        assert "product_category" in data
        assert "conformity_assessment_procedure" in data

    def test_step_2_returns_sbom_status(self, assessment):
        result = get_step_context(assessment, 2)

        assert result.ok
        data = result.value
        assert "components" in data
        assert "summary" in data

    def test_step_3_returns_grouped_findings(self, assessment):
        result = get_step_context(assessment, 3)

        assert result.ok
        data = result.value
        assert "control_groups" in data
        assert "summary" in data
        assert "vulnerability_handling" in data
        assert "article_14" in data

        # 5 groups
        assert len(data["control_groups"]) == 5

        # Summary counts
        assert data["summary"]["total"] == 21
        assert data["summary"]["unanswered"] == 21

    def test_step_4_returns_user_info_and_docs(self, assessment):
        result = get_step_context(assessment, 4)

        assert result.ok
        data = result.value
        assert "user_info" in data
        assert "documents" in data
        assert data["user_info"]["update_frequency"] == ""
        assert data["documents"] == {}

    def test_step_5_returns_summary(self, assessment):
        result = get_step_context(assessment, 5)

        assert result.ok
        data = result.value
        assert "product" in data
        assert "steps" in data
        assert "overall_ready" in data
        assert data["overall_ready"] is False

    def test_invalid_step_returns_error(self, assessment):
        result = get_step_context(assessment, 99)
        assert not result.ok
        assert result.status_code == 400


@pytest.mark.django_db
class TestSaveStepData:
    def test_step_1_saves_product_profile(self, assessment, sample_user):
        data = {
            "intended_use": "Home automation controller",
            "target_eu_markets": ["DE", "FR", "NL"],
            "product_category": "class_i",
            "is_open_source_steward": False,
            "harmonised_standard_applied": True,
            "support_period_end": str(
                datetime.date(datetime.date.today().year + 6, 6, 30)
            ),  # June 30, 6 years from now — always satisfies 5-year minimum (CRA Art 13(8))
        }
        result = save_step_data(assessment, 1, data, sample_user)

        assert result.ok
        a = result.value
        assert a.intended_use == "Home automation controller"
        assert a.target_eu_markets == ["DE", "FR", "NL"]
        assert a.product_category == "class_i"
        # Class I defaults to Module A (requires harmonised standard per CRA Art 32(2))
        assert a.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_A
        assert a.harmonised_standard_applied is True
        assert 1 in a.completed_steps
        assert a.status == CRAAssessment.WizardStatus.IN_PROGRESS

    def test_step_1_class_ii_sets_module_bc(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"product_category": "class_ii"}, sample_user)
        assert result.ok
        assert result.value.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_B_C

    def test_step_1_critical_defaults_to_module_bc(self, assessment, sample_user):
        """Critical products default to Module B+C (CRA Art 32(3)); EUCC not yet mandated."""
        result = save_step_data(assessment, 1, {"product_category": "critical"}, sample_user)
        assert result.ok
        assert result.value.conformity_assessment_procedure == CRAAssessment.ConformityProcedure.MODULE_B_C

    def test_step_1_class_i_without_harmonised_standard_rejected(self, assessment, sample_user):
        """Class I + Module A requires harmonised standard (CRA Art 32(2))."""
        result = save_step_data(assessment, 1, {"product_category": "class_i"}, sample_user)
        assert not result.ok
        assert result.status_code == 400
        assert "harmonised standard" in result.error.lower()

    def test_step_1_invalid_category_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"product_category": "invalid"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_2_marks_complete(self, assessment, sample_user):
        result = save_step_data(assessment, 2, {}, sample_user)
        assert result.ok
        assert 2 in result.value.completed_steps

    def test_step_3_updates_findings(self, assessment, sample_user):
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()

        data = {
            "findings": [
                {"finding_id": finding.id, "status": "satisfied", "notes": "Implemented"},
            ],
        }
        result = save_step_data(assessment, 3, data, sample_user)

        assert result.ok
        finding.refresh_from_db()
        assert finding.status == "satisfied"
        assert finding.notes == "Implemented"

    def test_step_3_updates_vuln_handling(self, assessment, sample_user):
        data = {
            "vulnerability_handling": {
                "vdp_url": "https://example.com/vdp",
                "acknowledgment_timeline_days": 5,
            },
        }
        result = save_step_data(assessment, 3, data, sample_user)

        assert result.ok
        a = result.value
        assert a.vdp_url == "https://example.com/vdp"
        assert a.acknowledgment_timeline_days == 5

    def test_step_3_updates_article_14(self, assessment, sample_user):
        data = {
            "article_14": {
                "csirt_country": "DE",
                "enisa_srp_registered": True,
            },
        }
        result = save_step_data(assessment, 3, data, sample_user)

        assert result.ok
        a = result.value
        assert a.csirt_country == "DE"
        assert a.enisa_srp_registered is True

    def test_step_3_invalid_finding_id(self, assessment, sample_user):
        data = {
            "findings": [
                {"finding_id": "nonexistent", "status": "satisfied"},
            ],
        }
        result = save_step_data(assessment, 3, data, sample_user)
        assert not result.ok
        assert result.status_code == 404

    def test_step_3_invalid_status(self, assessment, sample_user):
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()
        data = {
            "findings": [
                {"finding_id": finding.id, "status": "bogus"},
            ],
        }
        result = save_step_data(assessment, 3, data, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_4_saves_user_info(self, assessment, sample_user):
        data = {
            "update_frequency": "quarterly",
            "update_method": "auto-with-opt-out",
            "support_email": "support@acme.test",
        }
        result = save_step_data(assessment, 4, data, sample_user)

        assert result.ok
        a = result.value
        assert a.update_frequency == "quarterly"
        assert a.update_method == "auto-with-opt-out"
        assert a.support_email == "support@acme.test"
        assert 4 in a.completed_steps

    def test_step_5_requires_previous_steps(self, assessment, sample_user):
        result = save_step_data(assessment, 5, {}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_5_completes_assessment(self, assessment, sample_user):
        # Answer all findings so step 3 can be marked complete
        OSCALFinding.objects.filter(
            assessment_result=assessment.oscal_assessment_result,
        ).update(status="satisfied")

        # Complete steps 1-4 first
        save_step_data(assessment, 1, {"product_category": "default"}, sample_user)
        save_step_data(assessment, 2, {}, sample_user)
        save_step_data(assessment, 3, {}, sample_user)
        save_step_data(assessment, 4, {}, sample_user)
        assessment.refresh_from_db()

        result = save_step_data(assessment, 5, {}, sample_user)
        assert result.ok
        a = result.value
        assert a.status == CRAAssessment.WizardStatus.COMPLETE
        assert a.completed_at is not None
        assert a.oscal_assessment_result.status == "complete"

    def test_invalid_step_returns_error(self, assessment, sample_user):
        result = save_step_data(assessment, 99, {}, sample_user)
        assert not result.ok
        assert result.status_code == 400


@pytest.mark.django_db
class TestGetComplianceSummary:
    def test_returns_summary_shape(self, assessment):
        result = get_compliance_summary(assessment)

        assert result.ok
        data = result.value
        assert "product" in data
        assert "steps" in data
        assert "overall_ready" in data
        assert "export_available" in data
        assert data["overall_ready"] is False
        assert data["steps"][3]["controls"]["total"] == 21

    def test_overall_ready_when_all_steps_complete(self, assessment, sample_user):
        # Complete steps 1-4
        save_step_data(assessment, 1, {"product_category": "default"}, sample_user)
        save_step_data(assessment, 2, {}, sample_user)

        # Mark all findings as satisfied or not-applicable
        findings = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result)
        for f in findings:
            f.status = "satisfied"
            f.save()

        save_step_data(assessment, 3, {}, sample_user)
        save_step_data(assessment, 4, {}, sample_user)
        assessment.refresh_from_db()

        result = get_compliance_summary(assessment)
        assert result.ok
        assert result.value["overall_ready"] is True


@pytest.mark.django_db
class TestGetAssessmentById:
    def test_returns_assessment(self, assessment):
        result = get_assessment_by_id(assessment.id)
        assert result.ok
        assert result.value is not None
        assert result.value.id == assessment.id
        # Verify select_related data is accessible without extra queries
        assert result.value.team is not None
        assert result.value.product is not None

    def test_nonexistent_returns_failure(self):
        result = get_assessment_by_id("nonexistent99")
        assert not result.ok
        assert result.status_code == 404


@pytest.mark.django_db
class TestGetAssessmentListForTeam:
    def test_returns_assessments_for_team(self, assessment, sample_team_with_owner_member):
        team = sample_team_with_owner_member.team
        result = get_assessment_list_for_team(team.id)
        assert result.ok
        assert len(result.value) == 1
        item = result.value[0]
        assert item["id"] == assessment.id
        assert "product_name" in item
        assert "status" in item
        assert "status_value" in item
        assert "current_step" in item
        assert "completed_steps" in item
        assert "updated_at" in item

    def test_empty_for_other_team(self, assessment):
        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other Team")
        result = get_assessment_list_for_team(other_team.id)
        assert result.ok
        assert len(result.value) == 0

    def test_ordered_by_updated_at(self, sample_team_with_owner_member, sample_user):
        team = sample_team_with_owner_member.team
        p1 = Product.objects.create(name="Product A", team=team)
        p2 = Product.objects.create(name="Product B", team=team)
        r1 = get_or_create_assessment(p1.id, sample_user, team)
        r2 = get_or_create_assessment(p2.id, sample_user, team)
        assert r1.ok and r2.ok
        result = get_assessment_list_for_team(team.id)
        assert result.ok
        assert len(result.value) == 2
        # Most recently updated should be first
        assert result.value[0]["id"] == r2.value.id


@pytest.mark.django_db
class TestStepValidationEdgeCases:
    def test_step_1_invalid_eu_markets_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"target_eu_markets": ["DEU"]}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_eu_markets_not_list_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"target_eu_markets": "DE"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_invalid_date_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 1, {"support_period_end": "not-a-date"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_1_null_date_clears_field(self, assessment, sample_user):
        import datetime

        assessment.support_period_end = datetime.date(2030, 1, 1)
        assessment.save()
        result = save_step_data(assessment, 1, {"support_period_end": None}, sample_user)
        assert result.ok
        result.value.refresh_from_db()
        assert result.value.support_period_end is None

    def test_step_3_findings_not_list_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 3, {"findings": "not-a-list"}, sample_user)
        assert not result.ok
        assert result.status_code == 400

    def test_step_3_finding_not_dict_rejected(self, assessment, sample_user):
        result = save_step_data(assessment, 3, {"findings": ["not-a-dict"]}, sample_user)
        assert not result.ok
        assert result.status_code == 400
