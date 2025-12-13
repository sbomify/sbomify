# skip_file  # nosec
"""Tests for internal API endpoints (no auth required - secured at proxy level)."""
from __future__ import annotations

import pytest
from django.conf import settings
from django.test import Client, override_settings

from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
def test_check_domain_allowed_returns_200_for_app_base_url():
    """Test that the main application domain (APP_BASE_URL) is always allowed."""
    client = Client()

    # Test with the actual APP_BASE_URL from settings
    if settings.APP_BASE_URL:
        # Parse domain from APP_BASE_URL
        from urllib.parse import urlparse

        parsed = urlparse(settings.APP_BASE_URL)
        app_domain = parsed.hostname or parsed.netloc.split(":")[0]

        response = client.get(f"/api/v1/internal/domains?domain={app_domain}")
        assert response.status_code == 200


@pytest.mark.django_db
@override_settings(APP_BASE_URL="https://app.example.com")
def test_check_domain_allowed_app_base_url_with_https():
    """Test that APP_BASE_URL with https:// protocol is correctly parsed."""
    client = Client()

    response = client.get("/api/v1/internal/domains?domain=app.example.com")
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(APP_BASE_URL="http://localhost:8000")
def test_check_domain_allowed_app_base_url_with_port():
    """Test that APP_BASE_URL with port is correctly parsed."""
    client = Client()

    response = client.get("/api/v1/internal/domains?domain=localhost")
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(APP_BASE_URL="example.com")
def test_check_domain_allowed_app_base_url_without_protocol():
    """Test that APP_BASE_URL without protocol is correctly parsed."""
    client = Client()

    response = client.get("/api/v1/internal/domains?domain=example.com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_business_plan_custom_domain():
    """Test that custom domains from business plan teams are allowed."""
    client = Client()

    # Create a team with business plan and custom domain
    team = Team.objects.create(
        name="Business Team",
        billing_plan="business",
        custom_domain="business.example.com",
        custom_domain_validated=True,
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    response = client.get("/api/v1/internal/domains?domain=business.example.com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_enterprise_plan_custom_domain():
    """Test that custom domains from enterprise plan teams are allowed."""
    client = Client()

    # Create a team with enterprise plan and custom domain
    team = Team.objects.create(
        name="Enterprise Team",
        billing_plan="enterprise",
        custom_domain="enterprise.example.com",
        custom_domain_validated=False,  # Validation status doesn't matter for on-demand TLS
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    response = client.get("/api/v1/internal/domains?domain=enterprise.example.com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_community_plan_denied():
    """Test that custom domains from community plan teams are NOT allowed."""
    client = Client()

    # Create a team with community plan and custom domain
    team = Team.objects.create(
        name="Community Team",
        billing_plan="community",
        custom_domain="community.example.com",
        custom_domain_validated=True,
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    response = client.get("/api/v1/internal/domains?domain=community.example.com")
    assert response.status_code == 404


@pytest.mark.django_db
def test_check_domain_allowed_nonexistent_domain():
    """Test that non-existent domains are denied."""
    client = Client()

    response = client.get("/api/v1/internal/domains?domain=nonexistent.example.com")
    assert response.status_code == 404


@pytest.mark.django_db
def test_check_domain_allowed_case_insensitive():
    """Test that domain matching is case insensitive."""
    client = Client()

    # Create a team with custom domain in lowercase
    team = Team.objects.create(
        name="Business Team",
        billing_plan="business",
        custom_domain="example.com",
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    # Test with uppercase
    response = client.get("/api/v1/internal/domains?domain=EXAMPLE.COM")
    assert response.status_code == 200

    # Test with mixed case
    response = client.get("/api/v1/internal/domains?domain=Example.Com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_strips_whitespace():
    """Test that domain input is properly sanitized (whitespace stripped)."""
    client = Client()

    # Create a team with custom domain
    team = Team.objects.create(
        name="Business Team",
        billing_plan="business",
        custom_domain="example.com",
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    # Test with leading/trailing whitespace
    response = client.get("/api/v1/internal/domains?domain=%20example.com%20")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_handles_domain_with_port():
    """Test that domain with port is correctly parsed."""
    client = Client()

    # Create a team with custom domain
    team = Team.objects.create(
        name="Business Team",
        billing_plan="business",
        custom_domain="example.com",
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    # Test with port (should be stripped)
    response = client.get("/api/v1/internal/domains?domain=example.com:443")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_handles_domain_with_protocol():
    """Test that domain with protocol is correctly parsed."""
    client = Client()

    # Create a team with custom domain
    team = Team.objects.create(
        name="Business Team",
        billing_plan="business",
        custom_domain="example.com",
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    # Test with protocol (should be stripped)
    response = client.get("/api/v1/internal/domains?domain=https://example.com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_check_domain_allowed_missing_domain_parameter():
    """Test that missing domain parameter returns 422 (validation error)."""
    client = Client()

    response = client.get("/api/v1/internal/domains")
    # Ninja API framework returns 422 for missing required parameters
    assert response.status_code == 422


@pytest.mark.django_db
def test_check_domain_allowed_empty_domain_parameter():
    """Test that empty domain parameter is rejected."""
    client = Client()

    response = client.get("/api/v1/internal/domains?domain=")
    assert response.status_code == 404


@pytest.mark.django_db
def test_check_domain_allowed_invalid_domain_format():
    """Test that invalid domain formats are rejected."""
    client = Client()

    # Test various invalid formats
    invalid_domains = [
        "://invalid",
        "http://",
        "https://",
        "not a domain!",
        "domain with spaces",
    ]

    for invalid_domain in invalid_domains:
        response = client.get(f"/api/v1/internal/domains?domain={invalid_domain}")
        assert response.status_code == 404, f"Expected 404 for invalid domain: {invalid_domain}"


@pytest.mark.django_db
@override_settings(APP_BASE_URL="https://stage.sbomify.com")
def test_check_domain_allowed_real_world_scenario():
    """Test real-world scenario with stage.sbomify.com as APP_BASE_URL."""
    client = Client()

    # Test the main app domain
    response = client.get("/api/v1/internal/domains?domain=stage.sbomify.com")
    assert response.status_code == 200

    # Test a custom domain for a business team
    team = Team.objects.create(
        name="Acme Corp",
        billing_plan="business",
        custom_domain="trust.acme.com",
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    response = client.get("/api/v1/internal/domains?domain=trust.acme.com")
    assert response.status_code == 200

    # Test a random domain not in the system
    response = client.get("/api/v1/internal/domains?domain=random.example.com")
    assert response.status_code == 404


@pytest.mark.django_db
def test_check_domain_allowed_multiple_teams_same_billing_plan():
    """Test that multiple teams with the same billing plan all get their domains allowed."""
    client = Client()

    # Create multiple business teams
    team1 = Team.objects.create(
        name="Business Team 1",
        billing_plan="business",
        custom_domain="business1.example.com",
    )
    team1.key = number_to_random_token(team1.pk)
    team1.save()

    team2 = Team.objects.create(
        name="Business Team 2",
        billing_plan="business",
        custom_domain="business2.example.com",
    )
    team2.key = number_to_random_token(team2.pk)
    team2.save()

    # Both should be allowed
    response = client.get("/api/v1/internal/domains?domain=business1.example.com")
    assert response.status_code == 200

    response = client.get("/api/v1/internal/domains?domain=business2.example.com")
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(APP_BASE_URL="")
def test_check_domain_allowed_no_app_base_url():
    """Test behavior when APP_BASE_URL is not configured."""
    client = Client()

    # Create a business team with custom domain
    team = Team.objects.create(
        name="Business Team",
        billing_plan="business",
        custom_domain="business.example.com",
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    # Custom domain should still work
    response = client.get("/api/v1/internal/domains?domain=business.example.com")
    assert response.status_code == 200

    # Random domain should fail
    response = client.get("/api/v1/internal/domains?domain=random.example.com")
    assert response.status_code == 404


@pytest.mark.django_db
def test_check_domain_allowed_no_auth_required():
    """Test that the endpoint does not require authentication."""
    client = Client()

    # This endpoint should work without any authentication
    # (it's secured at the proxy level, not in Django)
    response = client.get("/api/v1/internal/domains?domain=example.com")

    # Should not return 401 (unauthorized) - either 200 or 404
    assert response.status_code in [200, 404]
    assert response.status_code != 401
