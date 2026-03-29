"""Tests for OSCAL service — catalog loading, import, assessment, serialization."""

from __future__ import annotations

import json

import pytest

from sbomify.apps.compliance.models import (
    OSCALAssessmentResult,
    OSCALCatalog,
    OSCALControl,
    OSCALFinding,
)
from sbomify.apps.compliance.services.oscal_service import (
    build_trestle_assessment_results,
    create_assessment_result,
    ensure_cra_catalog,
    import_catalog_to_db,
    load_cra_catalog,
    serialize_assessment_results,
    update_finding,
)
from sbomify.apps.core.models import Product


@pytest.fixture
def product(sample_team_with_owner_member):
    """Create a Product for testing."""
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="Test Product", team=team)


class TestLoadCraCatalog:
    def test_loads_valid_trestle_catalog(self):
        catalog = load_cra_catalog()

        assert catalog.uuid is not None
        assert catalog.metadata.title == "EU CRA Annex I \u2014 Essential Cybersecurity Requirements"
        assert catalog.metadata.version == "1.0.0"
        assert len(catalog.groups) == 5

    def test_has_21_controls_across_5_groups(self):
        catalog = load_cra_catalog()

        total = sum(len(g.controls) for g in catalog.groups)
        assert total == 21

    def test_group_distribution(self):
        catalog = load_cra_catalog()

        group_counts = {g.id: len(g.controls) for g in catalog.groups}
        assert group_counts == {
            "cra-sd": 6,
            "cra-dp": 4,
            "cra-av": 2,
            "cra-mn": 1,
            "cra-vh": 8,
        }

    def test_controls_have_required_fields(self):
        catalog = load_cra_catalog()

        for group in catalog.groups:
            for control in group.controls:
                assert control.id is not None
                assert control.title is not None
                assert control.props is not None
                assert len(control.props) >= 2
                prop_names = {p.name for p in control.props}
                assert "annex-ref" in prop_names
                assert "label" in prop_names
                assert control.parts is not None
                # At least a statement part
                part_names = {p.name for p in control.parts}
                assert "statement" in part_names


@pytest.mark.django_db
class TestImportCatalogToDb:
    def test_creates_catalog_and_controls(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        assert db_catalog.pk is not None
        assert db_catalog.name == "EU CRA Annex I"
        assert db_catalog.version == "1.0.0"
        assert db_catalog.catalog_json is not None

        controls = OSCALControl.objects.filter(catalog=db_catalog)
        assert controls.count() == 21

    def test_group_distribution_in_db(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        sd = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-sd").count()
        dp = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-dp").count()
        av = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-av").count()
        mn = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-mn").count()
        vh = OSCALControl.objects.filter(catalog=db_catalog, group_id="cra-vh").count()

        assert sd == 6
        assert dp == 4
        assert av == 2
        assert mn == 1
        assert vh == 8

    def test_controls_have_descriptions(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        controls = OSCALControl.objects.filter(catalog=db_catalog)
        for control in controls:
            assert control.description, f"Control {control.control_id} should have a description"

    def test_sort_order_is_sequential(self):
        trestle_catalog = load_cra_catalog()
        db_catalog = import_catalog_to_db(trestle_catalog, "EU CRA Annex I", "1.0.0")

        controls = list(OSCALControl.objects.filter(catalog=db_catalog).order_by("sort_order"))
        for i, control in enumerate(controls):
            assert control.sort_order == i


@pytest.mark.django_db
class TestEnsureCraCatalog:
    def test_creates_catalog_on_first_call(self):
        catalog = ensure_cra_catalog()

        assert catalog.pk is not None
        assert catalog.name == "EU CRA Annex I"
        assert catalog.version == "1.0.0"
        assert OSCALControl.objects.filter(catalog=catalog).count() == 21

    def test_idempotent_returns_same_catalog(self):
        catalog1 = ensure_cra_catalog()
        catalog2 = ensure_cra_catalog()

        assert catalog1.pk == catalog2.pk
        assert OSCALCatalog.objects.filter(name="EU CRA Annex I", version="1.0.0").count() == 1


@pytest.mark.django_db
class TestCreateAssessmentResult:
    def test_creates_ar_with_21_unanswered_findings(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team

        ar = create_assessment_result(catalog, team, product, sample_user)

        assert ar.pk is not None
        assert ar.catalog == catalog
        assert ar.team == team
        assert "Test Product" in ar.title
        assert ar.status == OSCALAssessmentResult.AssessmentStatus.IN_PROGRESS

        findings = OSCALFinding.objects.filter(assessment_result=ar)
        assert findings.count() == 21
        assert all(f.status == OSCALFinding.FindingStatus.UNANSWERED for f in findings)


@pytest.mark.django_db
class TestUpdateFinding:
    def test_updates_status_and_notes(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        finding = OSCALFinding.objects.filter(assessment_result=ar).first()
        assert finding is not None

        updated = update_finding(finding, "satisfied", "Fully implemented.")

        assert updated.status == "satisfied"
        assert updated.notes == "Fully implemented."

        # Verify persisted
        finding.refresh_from_db()
        assert finding.status == "satisfied"
        assert finding.notes == "Fully implemented."

    def test_rejects_invalid_status(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        finding = OSCALFinding.objects.filter(assessment_result=ar).first()
        assert finding is not None

        with pytest.raises(ValueError, match="Invalid status"):
            update_finding(finding, "bogus-status")


@pytest.mark.django_db
class TestBuildTrestleAssessmentResults:
    def test_produces_valid_oscal(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        # Set some findings to different statuses for a realistic test
        findings = list(OSCALFinding.objects.filter(assessment_result=ar).order_by("control__sort_order"))
        update_finding(findings[0], "satisfied", "Control implemented")
        update_finding(findings[1], "not-satisfied", "Needs work")
        update_finding(findings[2], "not-applicable", "N/A for this product")

        trestle_ar = build_trestle_assessment_results(ar)

        assert trestle_ar.uuid is not None
        assert trestle_ar.metadata is not None
        assert len(trestle_ar.results) == 1

        result = trestle_ar.results[0]
        assert result.findings is not None
        assert len(result.findings) == 21
        assert result.reviewed_controls is not None

    def test_status_mapping(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        findings = list(OSCALFinding.objects.filter(assessment_result=ar).order_by("control__sort_order"))
        update_finding(findings[0], "satisfied")
        update_finding(findings[1], "not-satisfied")
        update_finding(findings[2], "not-applicable")
        # findings[3] stays unanswered

        trestle_ar = build_trestle_assessment_results(ar)
        oscal_findings = trestle_ar.results[0].findings

        # Find findings by target_id
        by_target = {f.target.target_id: f for f in oscal_findings}

        sat = by_target[findings[0].control.control_id]
        assert sat.target.status.state.value == "satisfied"

        not_sat = by_target[findings[1].control.control_id]
        assert not_sat.target.status.state.value == "not-satisfied"

        na = by_target[findings[2].control.control_id]
        assert na.target.status.state.value == "satisfied"
        assert any(p.name == "finding-disposition" and p.value == "not-applicable" for p in na.props)

        unanswered = by_target[findings[3].control.control_id]
        assert unanswered.target.status.state.value == "not-satisfied"
        assert any(p.name == "finding-disposition" and p.value == "omitted" for p in unanswered.props)

    def test_roundtrip_serialization(self, sample_team_with_owner_member, sample_user, product):
        """Build trestle AR, serialize, and parse back to verify validity."""
        from trestle.oscal.assessment_results import AssessmentResults

        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        trestle_ar = build_trestle_assessment_results(ar)
        json_str = trestle_ar.oscal_serialize_json()

        # Parse back — trestle serializes with an "assessment-results" wrapper key
        data = json.loads(json_str)
        inner = data.get("assessment-results", data)
        roundtripped = AssessmentResults(**inner)
        assert roundtripped.uuid == trestle_ar.uuid
        assert len(roundtripped.results) == 1
        assert len(roundtripped.results[0].findings) == 21


@pytest.mark.django_db
class TestSerializeAssessmentResults:
    def test_returns_json_string(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        update_finding(
            OSCALFinding.objects.filter(assessment_result=ar).first(),
            "satisfied",
            "Done",
        )

        json_str = serialize_assessment_results(ar)

        assert isinstance(json_str, str)
        raw = json.loads(json_str)
        # trestle wraps in "assessment-results" key
        data = raw.get("assessment-results", raw)
        assert "uuid" in data
        assert "metadata" in data
        assert "results" in data
        assert len(data["results"]) == 1
        assert len(data["results"][0]["findings"]) == 21

    def test_reflects_correct_statuses(self, sample_team_with_owner_member, sample_user, product):
        catalog = ensure_cra_catalog()
        team = sample_team_with_owner_member.team
        ar = create_assessment_result(catalog, team, product, sample_user)

        findings = list(OSCALFinding.objects.filter(assessment_result=ar).order_by("control__sort_order"))
        update_finding(findings[0], "satisfied")
        update_finding(findings[1], "not-satisfied")

        json_str = serialize_assessment_results(ar)
        raw = json.loads(json_str)
        data = raw.get("assessment-results", raw)

        oscal_findings = data["results"][0]["findings"]
        by_target = {f["target"]["target-id"]: f for f in oscal_findings}

        sat = by_target[findings[0].control.control_id]
        assert sat["target"]["status"]["state"] == "satisfied"

        not_sat = by_target[findings[1].control.control_id]
        assert not_sat["target"]["status"]["state"] == "not-satisfied"
