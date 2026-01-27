"""
Comprehensive tests for access request API endpoints.

Tests cover:
- List access requests (pending, approved)
- Approve/reject/revoke via API
- NDA signing via API
- Error handling and edge cases
"""

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_api_client,
    sample_user,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member


@pytest.fixture
def company_nda_document(team_with_business_plan):
    """Create a company-wide NDA document."""
    component = team_with_business_plan.get_or_create_company_wide_component()
    content = b"Test NDA Content"
    content_hash = hashlib.sha256(content).hexdigest()

    document = Document.objects.create(
        name="Company NDA",
        component=component,
        document_type=Document.DocumentType.COMPLIANCE,
        compliance_subcategory=Document.ComplianceSubcategory.NDA,
        document_filename="nda.pdf",
        content_type="application/pdf",
        file_size=len(content),
        content_hash=content_hash,
        source="manual_upload",
        version="1.0",
    )

    team_with_business_plan.branding_info["company_nda_document_id"] = document.id
    team_with_business_plan.save()

    return document


@pytest.fixture
def pending_access_request(team_with_business_plan, guest_user):
    """Create a pending access request."""
    return AccessRequest.objects.create(
        team=team_with_business_plan,
        user=guest_user,
        status=AccessRequest.Status.PENDING,
    )


@pytest.fixture
def approved_access_request(team_with_business_plan, guest_user, sample_user):
    """Create an approved access request."""
    return AccessRequest.objects.create(
        team=team_with_business_plan,
        user=guest_user,
        status=AccessRequest.Status.APPROVED,
        decided_by=sample_user,
    )


@pytest.mark.django_db
class TestListAccessRequestsAPI:
    """Test list access requests API."""

    def test_list_pending_requests(
        self, authenticated_api_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test listing pending access requests."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse("api-1:list_pending_access_requests")

        response = client.get(url, **headers)

        assert response.status_code == 200
        data = response.json()
        # API returns list directly, not wrapped in {"items": [...]}
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(item["id"] == str(pending_access_request.id) for item in data)

    def test_list_approved_requests(
        self, authenticated_api_client, team_with_business_plan, approved_access_request, sample_user
    ):
        """Test listing approved access requests."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse("api-1:list_pending_access_requests")

        response = client.get(url, **headers)

        assert response.status_code == 200
        data = response.json()
        # API returns list directly, not wrapped in {"items": [...]}
        # Note: list_pending_access_requests only returns pending requests
        # Approved requests are not included in this endpoint
        assert isinstance(data, list)
        # Approved request should not be in pending list
        assert not any(item["id"] == str(approved_access_request.id) for item in data)

    def test_list_requires_admin(
        self, authenticated_api_client, team_with_business_plan, guest_user
    ):
        """Test that listing requires admin role."""
        # Guest user might not have access token, so create one
        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.access_tokens.utils import create_personal_access_token
        
        token_str = create_personal_access_token(guest_user)
        access_token = AccessToken.objects.create(user=guest_user, encoded_token=token_str, description="Test API Token")
        
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

        client, _ = authenticated_api_client
        client.force_login(guest_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse("api-1:list_pending_access_requests")

        response = client.get(url, **headers)

        assert response.status_code == 403


@pytest.mark.django_db
class TestApproveAccessRequestAPI:
    """Test approve access request API."""

    def test_approve_pending_request(
        self, authenticated_api_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test approving a pending access request."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:approve_access_request",
            kwargs={"request_id": pending_access_request.id},
        )

        response = client.post(url, {}, content_type="application/json", **headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"

        pending_access_request.refresh_from_db()
        assert pending_access_request.status == AccessRequest.Status.APPROVED

    def test_approve_creates_guest_member(
        self, authenticated_api_client, team_with_business_plan, pending_access_request, sample_user, guest_user
    ):
        """Test that approving creates a guest member."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:approve_access_request",
            kwargs={"request_id": pending_access_request.id},
        )

        response = client.post(url, {}, content_type="application/json", **headers)

        assert response.status_code == 200

        # Verify guest member was created
        member = Member.objects.filter(team=team_with_business_plan, user=guest_user).first()
        assert member is not None
        assert member.role == "guest"

    def test_approve_non_pending_request(
        self, authenticated_api_client, team_with_business_plan, approved_access_request, sample_user
    ):
        """Test that approving a non-pending request fails."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:approve_access_request",
            kwargs={"request_id": approved_access_request.id},
        )

        response = client.post(url, {}, content_type="application/json", **headers)

        # The endpoint should return 400 for non-pending requests
        assert response.status_code == 400


@pytest.mark.django_db
class TestRejectAccessRequestAPI:
    """Test reject access request API."""

    def test_reject_pending_request(
        self, authenticated_api_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test rejecting a pending access request."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:reject_access_request",
            kwargs={"request_id": pending_access_request.id},
        )

        response = client.post(url, {}, content_type="application/json", **headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

        pending_access_request.refresh_from_db()
        assert pending_access_request.status == AccessRequest.Status.REJECTED


@pytest.mark.django_db
class TestRevokeAccessRequestAPI:
    """Test revoke access request API."""

    def test_revoke_approved_request(
        self, authenticated_api_client, team_with_business_plan, approved_access_request, sample_user, guest_user
    ):
        """Test revoking an approved access request."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:revoke_access_request",
            kwargs={"request_id": approved_access_request.id},
        )

        response = client.post(url, {}, content_type="application/json", **headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "revoked"

        approved_access_request.refresh_from_db()
        assert approved_access_request.status == AccessRequest.Status.REVOKED

        # Verify guest member was removed
        member = Member.objects.filter(team=team_with_business_plan, user=guest_user).first()
        assert member is None


@pytest.mark.django_db
class TestSignNDAAPI:
    """Test sign NDA API."""

    @patch("sbomify.apps.documents.access_apis.S3Client")
    def test_sign_nda_with_valid_hash(
        self,
        mock_s3_client,
        authenticated_api_client,
        team_with_business_plan,
        pending_access_request,
        company_nda_document,
        guest_user,
    ):
        """Test signing NDA with valid content hash."""
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        mock_s3.get_document_data.return_value = b"Test NDA Content"

        client, access_token = authenticated_api_client
        client.force_login(guest_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:sign_nda",
            kwargs={
                "team_key": team_with_business_plan.key,
                "request_id": pending_access_request.id,
            },
        )

        response = client.post(
            url,
            json.dumps({"signed_name": "Test User", "consent": True}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "signed_name" in data

        # Verify signature was created
        signature = NDASignature.objects.filter(access_request=pending_access_request).first()
        assert signature is not None
        assert signature.nda_document == company_nda_document

    @patch("sbomify.apps.documents.access_apis.S3Client")
    def test_sign_nda_with_invalid_hash(
        self,
        mock_s3_client,
        authenticated_api_client,
        team_with_business_plan,
        pending_access_request,
        company_nda_document,
        guest_user,
    ):
        """Test signing NDA without consent."""
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        mock_s3.get_document_data.return_value = b"Test NDA Content"
        
        client, access_token = authenticated_api_client
        client.force_login(guest_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:sign_nda",
            kwargs={
                "team_key": team_with_business_plan.key,
                "request_id": pending_access_request.id,
            },
        )

        response = client.post(
            url,
            json.dumps({"signed_name": "Test User", "consent": False}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400

    @patch("sbomify.apps.documents.access_apis.S3Client")
    def test_sign_nda_captures_correct_ip_with_proxy(
        self,
        mock_s3_client,
        authenticated_api_client,
        team_with_business_plan,
        pending_access_request,
        company_nda_document,
        guest_user,
    ):
        """Test that NDA signing captures the correct client IP from X-Real-IP header."""
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        mock_s3.get_document_data.return_value = b"Test NDA Content"

        client, access_token = authenticated_api_client
        client.force_login(guest_user)

        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}",
            "HTTP_X_REAL_IP": "203.0.113.42",  # Client IP set by reverse proxy
        }
        url = reverse(
            "api-1:sign_nda",
            kwargs={
                "team_key": team_with_business_plan.key,
                "request_id": pending_access_request.id,
            },
        )

        response = client.post(
            url,
            json.dumps({"signed_name": "Test User", "consent": True}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200

        # Verify signature captures the correct IP from X-Real-IP header
        signature = NDASignature.objects.filter(access_request=pending_access_request).first()
        assert signature is not None
        assert signature.ip_address == "203.0.113.42"

    @patch("sbomify.apps.documents.access_apis.S3Client")
    def test_sign_nda_falls_back_to_remote_addr_without_proxy(
        self,
        mock_s3_client,
        authenticated_api_client,
        team_with_business_plan,
        pending_access_request,
        company_nda_document,
        guest_user,
    ):
        """Test that NDA signing falls back to REMOTE_ADDR when X-Real-IP is not set."""
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        mock_s3.get_document_data.return_value = b"Test NDA Content"

        client, access_token = authenticated_api_client
        client.force_login(guest_user)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse(
            "api-1:sign_nda",
            kwargs={
                "team_key": team_with_business_plan.key,
                "request_id": pending_access_request.id,
            },
        )

        response = client.post(
            url,
            json.dumps({"signed_name": "Test User", "consent": True}),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 200

        # Verify signature captures an IP (the test client's REMOTE_ADDR)
        signature = NDASignature.objects.filter(access_request=pending_access_request).first()
        assert signature is not None
        # Django test client sets REMOTE_ADDR to 127.0.0.1 by default
        assert signature.ip_address is not None
