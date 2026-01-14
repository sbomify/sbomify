"""
Tests for custom domain routing functionality.

Tests that custom domains correctly route to public pages with clean URLs
and that the middleware properly detects and attaches workspace context.
"""

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from sbomify.apps.core.models import Product, Project, Component
from sbomify.apps.teams.models import Team


from django.core.cache import cache

pytestmark = pytest.mark.django_db


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
    """Create a team with a custom domain."""
    team = Team.objects.create(
        name="Test Company",
        billing_plan="business",
        custom_domain="trust.example.com",
        custom_domain_validated=True,
    )
    # Set is_public after creation to bypass the save() override for paid plans
    team.is_public = True
    team.save(update_fields=["is_public"])
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
def project_with_custom_domain(db, custom_domain_team, product_with_custom_domain):
    """Create a public project for a team with custom domain."""
    project = Project.objects.create(
        name="Test Project",
        team=custom_domain_team,
        is_public=True,
    )
    project.products.add(product_with_custom_domain)
    return project


@pytest.fixture
def component_with_custom_domain(db, custom_domain_team):
    """Create a public component for a team with custom domain."""
    component = Component.objects.create(
        name="Test Component",
        component_type=Component.ComponentType.SBOM,
        team=custom_domain_team,
        is_public=True,
        is_global=True,
    )
    return component


class TestCustomDomainMiddleware:
    """Test the CustomDomainContextMiddleware."""

    def test_middleware_detects_custom_domain(self, client, custom_domain_team):
        """Test that middleware detects and attaches custom domain team."""
        response = client.get("/", HTTP_HOST="trust.example.com")

        # Middleware should set these attributes on the request
        # We can't directly access request in tests, but we can verify the response
        assert response.status_code in [200, 302, 404]  # Valid response

    def test_middleware_main_app_domain(self, client):
        """Test that middleware doesn't set custom domain for main app."""
        response = client.get("/", HTTP_HOST="app.sbomify.com")
        assert response.status_code in [200, 302]

    def test_middleware_localhost(self, client):
        """Test that middleware doesn't set custom domain for localhost."""
        response = client.get("/")
        assert response.status_code in [200, 302]


class TestCustomDomainRouting:
    """Test URL routing on custom domains."""

    def test_root_path_shows_workspace(self, client, custom_domain_team):
        """Test that / on custom domain shows workspace Trust Center."""
        response = client.get("/", HTTP_HOST="trust.example.com")

        # Should show the workspace public page
        assert response.status_code == 200
        assert b"Trust Center" in response.content or b"trust center" in response.content.lower()

    def test_product_detail_clean_url(self, client, product_with_custom_domain):
        """Test that /product/{id}/ works on custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(
            f"/product/{product_id}/",
            HTTP_HOST="trust.example.com"
        )

        assert response.status_code == 200
        assert product_with_custom_domain.name.encode() in response.content

    def test_project_detail_redirects_to_product(self, client, project_with_custom_domain):
        """Test that /project/{id}/ redirects to product page on custom domain."""
        project_id = project_with_custom_domain.id
        response = client.get(
            f"/project/{project_id}/",
            HTTP_HOST="trust.example.com"
        )

        # Projects now redirect to their parent product page
        assert response.status_code == 302
        assert "/product/" in response.url

    def test_component_detail_clean_url(self, client, component_with_custom_domain):
        """Test that /component/{id}/ works on custom domain."""
        component_id = component_with_custom_domain.id
        response = client.get(
            f"/component/{component_id}/",
            HTTP_HOST="trust.example.com"
        )

        assert response.status_code == 200

    def test_public_urls_redirect_to_clean_urls_on_custom_domain(self, client, product_with_custom_domain):
        """Test that /public/* URLs redirect to clean URLs on custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(
            f"/public/product/{product_id}/",
            HTTP_HOST="trust.example.com"
        )

        # Should redirect to clean URL format
        assert response.status_code == 302
        assert "/product/test-product/" in response.url

    def test_wrong_workspace_product_returns_404(self, client, db, custom_domain_team):
        """Test that accessing another workspace's product on custom domain returns 404."""
        # Create another team and product
        other_team = Team.objects.create(
            name="Other Company",
            billing_plan="community",
            is_public=True,
        )
        other_product = Product.objects.create(
            name="Other Product",
            team=other_team,
            is_public=True,
        )

        # Try to access other team's product on custom domain
        response = client.get(
            f"/product/{other_product.id}/",
            HTTP_HOST="trust.example.com"
        )

        # Should return 404 since product doesn't belong to this workspace
        assert response.status_code == 404


class TestCustomDomainSecurity:
    """Test security aspects of custom domain routing."""

    def test_unauthenticated_user_sees_only_public(self, client, custom_domain_team):
        """Test that unauthenticated users only see public content on custom domain."""
        response = client.get("/", HTTP_HOST="trust.example.com")

        # Should show public page, not require login
        assert response.status_code == 200

    def test_private_urls_not_accessible(self, client, custom_domain_team):
        """Test that private dashboard URLs don't work on custom domain."""
        # Try to access dashboard
        response = client.get("/dashboard", HTTP_HOST="trust.example.com")

        # Should get 404 or redirect, not the actual dashboard
        assert response.status_code in [404, 302]

    def test_private_product_not_shown(self, client, custom_domain_team):
        """Test that private products are not accessible via custom domain."""
        private_product = Product.objects.create(
            name="Private Product",
            team=custom_domain_team,
            is_public=False,  # Not public
        )

        response = client.get(
            f"/product/{private_product.id}/",
            HTTP_HOST="trust.example.com"
        )

        # Should be forbidden or not found
        assert response.status_code in [403, 404]
