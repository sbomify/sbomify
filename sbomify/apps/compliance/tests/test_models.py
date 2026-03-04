"""Tests for OSCAL compliance models."""

import pytest
from django.db import IntegrityError, transaction

from sbomify.apps.compliance.models import (
    OSCALAssessmentResult,
    OSCALCatalog,
    OSCALControl,
    OSCALFinding,
    OSCALObservation,
)


@pytest.fixture
def catalog():
    return OSCALCatalog.objects.create(
        name="BSI TR-03183-1",
        version="1.0",
        source_url="https://example.com/catalog",
        catalog_json={"metadata": {"title": "BSI TR-03183-1"}},
    )


@pytest.fixture
def control(catalog):
    return OSCALControl.objects.create(
        catalog=catalog,
        control_id="cra-sd-1",
        group_id="cra-sd",
        group_title="Security by Design",
        title="Secure defaults",
        description="Products shall be delivered with secure default configuration.",
        sort_order=1,
    )


@pytest.fixture
def assessment_result(catalog, sample_team, sample_user):
    return OSCALAssessmentResult.objects.create(
        catalog=catalog,
        team=sample_team,
        title="CRA Assessment Q1 2026",
        description="Quarterly assessment",
        assessor="Jane Doe",
        created_by=sample_user,
    )


@pytest.fixture
def finding(assessment_result, control):
    return OSCALFinding.objects.create(
        assessment_result=assessment_result,
        control=control,
        status="satisfied",
        notes="Control fully implemented.",
    )


@pytest.mark.django_db
class TestOSCALCatalog:
    def test_create_catalog(self, catalog):
        assert catalog.pk is not None
        assert len(catalog.pk) == 12
        assert catalog.name == "BSI TR-03183-1"
        assert catalog.version == "1.0"
        assert catalog.source_url == "https://example.com/catalog"
        assert catalog.catalog_json == {"metadata": {"title": "BSI TR-03183-1"}}
        assert catalog.created_at is not None

    def test_str(self, catalog):
        assert str(catalog) == "BSI TR-03183-1 v1.0"

    def test_unique_together_name_version(self, catalog):
        with pytest.raises(IntegrityError), transaction.atomic():
            OSCALCatalog.objects.create(
                name="BSI TR-03183-1",
                version="1.0",
                catalog_json={},
            )

    def test_different_versions_allowed(self, catalog):
        cat2 = OSCALCatalog.objects.create(
            name="BSI TR-03183-1",
            version="2.0",
            catalog_json={},
        )
        assert cat2.pk != catalog.pk

    def test_source_url_defaults_to_empty(self):
        cat = OSCALCatalog.objects.create(
            name="Test Catalog",
            version="1.0",
            catalog_json={},
        )
        assert cat.source_url == ""


@pytest.mark.django_db
class TestOSCALControl:
    def test_create_control(self, control, catalog):
        assert control.pk is not None
        assert len(control.pk) == 12
        assert control.catalog == catalog
        assert control.control_id == "cra-sd-1"
        assert control.group_id == "cra-sd"
        assert control.group_title == "Security by Design"
        assert control.title == "Secure defaults"
        assert control.sort_order == 1

    def test_str(self, control):
        assert str(control) == "cra-sd-1: Secure defaults"

    def test_unique_together_catalog_control_id(self, control, catalog):
        with pytest.raises(IntegrityError), transaction.atomic():
            OSCALControl.objects.create(
                catalog=catalog,
                control_id="cra-sd-1",
                group_id="cra-sd",
                group_title="Security by Design",
                title="Duplicate",
                description="Duplicate control",
                sort_order=2,
            )

    def test_same_control_id_different_catalog(self, control):
        cat2 = OSCALCatalog.objects.create(name="Other", version="1.0", catalog_json={})
        ctrl2 = OSCALControl.objects.create(
            catalog=cat2,
            control_id="cra-sd-1",
            group_id="cra-sd",
            group_title="Security by Design",
            title="Same ID different catalog",
            description="Allowed",
            sort_order=1,
        )
        assert ctrl2.pk != control.pk

    def test_fk_cascade_delete(self, control, catalog):
        catalog.delete()
        assert not OSCALControl.objects.filter(pk=control.pk).exists()

    def test_ordering_by_sort_order(self, catalog):
        c2 = OSCALControl.objects.create(
            catalog=catalog, control_id="cra-sd-2", group_id="cra-sd",
            group_title="Security by Design", title="Second",
            description="", sort_order=2,
        )
        c1 = OSCALControl.objects.create(
            catalog=catalog, control_id="cra-sd-0", group_id="cra-sd",
            group_title="Security by Design", title="First",
            description="", sort_order=0,
        )
        controls = list(OSCALControl.objects.filter(catalog=catalog))
        assert controls[0] == c1
        assert controls[-1] == c2


@pytest.mark.django_db
class TestOSCALAssessmentResult:
    def test_create_assessment_result(self, assessment_result, catalog, sample_team, sample_user):
        assert assessment_result.pk is not None
        assert len(assessment_result.pk) == 12
        assert assessment_result.catalog == catalog
        assert assessment_result.team == sample_team
        assert assessment_result.title == "CRA Assessment Q1 2026"
        assert assessment_result.assessor == "Jane Doe"
        assert assessment_result.status == "in-progress"
        assert assessment_result.started_at is not None
        assert assessment_result.completed_at is None
        assert assessment_result.created_by == sample_user

    def test_str(self, assessment_result):
        assert str(assessment_result) == "CRA Assessment Q1 2026 (in-progress)"

    def test_status_choices(self, catalog, sample_team):
        ar = OSCALAssessmentResult.objects.create(
            catalog=catalog,
            team=sample_team,
            title="Complete Assessment",
            status="complete",
        )
        assert ar.status == "complete"

    def test_defaults(self, catalog, sample_team):
        ar = OSCALAssessmentResult.objects.create(
            catalog=catalog,
            team=sample_team,
            title="Minimal",
        )
        assert ar.status == "in-progress"
        assert ar.description == ""
        assert ar.assessor == ""
        assert ar.created_by is None

    def test_team_cascade_delete(self, catalog, sample_user):
        from sbomify.apps.teams.models import Team

        team = Team.objects.create(name="cascade-test-team")
        ar = OSCALAssessmentResult.objects.create(
            catalog=catalog,
            team=team,
            title="Will be deleted",
            created_by=sample_user,
        )
        ar_pk = ar.pk
        team.delete()
        assert not OSCALAssessmentResult.objects.filter(pk=ar_pk).exists()

    def test_catalog_protect(self, assessment_result, catalog):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            catalog.delete()


@pytest.mark.django_db
class TestOSCALFinding:
    def test_create_finding(self, finding, assessment_result, control):
        assert finding.pk is not None
        assert len(finding.pk) == 12
        assert finding.assessment_result == assessment_result
        assert finding.control == control
        assert finding.status == "satisfied"
        assert finding.notes == "Control fully implemented."
        assert finding.updated_at is not None

    def test_str(self, finding):
        assert str(finding) == "cra-sd-1: satisfied"

    def test_unique_together_assessment_control(self, finding, assessment_result, control):
        with pytest.raises(IntegrityError), transaction.atomic():
            OSCALFinding.objects.create(
                assessment_result=assessment_result,
                control=control,
                status="not-satisfied",
            )

    def test_status_choices(self, assessment_result, control):
        # The finding fixture already uses "satisfied"; test the others
        catalog = control.catalog
        statuses = ["not-satisfied", "not-applicable", "unanswered"]
        for i, status in enumerate(statuses):
            ctrl = OSCALControl.objects.create(
                catalog=catalog,
                control_id=f"test-{i}",
                group_id="test",
                group_title="Test",
                title=f"Test {i}",
                description="",
                sort_order=10 + i,
            )
            f = OSCALFinding.objects.create(
                assessment_result=assessment_result,
                control=ctrl,
                status=status,
            )
            assert f.status == status

    def test_default_status(self, assessment_result):
        catalog = assessment_result.catalog
        ctrl = OSCALControl.objects.create(
            catalog=catalog, control_id="def-1", group_id="def",
            group_title="Defaults", title="Default test",
            description="", sort_order=99,
        )
        f = OSCALFinding.objects.create(
            assessment_result=assessment_result,
            control=ctrl,
        )
        assert f.status == "unanswered"
        assert f.notes == ""

    def test_control_protect(self, finding, control):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            control.delete()

    def test_assessment_result_cascade(self, finding, assessment_result):
        assessment_result.delete()
        assert not OSCALFinding.objects.filter(pk=finding.pk).exists()


@pytest.mark.django_db
class TestOSCALObservation:
    def test_create_observation(self, finding):
        obs = OSCALObservation.objects.create(
            finding=finding,
            description="Reviewed source code for secure defaults.",
            method="EXAMINE",
        )
        assert obs.pk is not None
        assert len(obs.pk) == 12
        assert obs.finding == finding
        assert obs.description == "Reviewed source code for secure defaults."
        assert obs.method == "EXAMINE"
        assert obs.evidence_document is None
        assert obs.collected_at is not None

    def test_str(self, finding):
        obs = OSCALObservation.objects.create(
            finding=finding,
            description="Interviewed developer",
            method="INTERVIEW",
        )
        assert str(obs) == "INTERVIEW observation for cra-sd-1: satisfied"

    def test_method_choices(self, finding):
        for method in ["EXAMINE", "INTERVIEW", "TEST"]:
            obs = OSCALObservation.objects.create(
                finding=finding,
                description=f"Test {method}",
                method=method,
            )
            assert obs.method == method

    def test_finding_cascade(self, finding):
        obs = OSCALObservation.objects.create(
            finding=finding,
            description="Will be deleted",
            method="TEST",
        )
        finding.delete()
        assert not OSCALObservation.objects.filter(pk=obs.pk).exists()
