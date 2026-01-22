"""
Tests for Component model deprecated methods.

These tests verify backward compatibility of deprecated access control methods
while ensuring they delegate to the centralized access control service.
"""

import hashlib

import pytest

from sbomify.apps.core.tests.shared_fixtures import guest_user, sample_user, team_with_business_plan
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
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


@pytest.mark.django_db
class TestComponentCanBeAccessedBy:
    """Test Component.can_be_accessed_by deprecated method."""

    def test_public_component_unauthenticated(self, team_with_business_plan):
        """Test public component access for unauthenticated user."""
        component = Component.objects.create(
            name="Public Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PUBLIC,
        )

        assert component.can_be_accessed_by(None, team_with_business_plan) is True

    def test_public_component_authenticated(self, sample_user, team_with_business_plan):
        """Test public component access for authenticated user."""
        component = Component.objects.create(
            name="Public Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PUBLIC,
        )

        assert component.can_be_accessed_by(sample_user, team_with_business_plan) is True

    def test_private_component_unauthenticated(self, team_with_business_plan):
        """Test private component access for unauthenticated user."""
        component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PRIVATE,
        )

        assert component.can_be_accessed_by(None, team_with_business_plan) is False

    def test_private_component_owner(self, sample_user, team_with_business_plan):
        """Test private component access for owner."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PRIVATE,
        )

        assert component.can_be_accessed_by(sample_user, team_with_business_plan) is True

    def test_private_component_guest(self, guest_user, team_with_business_plan):
        """Test private component access for guest (should be denied)."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

        component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PRIVATE,
        )

        assert component.can_be_accessed_by(guest_user, team_with_business_plan) is False

    def test_gated_component_unauthenticated(self, team_with_business_plan):
        """Test gated component access for unauthenticated user."""
        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.can_be_accessed_by(None, team_with_business_plan) is False

    def test_gated_component_owner(self, sample_user, team_with_business_plan):
        """Test gated component access for owner."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.can_be_accessed_by(sample_user, team_with_business_plan) is True

    def test_gated_component_guest_with_access(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test gated component access for guest with approved request and signed NDA."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        access_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=company_nda_document,
            nda_content_hash=company_nda_document.content_hash,
            signed_name="Test User",
        )

        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.can_be_accessed_by(guest_user, team_with_business_plan) is True

    def test_gated_component_guest_no_access(self, guest_user, team_with_business_plan):
        """Test gated component access for guest without access."""
        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.can_be_accessed_by(guest_user, team_with_business_plan) is False

    def test_uses_component_team_if_not_provided(self, sample_user, team_with_business_plan):
        """Test that method uses component.team if team parameter is not provided."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PRIVATE,
        )

        assert component.can_be_accessed_by(sample_user) is True


@pytest.mark.django_db
class TestComponentUserHasGatedAccess:
    """Test Component.user_has_gated_access deprecated method."""

    def test_unauthenticated_user(self, team_with_business_plan):
        """Test gated access for unauthenticated user."""
        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.user_has_gated_access(None, team_with_business_plan) is False

    def test_owner_has_gated_access(self, sample_user, team_with_business_plan):
        """Test that owner has gated access."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.user_has_gated_access(sample_user, team_with_business_plan) is True

    def test_guest_with_approved_request(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test that guest with approved request and signed NDA has gated access."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        access_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=company_nda_document,
            nda_content_hash=company_nda_document.content_hash,
            signed_name="Test User",
        )

        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.user_has_gated_access(guest_user, team_with_business_plan) is True

    def test_guest_without_access(self, guest_user, team_with_business_plan):
        """Test that guest without access does not have gated access."""
        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.user_has_gated_access(guest_user, team_with_business_plan) is False

    def test_uses_component_team_if_not_provided(self, sample_user, team_with_business_plan):
        """Test that method uses component.team if team parameter is not provided."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        assert component.user_has_gated_access(sample_user) is True
