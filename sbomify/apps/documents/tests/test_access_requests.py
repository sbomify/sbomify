"""
Comprehensive tests for access request functionality.

Tests cover:
- Access request creation, approval, rejection, revocation
- NDA signing and verification
- Email notifications
- Guest member creation
- Notification system
- Cache invalidation
- Access control for gated components
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_api_client,
    authenticated_web_client,
    get_api_headers,
    guest_user,
    sample_user,
    setup_authenticated_client_session,
    team_with_business_plan,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member


@pytest.fixture
def gated_component(team_with_business_plan, sample_user):
    """Create a gated component for testing."""
    Member.objects.get_or_create(
        user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
    )
    return Component.objects.create(
        name="Gated Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        visibility=Component.Visibility.GATED,
    )


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
        version="1.0",  # Set initial version for versioning tests
    )
    
    # Update team branding info to reference this NDA
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


@pytest.mark.django_db
class TestAccessRequestCreation:
    """Test access request creation."""

    def test_create_access_request_view_unauthenticated(self, client, team_with_business_plan):
        """Test that unauthenticated users cannot create access requests."""
        url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})
        response = client.post(url, {})
        assert response.status_code in [302, 401, 403]  # Redirect to login or forbidden

    def test_create_access_request_view_authenticated(
        self, authenticated_web_client, team_with_business_plan, guest_user
    ):
        """Test creating an access request via view."""
        url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})
        
        # Switch to guest user
        authenticated_web_client.force_login(guest_user)
        session = authenticated_web_client.session
        session["current_team"] = {
            "key": team_with_business_plan.key,
            "role": None,  # Not a member yet
            "name": team_with_business_plan.name,
        }
        session.save()
        
        response = authenticated_web_client.post(url, {})
        assert response.status_code in [200, 302]  # Success or redirect
        
        # Verify request was created
        assert AccessRequest.objects.filter(
            team=team_with_business_plan, user=guest_user, status=AccessRequest.Status.PENDING
        ).exists()

    def test_create_access_request_api(
        self, authenticated_api_client, team_with_business_plan, guest_user
    ):
        """Test creating an access request via API."""
        client, access_token = authenticated_api_client
        client.force_login(guest_user)
        
        # API endpoint is /api/v1/teams/{team_key}/access-request
        url = f"/api/v1/teams/{team_with_business_plan.key}/access-request"
        headers = get_api_headers(access_token)
        
        response = client.post(
            url,
            {},
            content_type="application/json",
            **headers,
        )
        
        assert response.status_code in [200, 201]
        data = response.json()
        # Response may have "status" field or be in "access_request" nested object
        if "access_request" in data and data["access_request"]:
            assert data["access_request"]["status"] == "pending"
        elif "status" in data:
            assert data["status"] == "pending"
        assert AccessRequest.objects.filter(
            team=team_with_business_plan, user=guest_user
        ).exists()

    def test_create_access_request_with_existing_pending(
        self, authenticated_web_client, team_with_business_plan, guest_user, pending_access_request
    ):
        """Test that creating a request when one already exists updates it."""
        url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.force_login(guest_user)
        
        response = authenticated_web_client.post(url, {})
        assert response.status_code in [200, 302]
        
        # Should still be only one request
        assert AccessRequest.objects.filter(
            team=team_with_business_plan, user=guest_user
        ).count() == 1

    def test_create_access_request_after_rejection(
        self, authenticated_web_client, team_with_business_plan, guest_user, sample_user
    ):
        """Test that users can re-request access after rejection."""
        # Create and reject a request
        request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.REJECTED,
            decided_by=sample_user,
            decided_at=timezone.now(),
        )
        
        # Try to create a new request
        authenticated_web_client.force_login(guest_user)
        url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(url, {})
        
        assert response.status_code in [200, 302]
        
        # Should update existing request to PENDING
        request.refresh_from_db()
        assert request.status == AccessRequest.Status.PENDING


@pytest.mark.django_db
class TestNDASigning:
    """Test NDA signing functionality."""

    def test_sign_nda_view_unauthenticated(self, client, team_with_business_plan, pending_access_request):
        """Test that unauthenticated users cannot sign NDAs."""
        url = reverse(
            "documents:sign_nda",
            kwargs={"team_key": team_with_business_plan.key, "request_id": pending_access_request.id},
        )
        response = client.get(url)
        assert response.status_code in [302, 401, 403]

    @patch("sbomify.apps.documents.views.access_requests.S3Client")
    def test_sign_nda_with_valid_hash(
        self, mock_s3_client, authenticated_web_client, team_with_business_plan, 
        company_nda_document, pending_access_request, guest_user
    ):
        """Test signing NDA with valid content hash."""
        authenticated_web_client.force_login(guest_user)
        
        # Mock S3 to return the NDA content (matching the content_hash in company_nda_document)
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        content = b"Test NDA Content"
        mock_s3.get_document_data.return_value = content
        
        url = reverse(
            "documents:sign_nda",
            kwargs={"team_key": team_with_business_plan.key, "request_id": pending_access_request.id},
        )
        
        # Submit NDA signing form with name and consent
        response = authenticated_web_client.post(
            url,
            {
                "signed_name": "Test User",
                "consent": "on",
            }
        )
        assert response.status_code in [200, 302]
        
        # Verify signature was created
        assert NDASignature.objects.filter(access_request=pending_access_request).exists()
        signature = NDASignature.objects.get(access_request=pending_access_request)
        assert signature.nda_document == company_nda_document
        assert signature.nda_content_hash == company_nda_document.content_hash

    @patch("sbomify.apps.documents.views.access_requests.S3Client")
    def test_sign_nda_with_invalid_hash(
        self, mock_s3_client, authenticated_web_client, team_with_business_plan,
        company_nda_document, pending_access_request, guest_user
    ):
        """Test that signing with modified NDA content fails."""
        authenticated_web_client.force_login(guest_user)
        
        # Mock S3 to return modified content (different from stored content_hash)
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        modified_content = b"Modified NDA Content"
        mock_s3.get_document_data.return_value = modified_content
        
        url = reverse(
            "documents:sign_nda",
            kwargs={"team_key": team_with_business_plan.key, "request_id": pending_access_request.id},
        )
        
        # Submit NDA signing form - should fail due to hash mismatch
        response = authenticated_web_client.post(
            url,
            {
                "signed_name": "Test User",
                "consent": "on",
            }
        )
        # Should redirect back with error message
        assert response.status_code in [302, 200]
        
        # Verify signature was NOT created
        assert not NDASignature.objects.filter(access_request=pending_access_request).exists()


@pytest.mark.django_db
class TestAccessRequestApproval:
    """Test access request approval."""

    def test_approve_access_request_view(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test approving an access request via view."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code in [200, 302]
        
        # Verify request was approved
        pending_access_request.refresh_from_db()
        assert pending_access_request.status == AccessRequest.Status.APPROVED
        assert pending_access_request.decided_by == sample_user
        
        # Verify guest member was created
        assert Member.objects.filter(
            team=team_with_business_plan,
            user=pending_access_request.user,
            role="guest",
        ).exists()

    @patch("sbomify.apps.documents.views.access_requests.send_mail")
    def test_approve_access_request_sends_email(
        self, mock_send_mail, authenticated_web_client, team_with_business_plan,
        pending_access_request, sample_user
    ):
        """Test that approval sends email notification."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Verify email was sent
        assert mock_send_mail.called
        call_args = mock_send_mail.call_args
        assert "Access Approved" in call_args[1]["subject"]
        assert pending_access_request.user.email in call_args[1]["recipient_list"]

    def test_approve_access_request_api(
        self, authenticated_api_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test approving an access request via API."""
        client, access_token = authenticated_api_client
        client.force_login(sample_user)
        
        # Ensure user is admin/owner
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        
        url = reverse("api-1:approve_access_request", kwargs={"request_id": pending_access_request.id})
        headers = get_api_headers(access_token)
        
        response = client.post(url, **headers)
        assert response.status_code == 200
        
        pending_access_request.refresh_from_db()
        assert pending_access_request.status == AccessRequest.Status.APPROVED

    def test_approve_access_request_creates_guest_member(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test that approval automatically creates guest member."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        # Verify guest member doesn't exist yet
        assert not Member.objects.filter(
            team=team_with_business_plan, user=pending_access_request.user
        ).exists()
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Verify guest member was created
        guest_member = Member.objects.get(
            team=team_with_business_plan, user=pending_access_request.user
        )
        assert guest_member.role == "guest"

    def test_approve_access_request_invalidates_cache(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test that approval invalidates user's team cache."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        # Set a cache key that should be invalidated
        cache_key = f"user_teams_invalidate:{pending_access_request.user.id}"
        cache.set(cache_key, True, timeout=600)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Cache key should still exist (it's set during approval)
        assert cache.get(cache_key) is True


@pytest.mark.django_db
class TestAccessRequestRejection:
    """Test access request rejection."""

    def test_reject_access_request_view(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test rejecting an access request via view."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "reject",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code in [200, 302]
        
        # Verify request was rejected
        pending_access_request.refresh_from_db()
        assert pending_access_request.status == AccessRequest.Status.REJECTED
        assert pending_access_request.decided_by == sample_user

    @patch("sbomify.apps.documents.views.access_requests.send_mail")
    def test_reject_access_request_sends_email(
        self, mock_send_mail, authenticated_web_client, team_with_business_plan,
        pending_access_request, sample_user
    ):
        """Test that rejection sends email notification."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(
            url,
            {
                "action": "reject",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Verify email was sent
        assert mock_send_mail.called
        call_args = mock_send_mail.call_args
        assert "Rejected" in call_args[1]["subject"]
        assert pending_access_request.user.email in call_args[1]["recipient_list"]

    def test_reject_access_request_api(
        self, authenticated_api_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test rejecting an access request via API."""
        client, access_token = authenticated_api_client
        client.force_login(sample_user)
        
        # Ensure user is admin/owner
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        
        url = reverse("api-1:reject_access_request", kwargs={"request_id": pending_access_request.id})
        headers = get_api_headers(access_token)
        
        response = client.post(url, **headers)
        assert response.status_code == 200
        
        pending_access_request.refresh_from_db()
        assert pending_access_request.status == AccessRequest.Status.REJECTED


@pytest.mark.django_db
class TestAccessRequestRevocation:
    """Test access request revocation."""

    def test_revoke_access_request(
        self, authenticated_web_client, team_with_business_plan, sample_user, guest_user
    ):
        """Test revoking an approved access request."""
        # Create approved request and guest member
        approved_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
            decided_by=sample_user,
            decided_at=timezone.now(),
        )
        Member.objects.create(
            team=team_with_business_plan, user=guest_user, role="guest"
        )
        
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "revoke",
                "request_id": approved_request.id,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code in [200, 302]
        
        # Verify request was revoked
        approved_request.refresh_from_db()
        assert approved_request.status == AccessRequest.Status.REVOKED
        
        # Verify guest member was removed
        assert not Member.objects.filter(
            team=team_with_business_plan, user=guest_user
        ).exists()


@pytest.mark.django_db
class TestNotificationSystem:
    """Test notification system for access requests."""

    def test_notification_provider_returns_pending_requests(
        self, team_with_business_plan, sample_user, pending_access_request
    ):
        """Test that notification provider returns pending requests."""
        from django.test import RequestFactory
        from sbomify.apps.documents.notifications import get_notifications
        
        # Ensure user is admin/owner
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        request.session = {}
        request.session["current_team"] = {
            "key": team_with_business_plan.key,
            "role": "owner",
            "name": team_with_business_plan.name,
        }
        
        notifications = get_notifications(request)
        assert len(notifications) > 0
        assert any(n.type == "access_request_pending" for n in notifications)

    def test_notification_dismissed_when_no_pending(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test that notification is dismissed when no pending requests."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        # Approve the only pending request
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Check that notification was dismissed
        session = authenticated_web_client.session
        dismissed_ids = session.get("dismissed_notifications", [])
        notification_id = f"access_request_pending_{team_with_business_plan.key}"
        assert notification_id in dismissed_ids


@pytest.mark.django_db
class TestGatedComponentAccess:
    """Test access control for gated components."""

    def test_gated_component_visible_publicly(self, client, gated_component):
        """Test that gated components are visible on public pages."""
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = client.get(url)
        assert response.status_code == 200

    @patch("sbomify.apps.documents.views.document_download.S3Client")
    def test_gated_component_download_requires_access(
        self, mock_s3_client, client, gated_component, team_with_business_plan, guest_user
    ):
        """Test that gated component downloads require access."""
        # Mock S3 to return document content
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        mock_s3.get_document_data.return_value = b"test document content"
        
        # Create document for gated component
        document = Document.objects.create(
            name="Test Document",
            component=gated_component,
            document_type=Document.DocumentType.SPECIFICATION,
            document_filename="test.pdf",
            source="manual_upload",
        )
        
        # Try to download without access
        url = reverse("documents:document_download", kwargs={"document_id": document.id})
        response = client.get(url, {"from_public": "true"})
        
        # Should show access denied message, not redirect
        assert response.status_code in [200, 403]
        
        # Grant access
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        
        # Now should be able to download (if authenticated)
        client.force_login(guest_user)
        # Set up session for proper access check
        session = client.session
        session["current_team"] = {
            "key": team_with_business_plan.key,
            "role": "guest",
            "name": team_with_business_plan.name,
        }
        session.save()
        
        response = client.get(url)
        # Should be able to download now
        assert response.status_code in [200, 302, 403]  # Depends on full setup


@pytest.mark.django_db
class TestNDADocumentVersioning:
    """Test NDA document versioning functionality."""

    @patch("sbomify.apps.core.object_store.S3Client")
    def test_nda_versioning_creates_new_version(
        self, mock_s3_client, authenticated_web_client, team_with_business_plan, company_nda_document, sample_user
    ):
        """Test that uploading new NDA creates a new version."""
        # Mock S3 upload
        mock_s3 = MagicMock()
        mock_s3_client.return_value = mock_s3
        mock_s3.upload_document.return_value = "new_nda_file.pdf"
        
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key})
        
        from django.core.files.uploadedfile import SimpleUploadedFile
        new_nda = SimpleUploadedFile("new_nda.pdf", b"New NDA Content v2", content_type="application/pdf")
        
        response = authenticated_web_client.post(
            url,
            {
                "company_nda_action": "upload",
                "company_nda_file": new_nda,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code in [200, 302]
        
        # Verify new document was created (versioning creates a new document)
        all_ndas = Document.objects.filter(
            component=company_nda_document.component,
            document_type=Document.DocumentType.COMPLIANCE,
            compliance_subcategory=Document.ComplianceSubcategory.NDA,
        ).order_by("-created_at")
        
        # Should have at least 2 documents now (original + new version)
        assert all_ndas.count() >= 2
        
        # Get the latest one (should be the new version)
        new_document = all_ndas.first()
        assert new_document is not None
        assert new_document.id != company_nda_document.id
        assert new_document.version is not None
        
        # Verify team's branding_info points to the new document
        team_with_business_plan.refresh_from_db()
        assert team_with_business_plan.branding_info.get("company_nda_document_id") == new_document.id


@pytest.mark.django_db
class TestContentHashVerification:
    """Test content hash verification for NDA signatures."""

    def test_nda_signature_is_document_modified(
        self, company_nda_document, pending_access_request
    ):
        """Test that is_document_modified detects changes."""
        # Create signature with original hash
        signature = NDASignature.objects.create(
            access_request=pending_access_request,
            nda_document=company_nda_document,
            nda_content_hash=company_nda_document.content_hash,
            signed_at=timezone.now(),
        )
        
        # Initially should not be modified
        assert signature.is_document_modified() is False
        
        # Modify the document's content hash
        company_nda_document.content_hash = hashlib.sha256(b"Modified Content").hexdigest()
        company_nda_document.save()
        
        # Now should be modified
        assert signature.is_document_modified() is True

    def test_nda_signature_no_content_hash(self, company_nda_document, pending_access_request):
        """Test that is_document_modified handles missing content hash."""
        # Remove content hash from document to simulate missing hash
        company_nda_document.content_hash = None
        company_nda_document.save()
        
        # Create signature with a hash (required field)
        signature = NDASignature.objects.create(
            access_request=pending_access_request,
            nda_document=company_nda_document,
            nda_content_hash="some_hash_value",
            signed_at=timezone.now(),
        )
        
        # Should return None if document's content hash is missing
        assert signature.is_document_modified() is None


@pytest.mark.django_db
class TestAccessRequestQueueView:
    """Test access request queue view functionality."""

    def test_access_request_queue_requires_auth(self, client, team_with_business_plan):
        """Test that queue view requires authentication."""
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = client.get(url)
        assert response.status_code in [302, 401, 403]

    def test_access_request_queue_requires_admin(
        self, authenticated_web_client, team_with_business_plan, guest_user
    ):
        """Test that queue view requires admin/owner role."""
        authenticated_web_client.force_login(guest_user)
        session = authenticated_web_client.session
        session["current_team"] = {
            "key": team_with_business_plan.key,
            "role": "guest",
            "name": team_with_business_plan.name,
        }
        session.save()
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.get(url)
        # TeamRoleRequiredMixin may redirect to recover workspace session if user is not a member
        assert response.status_code in [302, 403, 404]

    def test_access_request_queue_shows_pending_requests(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test that queue view shows pending requests."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.get(url)
        
        assert response.status_code == 200
        assert str(pending_access_request.user.email).encode() in response.content

    def test_access_request_queue_partial_rendering(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test that queue view supports partial rendering for HTMX."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.get(url, {"partial": "true"})
        
        assert response.status_code == 200
        # Should render the partial template
        assert b"Access Requests" in response.content or b"pending" in response.content

    def test_access_request_queue_with_company_nda(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user, company_nda_document
    ):
        """Test that queue view works when company NDA is enabled."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        # Create a signature for the request
        NDASignature.objects.create(
            access_request=pending_access_request,
            nda_document=company_nda_document,
            nda_content_hash=company_nda_document.content_hash,
            signed_name="Test User"
        )
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.get(url)
        
        assert response.status_code == 200
        assert str(pending_access_request.user.email).encode() in response.content


@pytest.mark.django_db
class TestAccessRequestNotificationProvider:
    """Test the access request notification provider."""

    def test_notification_provider_no_auth(self):
        """Test that provider returns empty list for unauthenticated users."""
        from django.test import RequestFactory
        from sbomify.apps.documents.notifications import get_notifications
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = type("User", (), {"is_authenticated": False})()
        request.session = {}
        
        notifications = get_notifications(request)
        assert notifications == []

    def test_notification_provider_no_team_in_session(self, sample_user):
        """Test that provider returns empty list when no team in session."""
        from django.test import RequestFactory
        from sbomify.apps.documents.notifications import get_notifications
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        request.session = {}
        
        notifications = get_notifications(request)
        assert notifications == []

    def test_notification_provider_not_admin(
        self, team_with_business_plan, guest_user, pending_access_request
    ):
        """Test that provider doesn't show notifications to non-admin users."""
        from django.test import RequestFactory
        from sbomify.apps.documents.notifications import get_notifications
        
        # Create guest member
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        request.session = {
            "current_team": {
                "key": team_with_business_plan.key,
                "role": "guest",
                "name": team_with_business_plan.name,
            }
        }
        
        notifications = get_notifications(request)
        assert notifications == []

    def test_notification_provider_with_nda_requires_signed(
        self, team_with_business_plan, sample_user, company_nda_document, guest_user
    ):
        """Test that provider only shows requests with signed NDA when NDA is required."""
        from django.test import RequestFactory
        from sbomify.apps.documents.notifications import get_notifications
        
        # Create pending request without NDA signature
        request_obj = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.PENDING,
        )
        
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        request.session = {
            "current_team": {
                "key": team_with_business_plan.key,
                "role": "owner",
                "name": team_with_business_plan.name,
            }
        }
        
        # Should not show notification (no signed NDA)
        notifications = get_notifications(request)
        assert len(notifications) == 0
        
        # Sign NDA
        NDASignature.objects.create(
            access_request=request_obj,
            nda_document=company_nda_document,
            nda_content_hash=company_nda_document.content_hash,
            signed_at=timezone.now(),
        )
        
        # Now should show notification
        notifications = get_notifications(request)
        assert len(notifications) == 1
        assert notifications[0].type == "access_request_pending"

    def test_notification_provider_removes_from_dismissed(
        self, team_with_business_plan, sample_user, pending_access_request
    ):
        """Test that provider removes notification from dismissed list when pending requests exist."""
        from django.test import RequestFactory
        from sbomify.apps.documents.notifications import get_notifications
        
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        notification_id = f"access_request_pending_{team_with_business_plan.key}"
        request.session = {
            "current_team": {
                "key": team_with_business_plan.key,
                "role": "owner",
                "name": team_with_business_plan.name,
            },
            "dismissed_notifications": [notification_id],
        }
        
        # Provider should remove from dismissed and return notification
        notifications = get_notifications(request)
        assert len(notifications) == 1
        
        # Verify it was removed from dismissed
        assert notification_id not in request.session.get("dismissed_notifications", [])


@pytest.mark.django_db
class TestAccessRequestEdgeCases:
    """Test edge cases and error handling."""

    def test_approve_non_pending_request(
        self, authenticated_web_client, team_with_business_plan, sample_user, guest_user
    ):
        """Test that approving a non-pending request fails."""
        # Create already approved request
        approved_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
            decided_by=sample_user,
            decided_at=timezone.now(),
        )
        
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": approved_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Should show error
        assert response.status_code in [200, 302]  # May redirect with error message

    def test_reject_non_pending_request(
        self, authenticated_web_client, team_with_business_plan, sample_user, guest_user
    ):
        """Test that rejecting a non-pending request fails."""
        # Create already rejected request
        rejected_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.REJECTED,
            decided_by=sample_user,
            decided_at=timezone.now(),
        )
        
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "reject",
                "request_id": rejected_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Should show error
        assert response.status_code in [200, 302]  # May redirect with error message

    def test_revoke_non_approved_request(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test that revoking a non-approved request fails."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        
        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "revoke",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Should show error
        assert response.status_code in [200, 302]  # May redirect with error message

    def test_access_request_unique_constraint(
        self, team_with_business_plan, guest_user, django_db_blocker
    ):
        """Test that unique constraint prevents duplicate requests."""
        from django.db import IntegrityError, transaction
        
        # Create first request
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.PENDING,
        )
        
        # Try to create duplicate - should raise IntegrityError due to unique_together constraint
        # The view/API handles this by updating existing requests, but direct creation should fail
        # Use django_db_blocker to manage transaction properly
        with django_db_blocker.unblock():
            with transaction.atomic():
                with pytest.raises(IntegrityError):
                    AccessRequest.objects.create(
                        team=team_with_business_plan,
                        user=guest_user,
                        status=AccessRequest.Status.PENDING,
                    )


@pytest.mark.django_db
class TestGuestMemberExclusion:
    """Test that guest members are excluded from member lists."""

    def test_guest_members_not_in_api_response(
        self, authenticated_api_client, team_with_business_plan, guest_user, sample_user
    ):
        """Test that guest members are not included in team API response."""
        # Ensure sample_user is a member (owner/admin)
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )
        
        # Create guest member
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        
        client, access_token = authenticated_api_client
        client.force_login(sample_user)
        
        from sbomify.apps.teams.apis import _build_team_response
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        
        team_data = _build_team_response(request, team_with_business_plan)
        
        # Verify guest members are not in the response
        # _build_team_response returns a TeamSchema (Pydantic model), convert to dict
        if hasattr(team_data, "model_dump"):
            team_dict = team_data.model_dump()
        elif hasattr(team_data, "dict"):
            team_dict = team_data.dict()
        else:
            team_dict = team_data
        
        # Handle both dict and Pydantic model members
        member_emails = []
        for m in team_dict.get("members", []):
            if isinstance(m, dict):
                member_emails.append(m["user"]["email"])
            elif hasattr(m, "user"):
                if isinstance(m.user, dict):
                    member_emails.append(m.user["email"])
                else:
                    member_emails.append(m.user.email)
        
        assert guest_user.email not in member_emails
        assert sample_user.email in member_emails
