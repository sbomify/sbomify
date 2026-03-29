"""Tests for the CRA Compliance API endpoints."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sbomify.apps.compliance.models import (
    OSCALFinding,
)
from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
from sbomify.apps.core.models import Product
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact


@pytest.fixture
def product(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return Product.objects.create(name="API Test Product", team=team)


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product):
    team = sample_team_with_owner_member.team
    result = get_or_create_assessment(product.id, sample_user, team)
    assert result.ok
    return result.value


@pytest.fixture
def assessment_with_contacts(sample_team_with_owner_member, sample_user, product):
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
    a = result.value
    a.intended_use = "Home automation"
    a.target_eu_markets = ["DE", "FR"]
    a.vdp_url = "https://acme.test/vdp"
    a.support_email = "support@acme.test"
    a.save()
    return a


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _disable_billing(settings):
    settings.BILLING = False


class TestCreateOrGetAssessment:
    def test_creates_assessment(self, authenticated_api_client, product):
        client, token = authenticated_api_client

        response = client.post(
            f"/api/v1/compliance/cra/product/{product.id}",
            **get_api_headers(token),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["product_id"] == product.id
        assert data["status"] == "draft"
        assert data["current_step"] == 1

    def test_returns_existing_assessment(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.post(
            f"/api/v1/compliance/cra/product/{assessment.product_id}",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["id"] == assessment.id

    def test_404_for_nonexistent_product(self, authenticated_api_client):
        client, token = authenticated_api_client

        response = client.post(
            "/api/v1/compliance/cra/product/nonexistent",
            **get_api_headers(token),
        )

        assert response.status_code == 404


class TestGetAssessment:
    def test_returns_assessment(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == assessment.id
        assert data["product_name"] == "API Test Product"

    def test_404_for_nonexistent(self, authenticated_api_client):
        client, token = authenticated_api_client

        response = client.get(
            "/api/v1/compliance/cra/nonexistent",
            **get_api_headers(token),
        )

        assert response.status_code == 404


class TestGetStepContext:
    def test_returns_step_1_context(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/step/1",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["step"] == 1
        assert "data" in data
        assert data["is_complete"] is False

    def test_400_for_invalid_step(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/step/99",
            **get_api_headers(token),
        )

        assert response.status_code == 400


class TestSaveStepData:
    def test_saves_step_1(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.patch(
            f"/api/v1/compliance/cra/{assessment.id}/step/1",
            data=json.dumps({"data": {"product_category": "default", "intended_use": "Testing"}}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert 1 in data["completed_steps"]
        assert data["status"] == "in_progress"

    def test_400_for_invalid_step(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.patch(
            f"/api/v1/compliance/cra/{assessment.id}/step/99",
            data=json.dumps({"data": {}}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 400


class TestGetSBOMStatus:
    def test_returns_sbom_status(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/sbom-status",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert "components" in data
        assert "summary" in data


class TestUpdateFinding:
    def test_updates_finding_status(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()

        response = client.put(
            f"/api/v1/compliance/cra/{assessment.id}/findings/{finding.id}",
            data=json.dumps({"status": "satisfied", "notes": "Implemented"}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "satisfied"
        assert data["notes"] == "Implemented"

    def test_404_for_nonexistent_finding(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.put(
            f"/api/v1/compliance/cra/{assessment.id}/findings/nonexistent",
            data=json.dumps({"status": "satisfied"}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 404

    def test_400_for_invalid_status(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()

        response = client.put(
            f"/api/v1/compliance/cra/{assessment.id}/findings/{finding.id}",
            data=json.dumps({"status": "bogus"}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 422  # Pydantic rejects invalid Literal value


class TestCreateObservation:
    def test_creates_observation(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()

        response = client.post(
            f"/api/v1/compliance/cra/{assessment.id}/findings/{finding.id}/observations",
            data=json.dumps(
                {
                    "description": "Manual code review completed",
                    "method": "EXAMINE",
                }
            ),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["description"] == "Manual code review completed"
        assert data["method"] == "EXAMINE"

    def test_400_for_invalid_method(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client
        finding = OSCALFinding.objects.filter(assessment_result=assessment.oscal_assessment_result).first()

        response = client.post(
            f"/api/v1/compliance/cra/{assessment.id}/findings/{finding.id}/observations",
            data=json.dumps(
                {
                    "description": "Test",
                    "method": "INVALID_METHOD",
                }
            ),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 422  # Pydantic rejects invalid Literal value


class TestGenerateDocument:
    @patch("sbomify.apps.core.object_store.StorageClient")
    def test_generates_vdp(self, mock_s3_cls, authenticated_api_client, assessment_with_contacts):
        client, token = authenticated_api_client

        response = client.post(
            f"/api/v1/compliance/cra/{assessment_with_contacts.id}/generate/vdp",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["document_kind"] == "vdp"
        assert data["version"] == 1

    def test_400_for_invalid_kind(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.post(
            f"/api/v1/compliance/cra/{assessment.id}/generate/bogus",
            **get_api_headers(token),
        )

        assert response.status_code == 400


class TestPreviewDocument:
    def test_returns_preview_content(self, authenticated_api_client, assessment_with_contacts):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment_with_contacts.id}/documents/vdp/preview",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "Vulnerability Disclosure Policy" in data["content"]

    def test_400_for_invalid_kind(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/documents/bogus/preview",
            **get_api_headers(token),
        )

        assert response.status_code == 400


class TestCreateExport:
    @patch("sbomify.apps.compliance.services.export_service.StorageClient")
    @patch("sbomify.apps.core.object_store.StorageClient")
    @patch("sbomify.apps.compliance.services.export_service._get_generated_doc_content")
    def test_creates_export_package(
        self, mock_get_content, mock_s3_cls, mock_export_s3_cls, authenticated_api_client, assessment_with_contacts
    ):
        mock_get_content.return_value = b"mock content"

        # Mark steps 1-4 complete and answer all findings (required for export)
        assessment_with_contacts.completed_steps = [1, 2, 3, 4]
        assessment_with_contacts.save(update_fields=["completed_steps"])

        from sbomify.apps.compliance.models import OSCALFinding

        OSCALFinding.objects.filter(
            assessment_result=assessment_with_contacts.oscal_assessment_result,
        ).update(status="satisfied")

        # Generate docs first (with S3 mocked)
        from sbomify.apps.compliance.services.document_generation_service import regenerate_all

        regenerate_all(assessment_with_contacts)

        client, token = authenticated_api_client

        response = client.post(
            f"/api/v1/compliance/cra/{assessment_with_contacts.id}/export",
            **get_api_headers(token),
        )

        assert response.status_code == 201
        data = response.json()
        assert "content_hash" in data
        assert "manifest" in data


class TestDownloadExport:
    def test_404_for_nonexistent_package(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/export/nonexistent/download",
            **get_api_headers(token),
        )

        assert response.status_code == 404


class TestStaleness:
    def test_returns_staleness_info(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/staleness",
            **get_api_headers(token),
        )

        assert response.status_code == 200


class TestRefreshStale:
    def test_refresh_with_no_stale_docs(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client

        response = client.post(
            f"/api/v1/compliance/cra/{assessment.id}/refresh",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["refreshed_count"] == 0


class TestOSCALExport:
    def test_returns_oscal_json(self, authenticated_api_client, assessment):
        client, token = authenticated_api_client
        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/oscal-export",
            **get_api_headers(token),
        )
        assert response.status_code == 200
        data = response.json()
        assert "assessment-results" in data

    def test_404_for_nonexistent_assessment(self, authenticated_api_client):
        client, token = authenticated_api_client
        response = client.get(
            "/api/v1/compliance/cra/nonexistent/oscal-export",
            **get_api_headers(token),
        )
        assert response.status_code == 404


class TestBillingGateAPI:
    """Test billing gate on API endpoints with BILLING enabled."""

    @pytest.fixture(autouse=True)
    def _enable_billing(self, settings):
        settings.BILLING = True

    def test_create_assessment_blocked_on_community_plan(self, authenticated_api_client, team_with_community_plan):
        client, token = authenticated_api_client
        product = Product.objects.create(name="Billing API Test", team=team_with_community_plan)
        response = client.post(
            f"/api/v1/compliance/cra/product/{product.id}",
            **get_api_headers(token),
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "billing_gate"
