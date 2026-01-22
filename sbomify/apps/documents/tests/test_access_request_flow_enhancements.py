"""Tests for Access Request UI flow enhancements (redirections, HTMX interactions)."""

import pytest
from django.urls import reverse
from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_web_client,
    setup_authenticated_client_session,
    team_with_business_plan,
    sample_user,
    guest_user,
)
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.teams.models import Member

@pytest.fixture
def pending_access_request(team_with_business_plan, guest_user):
    """Create a pending access request."""
    return AccessRequest.objects.create(
        team=team_with_business_plan,
        user=guest_user,
        status=AccessRequest.Status.PENDING,
    )

@pytest.mark.django_db
class TestAccessRequestFlowEnhancements:
    """Test specifics of the Access Request UI flow."""

    def test_approve_redirects_to_trust_center_with_trigger(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test approval redirects to Trust Center with HX-Trigger when active_tab is set."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        # Ensure user is owner
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        # Check redirection
        assert response.status_code == 302
        expected_url = reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key}) + "#trust-center"
        assert response.url == expected_url
        
        # Check HX-Trigger header
        assert "HX-Trigger" in response.headers
        assert response.headers["HX-Trigger"] == "refreshAccessRequests"

    def test_approve_redirects_to_queue_default(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test approval redirects to queue by default (no active_tab)."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "approve",
                "request_id": pending_access_request.id,
                # No active_tab
            },
        )
        
        # Check redirection
        assert response.status_code == 302
        expected_url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        assert response.url == expected_url
        
        # HX-Trigger usually not checking here, but key is logic difference

    def test_reject_redirects_to_trust_center_with_trigger(
        self, authenticated_web_client, team_with_business_plan, pending_access_request, sample_user
    ):
        """Test rejection redirects to Trust Center with HX-Trigger."""
        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "reject",
                "request_id": pending_access_request.id,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code == 302
        expected_url = reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key}) + "#trust-center"
        assert response.url == expected_url
        assert response.headers.get("HX-Trigger") == "refreshAccessRequests"

    def test_revoke_redirects_to_trust_center_with_trigger(
        self, authenticated_web_client, team_with_business_plan, guest_user, sample_user
    ):
        """Test revocation redirects to Trust Center with HX-Trigger."""
        # Create approved request
        approved_request = AccessRequest.objects.create(
            team=team_with_business_plan,
            user=guest_user,
            status=AccessRequest.Status.APPROVED
        )
        Member.objects.create(user=guest_user, team=team_with_business_plan, role="guest") # Needed for revocation logic usually

        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "revoke",
                "request_id": approved_request.id,
                "active_tab": "trust-center",
            },
        )
        
        assert response.status_code == 302
        expected_url = reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key}) + "#trust-center"
        assert response.url == expected_url
        assert response.headers.get("HX-Trigger") == "refreshAccessRequests"

    def test_error_redirects_preserve_tab(
        self, authenticated_web_client, team_with_business_plan, sample_user
    ):
        """Test that errors (e.g. invalid action) also redirect to trust center if tab matches."""
        # We need a request to reference, even if action is invalid
        pending = AccessRequest.objects.create(
            team=team_with_business_plan, user=sample_user, status=AccessRequest.Status.PENDING
        ) # Self request for simplicity, logic just needs valid ID usually or might fail earlier. 
        # Actually logic is: get_object_or_404(AccessRequest...). 
        # If we use valid ID but invalid ACTION...

        setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
        Member.objects.get_or_create(user=sample_user, team=team_with_business_plan, defaults={"role": "owner"})

        url = reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key})
        response = authenticated_web_client.post(
            url,
            {
                "action": "invalid_action",
                "request_id": pending.id,
                "active_tab": "trust-center",
            },
        )
        
        # Logic says: message.error(...) and return redirect(...)
        assert response.status_code == 302
        expected_url = reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key}) + "#trust-center"
        assert response.url == expected_url
        assert response.headers.get("HX-Trigger") == "refreshAccessRequests"
