"""Tests for component visibility and gating logic."""

import pytest
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import (
    setup_authenticated_client_session,
)
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member


@pytest.fixture
def public_component(team_with_business_plan):
    """Create a public component."""
    return Component.objects.create(
        name="Public Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.BOM,
        visibility=Component.Visibility.PUBLIC,
    )


@pytest.fixture
def private_component(team_with_business_plan):
    """Create a private component."""
    return Component.objects.create(
        name="Private Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.BOM,
        visibility=Component.Visibility.PRIVATE,
    )


@pytest.fixture
def gated_component(team_with_business_plan):
    """Create a gated component."""
    return Component.objects.create(
        name="Gated Component",
        team=team_with_business_plan,
        component_type=Component.ComponentType.BOM,
        visibility=Component.Visibility.GATED,
    )


@pytest.mark.django_db
class TestComponentVisibility:
    """Test component visibility rules."""

    def test_public_component_access_unauthenticated(self, client, public_component):
        """Test that public components are accessible to everyone."""
        url = reverse("core:component_details_public", kwargs={"component_id": public_component.id})
        response = client.get(url)
        assert response.status_code == 200
        assert "Public Component" in str(response.content)

    def test_private_component_no_access_public(self, client, private_component):
        """Test that private components are NOT accessible via public URL."""
        url = reverse("core:component_details_public", kwargs={"component_id": private_component.id})
        response = client.get(url)
        # Should be 403 or 404 depending on implementation, but definitely not 200
        assert response.status_code in [403, 404]

    def test_gated_component_access_unauthenticated(self, client, gated_component):
        """Test that gated components are accessible but show restriction UI."""
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = client.get(url)
        assert response.status_code == 200
        # Should show gated notice
        assert b"Gated Component" in response.content
        assert b"Request Access" in response.content

    def test_gated_component_access_authenticated_no_access(
        self, client, team_with_business_plan, gated_component, guest_user
    ):
        """Test gated component view for authenticated user WITHOUT access."""
        client.force_login(guest_user)
        
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = client.get(url)
        
        assert response.status_code == 200
        # Should show request access button
        assert b"Request Access" in response.content
        assert b"Gated Component" in response.content

    def test_gated_component_access_authenticated_pending_request(
        self, client, team_with_business_plan, gated_component, guest_user
    ):
        """Test gated component view with PENDING access request."""
        # Create pending request
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.PENDING,
        )
        
        client.force_login(guest_user)
        
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = client.get(url)
        
        assert response.status_code == 200
        assert b"Access Request Pending" in response.content

    def test_gated_component_access_authenticated_with_access(
        self, authenticated_web_client, team_with_business_plan, gated_component, guest_user
    ):
        """Test gated component access for user WITH access (guest member)."""
        # Grant access (guest membership + approved request)
        AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED,
        )
        Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")
        
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, guest_user)
        
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = authenticated_web_client.get(url)
        
        assert response.status_code == 200
        # Should NOT show request access buttons
        assert b"Request Access" not in response.content
        assert b"Access Request Pending" not in response.content
        
        # Should show 'Access Granted' or simply render content without restriction overlay
        # Note: The specific UI verify depends on template implementation
        assert response.context["user_has_gated_access"] is True


@pytest.mark.django_db
class TestAPendingRequestAndTheCurrentNDA:
    """A workspace that replaces its NDA leaves the old signatures live, by design.

    The pending-request block on the public component page reads liveness to
    decide whether it still owes the reader a signature. Scoped to the current
    NDA now: reading liveness alone reported a reader as done with a document
    they had never seen, and left the page with nothing to offer them.
    """

    def _nda(self, team, name: str):
        """A document the workspace can point `company_nda_document_id` at."""
        component = Component.objects.create(
            name=f"{name} holder",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
            visibility=Component.Visibility.PRIVATE,
        )
        return Document.objects.create(
            component=component,
            name=name,
            document_filename=f"{name}.pdf",
            content_type="application/pdf",
            source="manual_upload",
        )

    def _require(self, team, nda):
        team.branding_info = {**(team.branding_info or {}), "company_nda_document_id": nda.id}
        team.save(update_fields=["branding_info"])

    def _sign(self, access_request, nda):
        return NDASignature.objects.create(
            access_request=access_request,
            nda_document=nda,
            nda_content_hash="0" * 64,
            signed_name="Guest User",
            ip_address="203.0.113.1",
        )

    def _pending(self, team, user):
        return AccessRequest.objects.create(team=team, user=user, status=AccessRequest.Status.PENDING)

    def test_a_signature_on_a_superseded_nda_still_owes_the_current_one(
        self, client, team_with_business_plan, gated_component, guest_user
    ):
        old_nda = self._nda(team_with_business_plan, "NDA v1")
        pending = self._pending(team_with_business_plan, guest_user)
        self._sign(pending, old_nda)
        self._require(team_with_business_plan, self._nda(team_with_business_plan, "NDA v2"))

        client.force_login(guest_user)
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = client.get(url)

        assert response.status_code == 200
        assert response.context["pending_request_needs_nda"] is True
        assert b"NDA Required" in response.content

    def test_a_signature_on_the_current_nda_asks_for_nothing_further(
        self, client, team_with_business_plan, gated_component, guest_user
    ):
        current_nda = self._nda(team_with_business_plan, "NDA v1")
        pending = self._pending(team_with_business_plan, guest_user)
        self._sign(pending, current_nda)
        self._require(team_with_business_plan, current_nda)

        client.force_login(guest_user)
        url = reverse("core:component_details_public", kwargs={"component_id": gated_component.id})
        response = client.get(url)

        assert response.status_code == 200
        assert response.context["pending_request_needs_nda"] is False
        assert b"NDA Required" not in response.content
