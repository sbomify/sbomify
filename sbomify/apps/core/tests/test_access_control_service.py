"""
Comprehensive tests for the centralized access control service.

Tests cover:
- check_component_access for all visibility levels
- _check_gated_access for various user roles and states
- _user_has_signed_current_nda with version changes
- Edge cases and error scenarios
"""

import hashlib
from unittest.mock import MagicMock, PropertyMock

import pytest
from django.test import RequestFactory

from sbomify.apps.core.services.access_control import (
    _check_gated_access,
    _user_has_signed_current_nda,
    check_component_access,
)
from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_web_client,
    guest_user,
    sample_user,
    team_with_business_plan,
)
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


@pytest.mark.django_db
class TestCheckComponentAccess:
    """Test check_component_access function."""

    def test_public_component_unauthenticated(self, client, public_component):
        """Test public component access for unauthenticated user."""
        factory = RequestFactory()
        request = factory.get("/")
        request.user = MagicMock()
        request.user.is_authenticated = False

        result = check_component_access(request, public_component)

        assert result.has_access is True
        assert result.reason == "public"
        assert result.requires_authentication is False
        assert result.requires_access_request is False

    def test_public_component_authenticated(self, sample_user, public_component):
        """Test public component access for authenticated user."""
        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, public_component)

        assert result.has_access is True
        assert result.reason == "public"

    def test_private_component_unauthenticated(self, client, private_component):
        """Test private component access for unauthenticated user."""
        factory = RequestFactory()
        request = factory.get("/")
        request.user = MagicMock()
        request.user.is_authenticated = False

        result = check_component_access(request, private_component)

        assert result.has_access is False
        assert result.reason == "private_requires_authentication"
        assert result.requires_authentication is True

    def test_private_component_owner_access(
        self, sample_user, team_with_business_plan, private_component
    ):
        """Test private component access for owner."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)
        request.session = {"current_team": {"id": team_with_business_plan.id, "key": team_with_business_plan.key}}

        result = check_component_access(request, private_component)

        assert result.has_access is True
        assert result.reason == "private_access_granted"

    def test_private_component_guest_denied(
        self, guest_user, team_with_business_plan, private_component
    ):
        """Test private component access denied for guest member."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)
        request.session = {"current_team": {"id": team_with_business_plan.id, "key": team_with_business_plan.key}}

        result = check_component_access(request, private_component)

        assert result.has_access is False
        assert result.reason == "private_access_denied"

    def test_gated_component_unauthenticated(self, client, gated_component):
        """Test gated component access for unauthenticated user."""
        factory = RequestFactory()
        request = factory.get("/")
        request.user = MagicMock()
        request.user.is_authenticated = False

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_requires_authentication"
        assert result.requires_access_request is True

    def test_gated_component_owner_access(
        self, sample_user, team_with_business_plan, gated_component
    ):
        """Test gated component access for owner (no NDA required)."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is True
        assert result.reason == "gated_access_granted"

    def test_gated_component_guest_with_approved_request(
        self, guest_user, team_with_business_plan, gated_component
    ):
        """Test gated component access for guest with approved request and signed NDA."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        # Should have access if NDA is signed (or no NDA required)
        assert result.has_access is True
        assert result.reason == "gated_access_granted"

    def test_gated_component_guest_needs_nda_re_sign(
        self, guest_user, team_with_business_plan, gated_component, company_nda_document
    ):
        """Test gated component access when guest needs to re-sign NDA."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        # Create old NDA signature (different document version)
        old_nda_content = b"Old NDA Content v0.9"
        old_nda_content_hash = hashlib.sha256(old_nda_content).hexdigest()
        old_nda = Document.objects.create(
            name="Old NDA",
            component=company_nda_document.component,
            document_type=Document.DocumentType.COMPLIANCE,
            compliance_subcategory=Document.ComplianceSubcategory.NDA,
            document_filename="nda_old.pdf",
            content_type="application/pdf",
            file_size=len(old_nda_content),
            content_hash=old_nda_content_hash,
            source="manual_upload",
            version="0.9",
        )
        old_request = AccessRequest.objects.get(team=team_with_business_plan, user=guest_user)
        NDASignature.objects.create(
            access_request=old_request,
            nda_document=old_nda,
            nda_content_hash=old_nda.content_hash,
            signed_name="Test User",
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_nda_re_sign_required"

    def test_gated_component_pending_request(
        self, guest_user, team_with_business_plan, gated_component
    ):
        """Test gated component access with pending request."""
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.PENDING,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_access_request_pending"
        assert result.access_request_status == AccessRequest.Status.PENDING

    def test_gated_component_rejected_request(
        self, guest_user, team_with_business_plan, gated_component
    ):
        """Test gated component access with rejected request."""
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.REJECTED,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_access_request_rejected"
        assert result.access_request_status == AccessRequest.Status.REJECTED

    def test_gated_component_no_request(
        self, guest_user, team_with_business_plan, gated_component
    ):
        """Test gated component access with no request."""
        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_user
        # Mock is_authenticated property
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is False
        assert result.reason == "gated_access_required"
        assert result.requires_access_request is True


@pytest.mark.django_db
class TestCheckGatedAccess:
    """Test _check_gated_access function."""

    def test_unauthenticated_user(self, team_with_business_plan):
        """Test _check_gated_access for unauthenticated user."""
        has_access, needs_nda_re_sign = _check_gated_access(None, team_with_business_plan)

        assert has_access is False
        assert needs_nda_re_sign is False

    def test_owner_access(self, sample_user, team_with_business_plan):
        """Test _check_gated_access for owner (no NDA required)."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        has_access, needs_nda_re_sign = _check_gated_access(sample_user, team_with_business_plan)

        assert has_access is True
        assert needs_nda_re_sign is False

    def test_admin_access(self, sample_user, team_with_business_plan):
        """Test _check_gated_access for admin (no NDA required)."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "admin"}
        )

        has_access, needs_nda_re_sign = _check_gated_access(sample_user, team_with_business_plan)

        assert has_access is True
        assert needs_nda_re_sign is False

    def test_guest_with_signed_nda(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test _check_gated_access for guest with signed NDA."""
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

        has_access, needs_nda_re_sign = _check_gated_access(guest_user, team_with_business_plan)

        assert has_access is True
        assert needs_nda_re_sign is False

    def test_guest_without_signed_nda(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test _check_gated_access for guest without signed NDA."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

        has_access, needs_nda_re_sign = _check_gated_access(guest_user, team_with_business_plan)

        assert has_access is False
        assert needs_nda_re_sign is True

    def test_guest_no_nda_required(self, guest_user, team_with_business_plan):
        """Test _check_gated_access for guest when no NDA is required."""
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

        has_access, needs_nda_re_sign = _check_gated_access(guest_user, team_with_business_plan)

        assert has_access is True
        assert needs_nda_re_sign is False

    def test_approved_request_with_signed_nda(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test _check_gated_access for non-member with approved request and signed NDA."""
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

        has_access, needs_nda_re_sign = _check_gated_access(guest_user, team_with_business_plan)

        assert has_access is True
        assert needs_nda_re_sign is False

    def test_approved_request_without_signed_nda(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test _check_gated_access for non-member with approved request but no signed NDA."""
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )

        has_access, needs_nda_re_sign = _check_gated_access(guest_user, team_with_business_plan)

        assert has_access is False
        assert needs_nda_re_sign is True

    def test_no_access_request(self, guest_user, team_with_business_plan):
        """Test _check_gated_access for user with no access request."""
        has_access, needs_nda_re_sign = _check_gated_access(guest_user, team_with_business_plan)

        assert has_access is False
        assert needs_nda_re_sign is False


@pytest.mark.django_db
class TestUserHasSignedCurrentNDA:
    """Test _user_has_signed_current_nda function."""

    def test_no_nda_required(self, sample_user, team_with_business_plan):
        """Test when no NDA is required."""
        result = _user_has_signed_current_nda(sample_user, team_with_business_plan)

        assert result is True

    def test_nda_signed(self, guest_user, team_with_business_plan, company_nda_document):
        """Test when user has signed current NDA."""
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

        result = _user_has_signed_current_nda(guest_user, team_with_business_plan)

        assert result is True

    def test_nda_not_signed(self, guest_user, team_with_business_plan, company_nda_document):
        """Test when user has not signed current NDA."""
        result = _user_has_signed_current_nda(guest_user, team_with_business_plan)

        assert result is False

    def test_old_nda_signed(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test when user has signed old NDA version but not current."""
        # Create old NDA document
        old_nda_content = b"Old NDA Content v0.9"
        old_nda_content_hash = hashlib.sha256(old_nda_content).hexdigest()
        old_nda = Document.objects.create(
            name="Old NDA",
            component=company_nda_document.component,
            document_type=Document.DocumentType.COMPLIANCE,
            compliance_subcategory=Document.ComplianceSubcategory.NDA,
            document_filename="nda_old.pdf",
            content_type="application/pdf",
            file_size=len(old_nda_content),
            content_hash=old_nda_content_hash,
            source="manual_upload",
            version="0.9",
        )

        access_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        # Sign old NDA
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=old_nda,
            nda_content_hash=old_nda.content_hash,
            signed_name="Test User",
        )

        result = _user_has_signed_current_nda(guest_user, team_with_business_plan)

        assert result is False

    def test_multiple_nda_versions(
        self, guest_user, team_with_business_plan, company_nda_document
    ):
        """Test when user has signed multiple NDA versions."""
        # Create old NDA
        old_nda_content = b"Old NDA Content v0.9"
        old_nda_content_hash = hashlib.sha256(old_nda_content).hexdigest()
        old_nda = Document.objects.create(
            name="Old NDA",
            component=company_nda_document.component,
            document_type=Document.DocumentType.COMPLIANCE,
            compliance_subcategory=Document.ComplianceSubcategory.NDA,
            document_filename="nda_old.pdf",
            content_type="application/pdf",
            file_size=len(old_nda_content),
            content_hash=old_nda_content_hash,
            source="manual_upload",
            version="0.9",
        )

        access_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        # Sign old NDA
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=old_nda,
            nda_content_hash=old_nda.content_hash,
            signed_name="Test User",
        )
        # Sign current NDA (replaces old due to OneToOneField)
        NDASignature.objects.filter(access_request=access_request).delete()
        NDASignature.objects.create(
            access_request=access_request,
            nda_document=company_nda_document,
            nda_content_hash=company_nda_document.content_hash,
            signed_name="Test User",
        )

        result = _user_has_signed_current_nda(guest_user, team_with_business_plan)

        assert result is True
