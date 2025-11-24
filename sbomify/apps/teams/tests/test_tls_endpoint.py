"""Tests for Caddy TLS allow-host endpoint.

This endpoint is used by Caddy for on-demand TLS certificate issuance.

SECURITY NOTE: In production, this endpoint should be protected by Caddy
configuration to prevent public access. These tests assume the endpoint
is accessible (as it would be from Caddy's perspective).
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan
from sbomify.apps.teams.models import CustomDomain


@pytest.mark.django_db
class TestTLSAllowHost:
    """Test the /_tls/allow-host endpoint for Caddy integration."""

    @patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns")
    def test_allow_host_verified_and_active_domain(
        self,
        mock_verify_dns,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that verified and active domains are allowed."""
        cache.clear()
        mock_verify_dns.return_value = True

        team = team_with_business_plan

        # Create a verified and active custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=True,
            is_active=True,
        )

        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"
        response = client.get(url)

        assert response.status_code == 200
        assert response.content.decode() == "OK"

    def test_deny_host_not_verified(
        self,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that unverified domains are denied."""
        cache.clear()
        team = team_with_business_plan

        # Create an unverified custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=False,
            is_active=True,
        )

        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"
        response = client.get(url)

        assert response.status_code == 403

    def test_deny_host_not_active(
        self,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that inactive domains are denied."""
        cache.clear()
        team = team_with_business_plan

        # Create a verified but inactive custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=True,
            is_active=False,
        )

        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"
        response = client.get(url)

        assert response.status_code == 403

    def test_deny_host_not_found(self):
        """Test that unknown domains are denied."""
        cache.clear()
        client = Client()
        url = "/_tls/allow-host?domain=unknown.example.com"
        response = client.get(url)

        assert response.status_code == 403

    def test_deny_localhost(self):
        """Test that localhost is rejected immediately."""
        cache.clear()
        client = Client()

        # Test various localhost formats
        for hostname in ["localhost", "127.0.0.1", "::1"]:
            url = f"/_tls/allow-host?domain={hostname}"
            response = client.get(url)
            assert response.status_code == 403, f"{hostname} should be rejected"

    def test_deny_non_fqdn(self):
        """Test that non-FQDN domains are rejected."""
        cache.clear()
        client = Client()

        # Test domains without dots (not FQDN)
        for hostname in ["single", "nodots", "internal"]:
            url = f"/_tls/allow-host?domain={hostname}"
            response = client.get(url)
            assert response.status_code == 403, f"{hostname} should be rejected as non-FQDN"

    def test_missing_domain_parameter(self):
        """Test that requests without domain parameter are rejected."""
        cache.clear()
        client = Client()
        url = "/_tls/allow-host"
        response = client.get(url)

        assert response.status_code == 400

    @patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns")
    def test_allow_host_with_realtime_dns_check(
        self,
        mock_verify_dns,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that realtime DNS verification is performed when enabled."""
        cache.clear()
        mock_verify_dns.return_value = True

        team = team_with_business_plan

        # Create a verified and active custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=True,
            is_active=True,
        )

        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"
        response = client.get(url)

        assert response.status_code == 200
        # Verify that DNS check was called
        mock_verify_dns.assert_called_once_with("trust.example.com")

    @patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns")
    def test_deny_host_when_realtime_dns_check_fails(
        self,
        mock_verify_dns,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that domains are denied if realtime DNS check fails."""
        cache.clear()
        mock_verify_dns.return_value = False

        team = team_with_business_plan

        # Create a verified and active custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=True,
            is_active=True,
        )

        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"
        response = client.get(url)

        assert response.status_code == 403
        # Verify that DNS check was called
        mock_verify_dns.assert_called_once_with("trust.example.com")

    @patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns")
    def test_endpoint_does_not_require_django_authentication(
        self,
        mock_verify_dns,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that the endpoint doesn't require Django user authentication (for Caddy access)."""
        cache.clear()
        mock_verify_dns.return_value = True

        team = team_with_business_plan

        # Create a verified and active custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=True,
            is_active=True,
        )

        # Use unauthenticated client (simulating Caddy internal call)
        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"
        response = client.get(url)

        # Should work without Django authentication
        assert response.status_code == 200

    @patch("sbomify.apps.teams.views.tls.verify_custom_domain_dns")
    def test_rate_limit_enforcement(
        self,
        mock_verify_dns,
        team_with_business_plan,  # noqa: F811
    ):
        """Test that rate limiting is enforced (per-domain limit)."""
        # Clear cache before test
        cache.clear()

        mock_verify_dns.return_value = True

        team = team_with_business_plan

        # Create a verified and active custom domain
        CustomDomain.objects.create(
            team=team,
            hostname="trust.example.com",
            is_verified=True,
            is_active=True,
        )

        client = Client()
        url = "/_tls/allow-host?domain=trust.example.com"

        # Make requests from different IPs up to the per-domain limit (10 by default)
        # Using different IPs ensures we hit the per-domain limit, not per-IP limit
        from sbomify.apps.teams.views.tls import MAX_REQUESTS_PER_DOMAIN

        for i in range(MAX_REQUESTS_PER_DOMAIN):
            # Use different IP for each request to bypass IP rate limit
            response = client.get(url, REMOTE_ADDR=f"172.18.0.{i + 1}")
            assert response.status_code == 200, f"Request {i + 1} from different IP should succeed"

        # 11th request from yet another IP should be rate limited (domain limit reached)
        response = client.get(url, REMOTE_ADDR="172.18.0.99")
        assert response.status_code == 429
        assert "Rate limit exceeded for domain" in response.content.decode()
