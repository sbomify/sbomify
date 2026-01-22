"""Tests for component visibility and gating logic."""

import pytest
from django.urls import reverse
from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_web_client,
    guest_user,
    sample_user,
    setup_authenticated_client_session,
    team_with_business_plan,
)
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member


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
