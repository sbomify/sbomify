"""Unit tests for Component visibility and access control methods."""

import hashlib

import pytest
from sbomify.apps.core.tests.shared_fixtures import (
    guest_user,
    team_with_business_plan,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def member_user(django_user_model):
    """Create a regular member user."""
    return django_user_model.objects.create_user(
        username="member", email="member@example.com", password="password", first_name="Member", last_name="User"
    )

@pytest.fixture
def owner_user(django_user_model):
    """Create an owner user."""
    return django_user_model.objects.create_user(
        username="owner", email="owner@example.com", password="password", first_name="Owner", last_name="User"
    )

@pytest.fixture
def public_component(team_with_business_plan):
    """Create a public component."""
    return Component.objects.create(
        name="Public Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        visibility=Component.Visibility.PUBLIC,
    )

@pytest.fixture
def private_component(team_with_business_plan):
    """Create a private component."""
    return Component.objects.create(
        name="Private Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        visibility=Component.Visibility.PRIVATE,
    )

@pytest.fixture
def gated_component(team_with_business_plan):
    """Create a gated component."""
    return Component.objects.create(
        name="Gated Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        visibility=Component.Visibility.GATED,
    )

@pytest.fixture
def gated_component_with_nda(team_with_business_plan):
    """Create a gated component that requires NDA."""
    # Get or create company-wide component for NDA
    component = team_with_business_plan.get_or_create_company_wide_component()
    
    # Create NDA document
    content = b"Company NDA Content"
    content_hash = hashlib.sha256(content).hexdigest()
    nda_doc = Document.objects.create(
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
    # Update branding info to simulate team configuration
    team_with_business_plan.branding_info["company_nda_document_id"] = nda_doc.id
    team_with_business_plan.save()

    return Component.objects.create(
        name="Gated Component with NDA",
        team=team_with_business_plan,
        component_type=Component.ComponentType.SBOM,
        visibility=Component.Visibility.GATED,
    )

@pytest.mark.django_db
class TestComponentAccessMethods:
    """Test Component access control methods."""

    def test_can_be_accessed_by_public(self, public_component, guest_user):
        """Public components can be accessed by anyone (even unauthenticated, handled in view usually)."""
        # can_be_accessed_by logic:
        # if public -> True
        assert public_component.can_be_accessed_by(None) is True
        assert public_component.can_be_accessed_by(guest_user) is True

    def test_can_be_accessed_by_private(
        self, private_component, team_with_business_plan, owner_user, member_user, guest_user
    ):
        """Private components are only accessible by team owners/admins."""
        Member.objects.create(team=team_with_business_plan, user=owner_user, role="owner")
        Member.objects.create(team=team_with_business_plan, user=member_user, role="member") # Regular member? 
        # Note: logic says if member.role in ("owner", "admin"). Regular "member" usually can see private? 
        # Let's check implementation of can_be_accessed_by for PRIVATE:
        # member.role in ("owner", "admin") -> True. "member" role -> False?
        # Re-checking implementation from step 14 diff:
        # if self.visibility == self.Visibility.PRIVATE: ... member.role in ("owner", "admin")

        assert private_component.can_be_accessed_by(None) is False
        assert private_component.can_be_accessed_by(guest_user) is False # Not member
        assert private_component.can_be_accessed_by(owner_user) is True
        assert private_component.can_be_accessed_by(member_user) is False # Based on current implementation

    def test_can_be_accessed_by_gated(
        self, gated_component, team_with_business_plan, owner_user, guest_user
    ):
        """Gated components check for guest access or owner permissions."""
        assert gated_component.can_be_accessed_by(None) is False
        assert gated_component.can_be_accessed_by(guest_user) is False # Not member, no request

        # Add as owner
        Member.objects.create(team=team_with_business_plan, user=owner_user, role="owner")
        assert gated_component.can_be_accessed_by(owner_user) is True

        # Add guest as guest member
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        assert gated_component.can_be_accessed_by(guest_user) is True
    
    def test_can_be_accessed_by_gated_with_approved_request(
        self, gated_component, team_with_business_plan, guest_user
    ):
        """Gated component accessible via approved AccessRequest."""
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED
        )
        # Even if not a member yet (though typically they become guest member on approval)
        assert gated_component.can_be_accessed_by(guest_user) is True

    def test_user_has_gated_access_check(
        self, gated_component, team_with_business_plan, owner_user, guest_user
    ):
        """Test specific user_has_gated_access logic."""
        # Unauthenticated
        assert gated_component.user_has_gated_access(None) is False
        
        # User with no relation
        assert gated_component.user_has_gated_access(guest_user) is False

        # Owner has access
        Member.objects.create(team=team_with_business_plan, user=owner_user, role="owner")
        assert gated_component.user_has_gated_access(owner_user) is True

    def test_user_has_gated_access_needs_nda(
        self, gated_component_with_nda, team_with_business_plan, guest_user
    ):
        """Test gated access when NDA is required."""
        # User is guest member (implicit access usually)
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        
        # Without signature -> False
        assert gated_component_with_nda.user_has_gated_access(guest_user) is False

        # With signature -> True
        # Need to create signature
        # Logic: user_has_signed_current_nda checks AccessRequest with signature
        access_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED
        )
        nda_doc = Document.objects.get(id=team_with_business_plan.branding_info["company_nda_document_id"])
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=nda_doc,
            nda_content_hash=nda_doc.content_hash,
            signed_name="Test User",
            ip_address="127.0.0.1"
        )
        
        assert gated_component_with_nda.user_has_gated_access(guest_user) is True

