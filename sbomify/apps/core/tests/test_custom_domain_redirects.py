"""
Tests for custom domain redirect functionality.

Tests that requests to the main app domain redirect to custom domains
when appropriate, and that URL generation respects custom domains.
"""

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from urllib.parse import urlparse

from sbomify.apps.core.models import Product, Project, Component
from sbomify.apps.teams.models import Team


@pytest.fixture(autouse=True)
def setup_app_base_url(settings):
    """Set APP_BASE_URL for all tests in this module."""
    settings.APP_BASE_URL = "http://app.sbomify.com"


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test to prevent stale lookups."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def custom_domain_team(db):
    """Create a team with a validated custom domain."""
    team = Team.objects.create(
        name="Test Company",
        billing_plan="business",
        custom_domain="trust.example.com",
        custom_domain_validated=True,
    )
    # Set is_public after creation to bypass the save() override for paid plans
    team.is_public = True
    team.save(update_fields=["is_public"])
    # Refresh to get auto-generated key
    team.refresh_from_db()
    return team


@pytest.fixture
def team_without_custom_domain(db):
    """Create a team without a custom domain."""
    team = Team.objects.create(
        name="Regular Company",
        billing_plan="community",
        is_public=True,
    )
    # Refresh to get auto-generated key
    team.refresh_from_db()
    return team


@pytest.fixture
def product_with_custom_domain(db, custom_domain_team):
    """Create a public product for a team with custom domain."""
    product = Product.objects.create(
        name="Test Product",
        description="Test Description",
        team=custom_domain_team,
        is_public=True,
    )
    return product


@pytest.fixture
def product_without_custom_domain(db, team_without_custom_domain):
    """Create a public product for a team without custom domain."""
    product = Product.objects.create(
        name="Regular Product",
        team=team_without_custom_domain,
        is_public=True,
    )
    return product


@pytest.mark.django_db
class TestPublicPagesOnMainDomain:
    """Test that public pages redirect to custom domain when team has verified one."""

    def test_workspace_redirects_to_custom_domain(self, client, custom_domain_team):
        """Test that workspace page redirects to custom domain."""
        workspace_key = custom_domain_team.key
        response = client.get(
            f"/public/workspace/{workspace_key}/",
            HTTP_HOST="app.sbomify.com"
        )

        # Should redirect to custom domain
        assert response.status_code == 302
        assert urlparse(response.url).hostname == "trust.example.com"

    def test_product_redirects_to_custom_domain(self, client, product_with_custom_domain):
        """Test that product page redirects to custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(
            f"/public/product/{product_id}/",
            HTTP_HOST="app.sbomify.com"
        )

        # Should redirect to custom domain with slug-based URL
        assert response.status_code == 302
        assert urlparse(response.url).hostname == "trust.example.com"
        assert "/product/" in response.url

    def test_no_redirect_without_custom_domain(self, client, product_without_custom_domain):
        """Test that products without custom domains work normally."""
        product_id = product_without_custom_domain.id
        response = client.get(
            f"/public/product/{product_id}/",
            HTTP_HOST="app.sbomify.com"
        )

        # Should serve the page (no custom domain to redirect to)
        assert response.status_code == 200

    def test_works_on_custom_domain(self, client, product_with_custom_domain):
        """Test that clean URLs work on custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(
            f"/product/{product_id}/",
            HTTP_HOST="trust.example.com"
        )

        # Should serve the page (already on custom domain)
        assert response.status_code == 200

    def test_unvalidated_custom_domain_accessible(self, client, db):
        """Test that products work on main domain even with unvalidated custom domain."""
        team = Team.objects.create(
            name="Unvalidated Company",
            key="unval789",
            billing_plan="business",
            custom_domain="pending.example.com",
            custom_domain_validated=False,  # Not validated
            is_public=True,
        )
        product = Product.objects.create(
            name="Product",
            team=team,
            is_public=True,
        )

        response = client.get(
            f"/public/product/{product.id}/",
            HTTP_HOST="app.sbomify.com"
        )

        # Should work normally
        assert response.status_code == 200


@pytest.mark.django_db
class TestPublicURLsOnCustomDomain:
    """Test that /public/* URLs work on custom domains (serve content without redirect)."""

    def test_public_workspace_works_on_custom_domain(self, client, custom_domain_team):
        """Test that /public/workspace/* works on custom domain."""
        response = client.get(
            f"/public/workspace/{custom_domain_team.key}/",
            HTTP_HOST="trust.example.com"
        )

        # Should serve content (public URLs work on custom domains)
        assert response.status_code == 200

    def test_public_product_works_on_custom_domain(self, client, product_with_custom_domain):
        """Test that /public/product/* works on custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(
            f"/public/product/{product_id}/",
            HTTP_HOST="trust.example.com"
        )

        # Should serve content (public URLs work on custom domains)
        assert response.status_code == 200

    def test_main_domain_public_urls_redirect(self, client, product_with_custom_domain):
        """Test that /public/* URLs on main domain redirect to custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(
            f"/public/product/{product_id}/",
            HTTP_HOST="app.sbomify.com"
        )

        # Should redirect to custom domain
        assert response.status_code == 302
        parsed = urlparse(response.url)
        assert parsed.hostname == "trust.example.com"


@pytest.mark.django_db
class TestPrivatePagesOnCustomDomain:
    """Test that private pages redirect to main domain or show public content."""

    def test_dashboard_not_accessible_on_custom_domain(self, client, custom_domain_team):
        """Test that dashboard is not accessible on custom domain."""
        response = client.get(
            "/dashboard",
            HTTP_HOST="trust.example.com"
        )

        # Custom domain should not serve private pages
        assert response.status_code in [302, 404]

    def test_authenticated_user_sees_public_content(self, client, product_with_custom_domain, django_user_model):
        """Test that authenticated users see public content on custom domain."""
        # Create and login user
        user = django_user_model.objects.create_user(username="testuser", password="testpass")
        client.login(username="testuser", password="testpass")

        product_id = product_with_custom_domain.id
        response = client.get(
            f"/product/{product_id}/",
            HTTP_HOST="trust.example.com"
        )

        # Should show public content even when authenticated
        assert response.status_code == 200
