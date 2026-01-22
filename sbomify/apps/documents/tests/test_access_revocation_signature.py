
import hashlib
import pytest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_web_client,
    setup_authenticated_client_session,
    team_with_business_plan,
    sample_user,
    guest_user,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member

@pytest.fixture
def nda_document(team_with_business_plan):
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
def signed_access_request(team_with_business_plan, guest_user, nda_document, sample_user):
    """Create an approved access request with a signature."""
    request = AccessRequest.objects.create(
        team=team_with_business_plan,
        user=guest_user,
        status=AccessRequest.Status.APPROVED,
        decided_by=sample_user,
        decided_at=timezone.now(),
    )
    # Add guest member
    Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
    
    # Sign NDA
    NDASignature.objects.create(
        access_request=request,
        nda_document=nda_document,
        nda_content_hash=nda_document.content_hash,
        signed_name="Guest User",
    )
    return request

@pytest.mark.django_db
class TestAccessRevocationSignature:
    """Test NDA signature lifecycle during revocation and rejection."""

    def test_revoke_via_queue_deletes_signature(
        self, authenticated_web_client, team_with_business_plan, signed_access_request, sample_user
    ):
        """Test that revoking an access request deletes the associated NDA signature."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        # Ensure user is owner
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        signature_id = signed_access_request.nda_signature.id
        assert NDASignature.objects.filter(id=signature_id).exists()

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "revoke",
                "request_id": signed_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code == 302
        
        # Verify request is revoked
        signed_access_request.refresh_from_db()
        assert signed_access_request.status == AccessRequest.Status.REVOKED
        
        # Verify signature is deleted
        assert not NDASignature.objects.filter(id=signature_id).exists()

    def test_reject_via_queue_deletes_signature(
        self, authenticated_web_client, team_with_business_plan, guest_user, nda_document, sample_user
    ):
        """Test that rejecting an access request (which might have a signature) deletes it."""
        # Create a pending request with signature (simulating user signed before approval or something)
        # Assuming the flow allows signature on pending request
        request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.PENDING,
        )
        signature = NDASignature.objects.create(
            access_request=request,
            nda_document=nda_document,
            nda_content_hash=nda_document.content_hash,
            signed_name="Guest User",
        )
        
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(
            url,
            {
                "action": "reject",
                "request_id": request.id,
                "active_tab": "trust-center",
            },
        )
        
        request.refresh_from_db()
        assert request.status == AccessRequest.Status.REJECTED
        
        # Verify signature is deleted
        assert not NDASignature.objects.filter(id=signature.id).exists()

    def test_rerequest_after_revocation_deletes_residual_signature(
        self, authenticated_web_client, team_with_business_plan, guest_user, nda_document
    ):
        """Test that re-requesting after revocation cleans up any residual signature."""
        # Create a REVOKED request that still has a signature (simulating edge case or previous bug)
        request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.REVOKED,
        )
        signature = NDASignature.objects.create(
            access_request=request,
            nda_document=nda_document,
            nda_content_hash=nda_document.content_hash,
            signed_name="Guest User",
        )
        
        # Guest logs in and requests access again
        authenticated_web_client.force_login(guest_user)
        url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(url, {})
        
        assert response.status_code in [200, 302]
        
        request.refresh_from_db()
        assert request.status == AccessRequest.Status.PENDING
        
        # Verify residual signature was deleted
        assert not NDASignature.objects.filter(id=signature.id).exists()

    def test_rerequest_after_rejection_deletes_residual_signature(
        self, authenticated_web_client, team_with_business_plan, guest_user, nda_document
    ):
        """Test that re-requesting after rejection cleans up any residual signature."""
        request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.REJECTED,
        )
        signature = NDASignature.objects.create(
            access_request=request,
            nda_document=nda_document,
            nda_content_hash=nda_document.content_hash,
            signed_name="Guest User",
        )
        
        authenticated_web_client.force_login(guest_user)
        url = reverse("documents:request_access", kwargs={"team_key": team_with_business_plan.key})
        authenticated_web_client.post(url, {})
        
        request.refresh_from_db()
        assert request.status == AccessRequest.Status.PENDING
        
        assert not NDASignature.objects.filter(id=signature.id).exists()
