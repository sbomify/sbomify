"""Tests for custom domain (CNAME) management API endpoints.

This module tests the CNAME management functionality for workspaces,
including feature gating for business/enterprise plans only.

Note: Each workspace can only have ONE custom domain.
"""

import json
from unittest.mock import patch

import pytest

from sbomify.apps.core.tests.shared_fixtures import (
    get_api_headers,
)
from sbomify.apps.teams.models import Member


@pytest.mark.django_db
class TestCustomDomainCreate:
    """Test creating custom domains for workspaces."""

    def test_create_custom_domain_success_business_plan(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that business plan users can create custom domains."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {
            "hostname": "trust.example.com",
        }

        response = client.post(url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201
        data = response.json()
        assert data["hostname"] == "trust.example.com"
        assert data["is_verified"] is False
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data

    def test_create_custom_domain_success_enterprise_plan(
        self,
        team_with_enterprise_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that enterprise plan users can create custom domains."""
        # team_with_enterprise_plan fixture already creates owner member with sample_user
        team = team_with_enterprise_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {
            "hostname": "trust.example.com",
        }

        response = client.post(url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201
        data = response.json()
        assert data["hostname"] == "trust.example.com"

    def test_create_custom_domain_forbidden_community_plan(
        self,
        team_with_community_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that community plan users cannot create custom domains."""
        # team_with_community_plan fixture already creates owner member with sample_user
        team = team_with_community_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {
            "hostname": "trust.example.com",
        }

        response = client.post(url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 403
        data = response.json()
        assert "detail" in data
        assert "business" in data["detail"].lower() or "enterprise" in data["detail"].lower()

    def test_create_custom_domain_requires_owner_or_admin(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that only owners and admins can create custom domains."""
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Change the existing member from owner to member role
        member = Member.objects.get(user=token.user, team=team)
        member.role = "member"
        member.save()

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {
            "hostname": "trust.example.com",
        }

        response = client.post(url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 403

    def test_create_custom_domain_requires_authentication(
        self,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that creating custom domains requires authentication."""
        from django.test import Client

        team = team_with_business_plan
        client = Client()

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {
            "hostname": "trust.example.com",
        }

        response = client.post(url, json.dumps(payload), content_type="application/json")
        assert response.status_code in [401, 403]

    def test_create_custom_domain_invalid_hostname(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that invalid hostnames are rejected."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        invalid_hostnames = [
            ("invalid hostname with spaces", 400),
            ("http://example.com", 400),  # Should be hostname only
            ("https://example.com", 400),  # Should be hostname only
            ("", 422),  # Empty hostname - caught by Pydantic validation
            (".", 400),  # Invalid
            ("-.example.com", 400),  # Invalid start
            ("example-.com", 400),  # Invalid end
        ]

        for hostname, expected_status in invalid_hostnames:
            payload = {"hostname": hostname}
            response = client.post(url, json.dumps(payload), content_type="application/json", **headers)
            assert response.status_code == expected_status, f"Hostname '{hostname}' should return {expected_status}"

    def test_create_duplicate_custom_domain_same_workspace(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that a workspace can only have one custom domain."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {
            "hostname": "trust.example.com",
        }

        # First creation should succeed
        response = client.post(url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Second creation for same workspace should fail (workspace already has a domain)
        payload2 = {
            "hostname": "different.example.com",
        }
        response = client.post(url, json.dumps(payload2), content_type="application/json", **headers)
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "already has" in data["detail"].lower() or "one domain" in data["detail"].lower()


@pytest.mark.django_db
class TestCustomDomainGet:
    """Test getting the workspace's custom domain."""

    def test_get_custom_domain_success(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test getting the workspace's custom domain."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Get the workspace's custom domain
        get_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.get(get_url, **headers)
        assert response.status_code == 200

        data = response.json()
        assert data["hostname"] == "trust.example.com"
        assert "id" in data
        assert "is_verified" in data
        assert "is_active" in data

    def test_get_custom_domain_not_found(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test getting custom domain when workspace doesn't have one."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.get(url, **headers)
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_get_custom_domain_requires_member(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that getting custom domain requires team membership."""
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Remove user as member of the team
        Member.objects.filter(user=token.user, team=team).delete()

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.get(url, **headers)
        # Returns 404 for team not found to avoid leaking team existence
        assert response.status_code in [403, 404]

    def test_get_custom_domain_forbidden_community_plan(
        self,
        team_with_community_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that community plan users cannot access custom domains."""
        # team_with_community_plan fixture already creates owner member with sample_user
        team = team_with_community_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.get(url, **headers)
        assert response.status_code == 403


@pytest.mark.django_db
class TestCustomDomainUpdate:
    """Test updating custom domains."""

    def test_update_custom_domain_success(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test updating the workspace's custom domain."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Update the custom domain
        update_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        update_payload = {
            "is_active": False,
        }
        response = client.patch(update_url, json.dumps(update_payload), content_type="application/json", **headers)
        assert response.status_code == 200

        data = response.json()
        assert data["is_active"] is False
        assert data["hostname"] == "trust.example.com"  # Hostname should not change

    def test_update_custom_domain_hostname_forbidden(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that updating hostname is not allowed via PATCH."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Try to update hostname
        update_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        update_payload = {
            "hostname": "different.example.com",
        }
        response = client.patch(update_url, json.dumps(update_payload), content_type="application/json", **headers)
        # Should either ignore the hostname field or reject it
        data = response.json()
        # Original hostname should be preserved
        assert data["hostname"] == "trust.example.com"

    def test_update_custom_domain_requires_owner_or_admin(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that only owners and admins can update custom domains."""
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Get the existing owner member (created by fixture)
        member = Member.objects.get(user=token.user, team=team)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Change user to member (not owner/admin)
        member.role = "member"
        member.save()

        # Try to update
        update_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        update_payload = {"is_active": False}
        response = client.patch(update_url, json.dumps(update_payload), content_type="application/json", **headers)
        assert response.status_code == 403


@pytest.mark.django_db
class TestCustomDomainDelete:
    """Test deleting custom domains."""

    def test_delete_custom_domain_success(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test deleting the workspace's custom domain."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Delete the custom domain
        delete_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.delete(delete_url, **headers)
        assert response.status_code == 204

        # Verify it's deleted
        get_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.get(get_url, **headers)
        assert response.status_code == 404

    def test_delete_custom_domain_not_found(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test deleting when workspace doesn't have a custom domain."""
        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.delete(url, **headers)
        assert response.status_code == 404

    def test_delete_custom_domain_requires_owner_or_admin(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that only owners and admins can delete custom domains."""
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Get the existing owner member (created by fixture)
        member = Member.objects.get(user=token.user, team=team)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Change user to member (not owner/admin)
        member.role = "member"
        member.save()

        # Try to delete
        delete_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.delete(delete_url, **headers)
        assert response.status_code == 403


@pytest.mark.django_db
class TestCustomDomainVerification:
    """Test custom domain verification functionality."""

    @patch("sbomify.apps.teams.tasks.verify_custom_domain_task.send")
    def test_verify_custom_domain_triggers_task(
        self,
        mock_task_send,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that verifying a custom domain triggers async task."""
        mock_task_send.return_value = None

        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Verify the custom domain (triggers async task, returns 202 Accepted)
        verify_url = f"/api/v1/workspaces/{team.key}/custom-domain/verify"
        response = client.post(verify_url, **headers)
        assert response.status_code == 202

        # Task is queued and will run asynchronously
        # Note: In production, client would poll GET endpoint to check verification status
        mock_task_send.assert_called_once()

    def test_verify_custom_domain_task_success_via_cname(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test the async DNS verification task with CNAME record."""
        # Configure APP_BASE_URL for testing
        settings.APP_BASE_URL = "https://edge.example.com"

        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Mock DNS resolver to return CNAME pointing to edge
        with patch("dns.resolver.resolve") as mock_resolve:
            from unittest.mock import MagicMock

            # Create mock CNAME response pointing to edge.example.com
            mock_rdata = MagicMock()
            mock_rdata.target = MagicMock()
            mock_rdata.target.__str__ = lambda self: "edge.example.com."
            mock_resolve.return_value = [mock_rdata]

            # Execute the verification task directly (simulating async execution)
            from sbomify.apps.teams.models import CustomDomain
            from sbomify.apps.teams.tasks import verify_custom_domain_task

            custom_domain = CustomDomain.objects.get(team=team)
            result = verify_custom_domain_task(custom_domain.id)

            # Verify the task executed successfully
            assert result["success"] is True
            assert result["verified"] is True

            # Check that the domain is now verified in the database
            custom_domain.refresh_from_db()
            assert custom_domain.is_verified is True
            assert custom_domain.verified_at is not None

    @patch("sbomify.apps.teams.utils.verify_custom_domain_dns")
    def test_verify_custom_domain_task_failure(
        self,
        mock_verify_dns,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test the async DNS verification task with failed resolution."""
        mock_verify_dns.return_value = False

        # team_with_business_plan fixture already creates owner member with sample_user
        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Execute the verification task directly (simulating async execution)
        from sbomify.apps.teams.models import CustomDomain
        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        result = verify_custom_domain_task(custom_domain.id)

        # Verify the task executed but verification failed
        assert result["success"] is True  # Task executed successfully
        assert result["verified"] is False  # But DNS verification failed

        # Check that the domain is still not verified in the database
        custom_domain.refresh_from_db()
        assert custom_domain.is_verified is False
        assert custom_domain.verified_at is None
