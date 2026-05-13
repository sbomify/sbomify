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
def _valid_manufacturer(sample_team_with_owner_member):
    """Configure a non-placeholder manufacturer so Step 1 save-path
    tests don't trip the Annex V item 2 server-side guard (#908)."""
    team = sample_team_with_owner_member.team
    # Don't collide with ``assessment_with_contacts`` which creates its
    # own ``Default`` profile; use a distinct name that still passes
    # the placeholder check.
    profile, _ = ContactProfile.objects.get_or_create(team=team, name="Default", defaults={"is_default": True})
    ContactEntity.objects.get_or_create(
        profile=profile,
        name="Acme Labs GmbH",
        defaults={"email": "legal@acmelabs.example", "is_manufacturer": True},
    )


@pytest.fixture
def assessment(sample_team_with_owner_member, sample_user, product, _valid_manufacturer):
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

    def test_cross_team_assessment_returns_404_not_403(self, authenticated_api_client, guest_user):
        """IDOR + enumeration-resistance: a real assessment owned by a
        different team must return 404, not 403. The 403-vs-404
        differential is what lets an attacker enumerate which 12-char
        assessment IDs exist across tenants."""
        from sbomify.apps.compliance.services.wizard_service import get_or_create_assessment
        from sbomify.apps.core.models import Product
        from sbomify.apps.teams.models import ContactEntity, ContactProfile, Member, Team

        # Build a parallel team+product+assessment owned by ``guest_user``
        # (which has no membership in the authenticated client's team).
        other_team = Team.objects.create(name="OtherTeam", key="OT01")
        Member.objects.create(user=guest_user, team=other_team, role="owner")
        profile = ContactProfile.objects.create(name="Default", team=other_team, is_default=True)
        ContactEntity.objects.create(
            profile=profile,
            name="Other Labs GmbH",
            email="legal@otherlabs.example",
            is_manufacturer=True,
        )
        other_product = Product.objects.create(name="Other Product", team=other_team)
        other_assessment = get_or_create_assessment(other_product.id, guest_user, other_team).value
        assert other_assessment is not None

        client, token = authenticated_api_client
        response = client.get(
            f"/api/v1/compliance/cra/{other_assessment.id}",
            **get_api_headers(token),
        )

        assert response.status_code == 404, (
            f"cross-team access must collapse to 404, not {response.status_code}; "
            "otherwise the API leaks which assessment IDs exist across tenants"
        )

    def test_same_team_insufficient_role_returns_403_not_404(
        self, sample_team_with_owner_member, sample_user, product, _valid_manufacturer
    ):
        """Role denials for users who ARE members of the team should
        surface as 403, not 404. The 404-for-cross-team collapse is a
        side-channel defence against ID enumeration; collapsing 403
        too would mask legitimate "you need a higher role" feedback
        from users who legitimately can see the resource.
        """
        from django.test import Client

        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import create_personal_access_token
        from sbomify.apps.core.models import User
        from sbomify.apps.teams.models import Member

        team = sample_team_with_owner_member.team
        assessment = get_or_create_assessment(product.id, sample_user, team).value
        assert assessment is not None

        # Second user joined the team as a guest (below the
        # ``(owner, admin)`` allowlist).
        guest = User.objects.create_user(username="guest_in_team", email="gi@test.local", password="x")
        Member.objects.create(user=guest, team=team, role="guest")
        token_str = create_personal_access_token(guest)
        token = AccessToken.objects.create(user=guest, encoded_token=token_str, description="guest-token")

        client = Client()
        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}",
            **get_api_headers(token),
        )
        assert response.status_code == 403, (
            f"same-team role denial must return 403, not {response.status_code}; "
            "collapsing role failures to 404 would mask the real reason"
        )
        # The two distinct 403 cases must be distinguishable via
        # error_code so an API client can tell a role denial from a
        # billing-gate denial without parsing messages.
        assert response.json()["error_code"] == "permission_denied"

    def test_billing_gate_returns_billing_error_code_not_permission_denied(
        self, authenticated_api_client, assessment
    ):
        """Both billing-gate and role-denial failures return 403, but
        they carry different ``error_code`` values so callers can
        discriminate. A regression that collapsed the two would mis-
        report a role failure as a billing problem (or vice versa) to
        every API client."""
        from sbomify.apps.core.tests.shared_fixtures import get_api_headers

        client, token = authenticated_api_client
        with patch("sbomify.apps.compliance.permissions.check_cra_access", return_value=False):
            response = client.get(
                f"/api/v1/compliance/cra/{assessment.id}",
                **get_api_headers(token),
            )
        assert response.status_code == 403
        assert response.json()["error_code"] == "billing_gate"


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
    @patch("sbomify.apps.core.object_store.S3Client")
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
    @patch("sbomify.apps.compliance.services.export_service.S3Client")
    @patch("sbomify.apps.core.object_store.S3Client")
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

    def test_404_response_carries_no_store_headers(self, authenticated_api_client, assessment):
        """Cache-Control must apply on the error path too — a shared
        cache (Caddy, corporate proxy) must not retain a 404 keyed on
        an assessment+package-id pair. Regression for #909."""
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/export/nonexistent/download",
            **get_api_headers(token),
        )

        assert response.status_code == 404
        assert response["Cache-Control"] == "no-store"
        assert response["Pragma"] == "no-cache"

    def test_403_response_carries_no_store_headers(self, authenticated_api_client, assessment):
        """The 403 path is the primary threat model the Cache-Control
        change addresses — a shared cache keyed on (Authorization,
        path) must not retain "this assessment exists, just not for
        you". Covers both the team-role 403 and the billing-gate 403
        by patching ``check_cra_access``."""
        client, token = authenticated_api_client

        # ``check_cra_access`` is now consumed inside
        # ``permissions.require_assessment_access``. Patch at the source
        # so the decision propagates through both API and view surfaces.
        with patch("sbomify.apps.compliance.permissions.check_cra_access", return_value=False):
            response = client.get(
                f"/api/v1/compliance/cra/{assessment.id}/export/anything/download",
                **get_api_headers(token),
            )

        assert response.status_code == 403
        assert response["Cache-Control"] == "no-store"
        assert response["Pragma"] == "no-cache"

    def test_200_response_carries_no_store_headers(self, authenticated_api_client, assessment, mock_s3_client):
        """Happy path: a successful download response must not be
        cacheable — the presigned URL inside would otherwise be served
        from an intermediate cache past its server-side expiry."""
        from sbomify.apps.compliance.models import CRAExportPackage

        package = CRAExportPackage.objects.create(
            assessment=assessment,
            storage_key=f"compliance/exports/{assessment.id}/test.zip",
            content_hash="0" * 64,
            manifest={"format_version": "1.0"},
        )
        client, token = authenticated_api_client

        response = client.get(
            f"/api/v1/compliance/cra/{assessment.id}/export/{package.id}/download",
            **get_api_headers(token),
        )

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        assert response["Pragma"] == "no-cache"

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
