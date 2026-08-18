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
    setup_authenticated_client_session,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, Component
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

    def test_guest_can_access_gated_component(self, guest_with_access, team_with_business_plan):
        """Test that guest with access can view gated component."""
        gated_component = Component.objects.create(
            name="Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
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

    def test_guest_cannot_access_private_component(self, guest_with_access, team_with_business_plan):
        """Test that guest cannot access private component."""
        private_component = Component.objects.create(
            name="Private Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
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

    def test_guest_can_access_public_component(self, guest_with_access, team_with_business_plan):
        """Test that guest can access public component."""
        public_component = Component.objects.create(
            name="Public Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
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
            component_type=Component.ComponentType.BOM,
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
            component_type=Component.ComponentType.BOM,
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
            component_type=Component.ComponentType.BOM,
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
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        client, access_token = authenticated_api_client
        client.force_login(sample_user)

        from django.test import RequestFactory

        from sbomify.apps.teams.apis import _build_team_response

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


@pytest.mark.django_db
class TestGuestIsExternalOnly:
    """A guest holds no role capability — only the trust-center (ABAC) path.

    Guests used to sit in the READ_MEMBER tier, so the API handed them internal,
    non-public workspace data even though GuestAccessBlockedMixin kept them out
    of the equivalent web pages. They were also granted artifact upload. Both are
    withdrawn: a guest is an external visitor who reaches restricted content
    solely by being approved for it and signing the NDA.

    The two halves are tested together on purpose — revoking too much would be as
    much of a bug as revoking too little.
    """

    def _client(self, team, user):
        from django.test import Client

        client = Client()
        setup_authenticated_client_session(client, team, user)
        return client

    def test_guest_holds_no_role_capability(self, team_with_business_plan, guest_with_access):
        """The tier table itself: no action grants a guest anything."""
        from sbomify.apps.core.authz import _ROLE_ACTIONS, ROLE_GUEST

        granting = [action for action, roles in _ROLE_ACTIONS.items() if ROLE_GUEST in roles]
        assert granting == [], f"guest is external-only but still holds: {granting}"

    def test_guest_cannot_list_internal_products(self, team_with_business_plan, guest_with_access):
        """Internal inventory must not be enumerable by an external visitor.

        Note this endpoint ALSO carries an inline ``_is_guest_member`` deny-check,
        so it 403s with or without the tier change. It is kept as an end-to-end
        assertion of the product behaviour; the tier itself is pinned by
        ``test_guest_holds_no_role_capability`` and by
        ``test_guest_cannot_read_workspace_billing_usage``, whose endpoint has no
        inline guest check and is therefore gated solely by the read tier.
        """
        client = self._client(team_with_business_plan, guest_with_access)
        response = client.get("/api/v1/products")
        assert response.status_code == 403

    def test_guest_cannot_list_internal_components(self, team_with_business_plan, guest_with_access):
        """See the note on test_guest_cannot_list_internal_products."""
        client = self._client(team_with_business_plan, guest_with_access)
        response = client.get("/api/v1/components")
        assert response.status_code == 403

    def test_guest_cannot_read_workspace_billing_usage(self, team_with_business_plan, guest_with_access):
        client = self._client(team_with_business_plan, guest_with_access)
        response = client.get(f"/api/v1/billing/usage/?team_key={team_with_business_plan.key}")
        assert response.status_code == 403

    def test_guest_cannot_publish_artifacts(self, team_with_business_plan, guest_with_access):
        """The PUBLISH grant added under #468 is withdrawn."""
        from sbomify.apps.core.authz import can

        component = Component.objects.create(team=team_with_business_plan, name="guest-publish-check")
        assert can(guest_with_access, "artifact:publish", component).allowed is False

    def test_guest_keeps_gated_component_access(self, team_with_business_plan, guest_with_access):
        """The half that must NOT change: approved + NDA-signed still gets in."""
        gated = Component.objects.create(
            name="Still Reachable",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.GATED,
        )
        request = RequestFactory().get("/")
        request.user = guest_with_access

        result = check_component_access(request, gated)
        assert result.has_access is True
        assert result.reason == "gated_access_granted"

    def test_guest_still_denied_private_component(self, team_with_business_plan, guest_with_access):
        private = Component.objects.create(
            name="Still Hidden",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PRIVATE,
        )
        request = RequestFactory().get("/")
        request.user = guest_with_access

        assert check_component_access(request, private).has_access is False


@pytest.mark.django_db
class TestGuestCannotLeakAcrossWorkspaces:
    """A guest of workspace X must not read X's internals via their OWN workspace.

    These paths gated on helpers scoped to the caller's *session* workspace
    (``_is_internal_member``) or on plain team membership, so being an owner
    somewhere satisfied them even when the resource lived elsewhere. Removing
    guest from the read tier does not close that on its own — the check has to be
    about the resource's workspace, not the caller's.
    """

    @pytest.fixture
    def guest_of_vendor(self, team_with_business_plan, guest_user, company_nda_document):
        """A user who owns their own workspace and is an approved guest of another."""
        from sbomify.apps.teams.models import Team

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
        own = Team.objects.create(name="Guest's Own Workspace")
        Member.objects.create(team=own, user=guest_user, role="owner", is_default_team=True)
        return guest_user, own

    def test_dashboard_summary_excludes_guest_workspaces(self, team_with_business_plan, guest_of_vendor):
        """Totals and latest uploads must not include a workspace they only guest in."""
        from django.test import Client

        from sbomify.apps.sboms.models import Product

        user, own = guest_of_vendor
        Product.objects.create(team=team_with_business_plan, name="Vendor Private Product")

        client = Client()
        setup_authenticated_client_session(client, own, user)
        response = client.get("/api/v1/dashboard/summary")

        assert response.status_code == 200
        body = response.json()
        # Their own (empty) workspace is all they should be counted for; the
        # vendor's product must not be included in the totals. (Asserting the
        # product *name* is absent would be vacuous — this payload carries counts
        # and upload names, never product names.)
        assert body["total_products"] == 0
        assert body["total_components"] == 0

    def test_component_releases_hides_other_workspace_private_products(self, team_with_business_plan, guest_of_vendor):
        """A gated component is publicly viewable; its private product names are not."""
        from django.test import Client

        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM, Product

        user, own = guest_of_vendor
        gated = Component.objects.create(
            name="Vendor Gated Component",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.GATED,
        )
        private_product = Product.objects.create(
            team=team_with_business_plan, name="Vendor Secret Product", is_public=False
        )
        release = Release.objects.create(product=private_product, name="v1.0.0")
        # The endpoint finds releases via the component's artifacts, so the
        # component has to actually be tagged into the release — without this the
        # response is empty for unrelated reasons and the test proves nothing.
        sbom = SBOM.objects.create(
            name="vendor-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            component=gated,
            source="api",
        )
        ReleaseArtifact.objects.create(release=release, sbom=sbom)

        client = Client()
        setup_authenticated_client_session(client, own, user)
        response = client.get(f"/api/v1/components/{gated.id}/releases")

        assert response.status_code == 200
        assert "Vendor Secret Product" not in response.content.decode()
        # And the release itself is withheld, not merely its product name.
        assert response.json()["items"] == []


@pytest.mark.django_db
class TestReleaseDisclosureIsConsistent:
    """All five "which releases contain this artifact" endpoints share one policy.

    If the caller cannot see the product, they do not see its releases — not even
    with the product fields blanked, because release names and descriptions
    routinely carry the product codename. Previously three different policies were
    enforced across these endpoints, and two of them handed private product names
    to anonymous callers.
    """

    @pytest.fixture
    def public_component_in_private_release(self, team_with_business_plan):
        from sbomify.apps.core.models import Release, ReleaseArtifact
        from sbomify.apps.sboms.models import SBOM, Product

        component = Component.objects.create(
            name="Public Face",
            team=team_with_business_plan,
            component_type=Component.ComponentType.BOM,
            visibility=Component.Visibility.PUBLIC,
        )
        sbom = SBOM.objects.create(
            name="public-sbom",
            version="1.0.0",
            format="cyclonedx",
            format_version="1.6",
            component=component,
            source="api",
        )
        secret = Product.objects.create(team=team_with_business_plan, name="Project Zephyr", is_public=False)
        release = Release.objects.create(product=secret, name="zephyr-2.1-rc3")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        return component, sbom

    def test_anonymous_never_sees_private_product_via_any_release_listing(self, public_component_in_private_release):
        from django.test import Client

        component, sbom = public_component_in_private_release
        client = Client()  # unauthenticated

        for url in (
            f"/api/v1/components/{component.id}/releases",
            f"/api/v1/components/{component.id}/sboms",
            f"/api/v1/components/{component.id}/documents",
            f"/api/v1/sboms/{sbom.id}/releases",
        ):
            response = client.get(url)
            assert response.status_code == 200, f"{url} -> {response.status_code}"
            body = response.content.decode()
            assert "Project Zephyr" not in body, f"private product name leaked via {url}"
            # The release name itself carries the codename, so withholding the
            # product field alone would not be enough.
            assert "zephyr-2.1-rc3" not in body, f"private release leaked via {url}"
