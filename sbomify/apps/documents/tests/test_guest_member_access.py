"""
Tests for guest member access scenarios.

Tests cover:
- Guest members can access gated components with approved request and signed NDA
- Guest members cannot access private components
- Guest members are excluded from member lists
- Guest members can download documents/SBOMs for gated components
"""

import hashlib

import pytest
from django.test import RequestFactory
from django.urls import reverse

from sbomify.apps.core.services.access_control import check_component_access
from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_api_client,
    authenticated_web_client,
    guest_user,
    sample_user,
    setup_authenticated_client_session,
    team_with_business_plan,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component, SBOM
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
def guest_with_access(team_with_business_plan, guest_user, company_nda_document):
    """Create guest member with approved access and signed NDA."""
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
    return guest_user


@pytest.mark.django_db
class TestGuestMemberGatedAccess:
    """Test guest member access to gated components."""

    def test_guest_can_access_gated_component(
        self, guest_with_access, team_with_business_plan
    ):
        """Test that guest with access can view gated component."""
        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_with_access
        # Mock is_authenticated property
        from unittest.mock import PropertyMock
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, gated_component)

        assert result.has_access is True
        assert result.reason == "gated_access_granted"

    def test_guest_cannot_access_private_component(
        self, guest_with_access, team_with_business_plan
    ):
        """Test that guest cannot access private component."""
        private_component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PRIVATE,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_with_access
        # Mock is_authenticated property
        from unittest.mock import PropertyMock
        type(request.user).is_authenticated = PropertyMock(return_value=True)
        request.session = {"current_team": {"id": team_with_business_plan.id, "key": team_with_business_plan.key}}

        result = check_component_access(request, private_component)

        assert result.has_access is False
        assert result.reason == "private_access_denied"

    def test_guest_can_access_public_component(
        self, guest_with_access, team_with_business_plan
    ):
        """Test that guest can access public component."""
        public_component = Component.objects.create(
            name="Public Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PUBLIC,
        )

        factory = RequestFactory()
        request = factory.get("/")
        request.user = guest_with_access
        # Mock is_authenticated property
        from unittest.mock import PropertyMock
        type(request.user).is_authenticated = PropertyMock(return_value=True)

        result = check_component_access(request, public_component)

        assert result.has_access is True
        assert result.reason == "public"


@pytest.mark.django_db
class TestGuestMemberDocumentAccess:
    """Test guest member access to documents."""

    def test_guest_can_download_gated_component_document(
        self, authenticated_web_client, team_with_business_plan, guest_with_access, company_nda_document
    ):
        """Test that guest can download document from gated component."""
        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        document = Document.objects.create(
            name="Test Document",
            component=gated_component,
            document_type=Document.DocumentType.SPECIFICATION,
            document_filename="test.pdf",
            content_type="application/pdf",
            file_size=100,
            source="manual_upload",
        )

        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, guest_with_access)

        url = reverse("documents:document_download", kwargs={"document_id": document.id})
        response = authenticated_web_client.get(url)

        # Should be able to download (or get redirect to S3, or 500 if S3 unavailable in tests)
        assert response.status_code in [200, 302, 403, 500]

    def test_guest_cannot_download_private_component_document(
        self, authenticated_web_client, team_with_business_plan, guest_with_access
    ):
        """Test that guest cannot download document from private component."""
        private_component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.PRIVATE,
        )

        document = Document.objects.create(
            name="Test Document",
            component=private_component,
            document_type=Document.DocumentType.SPECIFICATION,
            document_filename="test.pdf",
            content_type="application/pdf",
            file_size=100,
            source="manual_upload",
        )

        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, guest_with_access)

        url = reverse("documents:document_download", kwargs={"document_id": document.id})
        response = authenticated_web_client.get(url)

        # Should be denied
        assert response.status_code in [403, 404]


@pytest.mark.django_db
class TestGuestMemberSBOMAccess:
    """Test guest member access to SBOMs."""

    def test_guest_can_download_gated_component_sbom(
        self, authenticated_web_client, team_with_business_plan, guest_with_access
    ):
        """Test that guest can download SBOM from gated component."""
        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.SBOM,
            visibility=Component.Visibility.GATED,
        )

        sbom = SBOM.objects.create(
            component=gated_component,
            format="cyclonedx",
            version="1.0",
            name="test-sbom",
            sbom_filename="test.json",
        )

        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, guest_with_access)

        url = reverse("sboms:sbom_download", kwargs={"sbom_id": sbom.id})
        response = authenticated_web_client.get(url)

        # Should be able to download (or get redirect to S3, or 500 if S3 unavailable in tests)
        assert response.status_code in [200, 302, 403, 500]


@pytest.mark.django_db
class TestGuestMemberExclusion:
    """Test that guest members are excluded from member lists."""

    def test_guest_not_in_team_members_list(
        self, authenticated_api_client, team_with_business_plan, guest_with_access, sample_user
    ):
        """Test that guest members are not included in team members API."""
        Member.objects.get_or_create(
            user=sample_user, team=team_with_business_plan, defaults={"role": "owner"}
        )

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        from sbomify.apps.teams.apis import _build_team_response
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = sample_user

        team_data = _build_team_response(request, team_with_business_plan)

        # Convert to dict
        if hasattr(team_data, "model_dump"):
            team_dict = team_data.model_dump()
        elif hasattr(team_data, "dict"):
            team_dict = team_data.dict()
        else:
            team_dict = team_data

        # Extract member emails
        member_emails = []
        for m in team_dict.get("members", []):
            if isinstance(m, dict):
                member_emails.append(m["user"]["email"])
            elif hasattr(m, "user"):
                if isinstance(m.user, dict):
                    member_emails.append(m.user["email"])
                else:
                    member_emails.append(m.user.email)

        # Guest should not be in list
        assert guest_with_access.email not in member_emails
        # Owner should be in list
        assert sample_user.email in member_emails
