"""Integration tests for custom domain + Caddy TLS endpoint.

This module tests the complete flow from custom domain creation through to
Caddy TLS certificate issuance verification.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_api_client,
    get_api_headers,
    team_with_business_plan,
)
from sbomify.apps.teams.models import CustomDomain, Member


@pytest.mark.django_db
class TestCustomDomainCaddyIntegration:
    """Integration tests for the complete custom domain + TLS flow."""

    def test_full_flow_unverified_domain_denied_by_caddy(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test that newly created (unverified) domains are denied by Caddy."""
        cache.clear()

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Step 1: Create a custom domain via API
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)

        assert response.status_code == 201
        data = response.json()
        assert data["hostname"] == "trust.example.com"
        assert data["is_verified"] is False
        assert data["is_active"] is True

        # Step 2: Check Caddy TLS endpoint - should DENY (not verified)
        caddy_client = Client()  # Caddy doesn't use Django auth
        tls_url = "/_tls/allow-host?domain=trust.example.com"
        response = caddy_client.get(tls_url)

        assert response.status_code == 403
        assert "not verified" in response.content.decode().lower()

    @patch("dns.resolver.resolve")
    def test_full_flow_verified_domain_allowed_by_caddy(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test complete flow: create → verify → Caddy allows certificate issuance."""
        cache.clear()

        # Configure APP_BASE_URL for DNS verification
        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Step 1: Create a custom domain via API
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)

        assert response.status_code == 201
        data = response.json()
        assert data["is_verified"] is False

        # Step 2: Verify the domain (triggers async task)
        verify_url = f"/api/v1/workspaces/{team.key}/custom-domain/verify"
        response = client.post(verify_url, **headers)
        assert response.status_code == 202  # Task queued

        # Step 3: Simulate async task execution with successful DNS verification
        # Mock CNAME record pointing to sbomify.example.com
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        # Execute the verification task
        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        result = verify_custom_domain_task(custom_domain.id)

        assert result["success"] is True
        assert result["verified"] is True

        # Step 4: Verify domain is now verified in database
        custom_domain.refresh_from_db()
        assert custom_domain.is_verified is True
        assert custom_domain.verified_at is not None

        # Step 5: Check Caddy TLS endpoint - should ALLOW (verified and active)
        caddy_client = Client()  # Caddy doesn't use Django auth
        tls_url = "/_tls/allow-host?domain=trust.example.com"

        # Mock DNS for real-time check in TLS endpoint
        with patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns") as mock_verify:
            mock_verify.return_value = True
            response = caddy_client.get(tls_url)

        assert response.status_code == 200
        assert response.content.decode() == "OK"

    @patch("dns.resolver.resolve")
    def test_full_flow_deactivated_domain_denied_by_caddy(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test that deactivated domains are denied by Caddy even if verified."""
        cache.clear()

        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create and verify domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Simulate verification
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        verify_custom_domain_task(custom_domain.id)

        custom_domain.refresh_from_db()
        assert custom_domain.is_verified is True

        # Deactivate the domain
        update_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        update_payload = {"is_active": False}
        response = client.patch(update_url, json.dumps(update_payload), content_type="application/json", **headers)
        assert response.status_code == 200

        data = response.json()
        assert data["is_active"] is False

        # Caddy should DENY (domain is inactive)
        caddy_client = Client()
        tls_url = "/_tls/allow-host?domain=trust.example.com"
        response = caddy_client.get(tls_url)

        assert response.status_code == 403
        assert "not active" in response.content.decode().lower()

    @patch("dns.resolver.resolve")
    def test_full_flow_deleted_domain_denied_by_caddy(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test that deleted domains are denied by Caddy."""
        cache.clear()

        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create and verify domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Simulate verification
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        verify_custom_domain_task(custom_domain.id)

        # Delete the domain
        delete_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.delete(delete_url, **headers)
        assert response.status_code == 204

        # Verify it's deleted
        assert not CustomDomain.objects.filter(hostname="trust.example.com").exists()

        # Caddy should DENY (domain not found)
        caddy_client = Client()
        tls_url = "/_tls/allow-host?domain=trust.example.com"
        response = caddy_client.get(tls_url)

        assert response.status_code == 403
        assert "not found" in response.content.decode().lower()

    def test_full_flow_verification_failure_lifecycle(
        self,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
    ):
        """Test flow when DNS verification fails."""
        cache.clear()

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create a custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Trigger verification (will fail if DNS not configured)
        verify_url = f"/api/v1/workspaces/{team.key}/custom-domain/verify"
        response = client.post(verify_url, **headers)
        assert response.status_code == 202  # Task queued

        # Simulate failed DNS verification (wrong CNAME target)
        with patch("dns.resolver.resolve") as mock_dns:
            mock_rdata = MagicMock()
            mock_rdata.target = MagicMock()
            mock_rdata.target.__str__ = lambda self: "wrong-domain.com."
            mock_dns.return_value = [mock_rdata]

            from sbomify.apps.teams.tasks import verify_custom_domain_task

            custom_domain = CustomDomain.objects.get(team=team)
            result = verify_custom_domain_task(custom_domain.id)

            assert result["success"] is True  # Task executed
            assert result["verified"] is False  # But verification failed

        # Domain should still be unverified
        custom_domain.refresh_from_db()
        assert custom_domain.is_verified is False

        # Caddy should DENY (not verified)
        caddy_client = Client()
        tls_url = "/_tls/allow-host?domain=trust.example.com"
        response = caddy_client.get(tls_url)

        assert response.status_code == 403
        assert "not verified" in response.content.decode().lower()

    @patch("dns.resolver.resolve")
    def test_full_flow_multiple_workspaces_same_hostname_prevented(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test that the same hostname cannot be used by multiple workspaces."""
        cache.clear()

        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create first custom domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Create a second workspace
        from sbomify.apps.billing.models import BillingPlan
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Team

        business_plan = BillingPlan.objects.get(key="business")
        team2 = Team.objects.create(
            name="Second Business Team",
            billing_plan=business_plan.key,
            billing_plan_limits={
                "max_products": business_plan.max_products,
                "max_projects": business_plan.max_projects,
                "max_components": business_plan.max_components,
                "stripe_customer_id": "cus_test456",
                "stripe_subscription_id": "sub_test456",
                "subscription_status": "active",
            },
        )
        team2.key = number_to_random_token(team2.pk)
        team2.save()

        # Make user owner of second team
        Member.objects.create(team=team2, user=token.user, role="owner", is_default_team=False)

        # Try to create same hostname for second workspace
        create_url2 = f"/api/v1/workspaces/{team2.key}/custom-domain"
        payload2 = {"hostname": "trust.example.com"}  # Same hostname
        response = client.post(create_url2, json.dumps(payload2), content_type="application/json", **headers)

        # Should be rejected - hostname already in use
        assert response.status_code == 400
        data = response.json()
        assert "already in use" in data["detail"].lower()

        # Verify Caddy still only sees the first workspace's domain
        caddy_client = Client()
        tls_url = "/_tls/allow-host?domain=trust.example.com"

        # Mock DNS for real-time check
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        # Verify domain for first team
        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(hostname="trust.example.com")
        verify_custom_domain_task(custom_domain.id)

        custom_domain.refresh_from_db()
        assert custom_domain.team == team  # Belongs to first team

        # Now Caddy should allow it (verified for first team)
        with patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns") as mock_verify:
            mock_verify.return_value = True
            response = caddy_client.get(tls_url)

        assert response.status_code == 200

    @patch("dns.resolver.resolve")
    def test_full_flow_reactivation_after_deactivation(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test domain deactivation and reactivation flow."""
        cache.clear()

        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create and verify domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Verify
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        verify_custom_domain_task(custom_domain.id)

        # Deactivate
        update_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.patch(
            update_url, json.dumps({"is_active": False}), content_type="application/json", **headers
        )
        assert response.status_code == 200

        # Caddy should DENY
        caddy_client = Client()
        tls_url = "/_tls/allow-host?domain=trust.example.com"
        response = caddy_client.get(tls_url)
        assert response.status_code == 403

        # Reactivate
        response = client.patch(update_url, json.dumps({"is_active": True}), content_type="application/json", **headers)
        assert response.status_code == 200

        # Caddy should ALLOW again
        with patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns") as mock_verify:
            mock_verify.return_value = True
            response = caddy_client.get(tls_url)

        assert response.status_code == 200

    @patch("dns.resolver.resolve")
    def test_full_flow_get_after_verification(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test that GET endpoint reflects verification status after async task completes."""
        cache.clear()

        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # GET before verification
        get_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        response = client.get(get_url, **headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_verified"] is False
        assert data["verified_at"] is None

        # Verify domain
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        verify_custom_domain_task(custom_domain.id)

        # GET after verification - status should be updated
        response = client.get(get_url, **headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_verified"] is True
        assert data["verified_at"] is not None

        # Frontend can poll this endpoint to check verification status

    @patch("dns.resolver.resolve")
    def test_full_flow_caddy_rate_limiting_integration(
        self,
        mock_dns_resolve,
        team_with_business_plan,  # noqa: F811
        authenticated_api_client,  # noqa: F811
        settings,
    ):
        """Test that Caddy rate limiting protects against abuse."""
        cache.clear()

        settings.APP_BASE_URL = "https://sbomify.example.com"

        team = team_with_business_plan
        client, token = authenticated_api_client
        headers = get_api_headers(token)

        # Create and verify domain
        create_url = f"/api/v1/workspaces/{team.key}/custom-domain"
        payload = {"hostname": "trust.example.com"}
        response = client.post(create_url, json.dumps(payload), content_type="application/json", **headers)
        assert response.status_code == 201

        # Verify
        mock_rdata = MagicMock()
        mock_rdata.target = MagicMock()
        mock_rdata.target.__str__ = lambda self: "sbomify.example.com."
        mock_dns_resolve.return_value = [mock_rdata]

        from sbomify.apps.teams.tasks import verify_custom_domain_task

        custom_domain = CustomDomain.objects.get(team=team)
        verify_custom_domain_task(custom_domain.id)

        # Make requests from Caddy up to rate limit
        caddy_client = Client()
        tls_url = "/_tls/allow-host?domain=trust.example.com"

        from sbomify.apps.teams.views.tls import MAX_REQUESTS_PER_DOMAIN

        with patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns") as mock_verify:
            mock_verify.return_value = True

            # Make MAX_REQUESTS_PER_DOMAIN requests
            for i in range(MAX_REQUESTS_PER_DOMAIN):
                response = caddy_client.get(tls_url, REMOTE_ADDR=f"10.0.0.{i + 1}")
                assert response.status_code == 200

            # Next request should be rate limited
            response = caddy_client.get(tls_url, REMOTE_ADDR="10.0.0.99")
            assert response.status_code == 429
            assert "Rate limit exceeded" in response.content.decode()
