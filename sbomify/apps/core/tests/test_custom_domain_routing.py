"""
Tests for custom domain routing functionality.

Tests that custom domains correctly route to public pages with clean URLs
and that the middleware properly detects and attaches workspace context.
"""

import pytest
from django.core.cache import cache

from sbomify.apps.core.models import Component, Product
from sbomify.apps.teams.models import Team

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
def component_with_custom_domain(db, custom_domain_team):
    """Create a public component for a team with custom domain."""
    component = Component.objects.create(
        name="Test Component",
        component_type=Component.ComponentType.BOM,
        team=custom_domain_team,
        visibility=Component.Visibility.PUBLIC,
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
        response = client.get(f"/product/{product_id}/", HTTP_HOST="trust.example.com")

        assert response.status_code == 200
        assert product_with_custom_domain.name.encode() in response.content

    def test_component_detail_clean_url(self, client, component_with_custom_domain):
        """Test that /component/{id}/ works on custom domain."""
        component_id = component_with_custom_domain.id
        response = client.get(f"/component/{component_id}/", HTTP_HOST="trust.example.com")

        assert response.status_code == 200

    def test_public_urls_redirect_to_clean_urls_on_custom_domain(self, client, product_with_custom_domain):
        """Test that /public/* URLs redirect to clean URLs on custom domain."""
        product_id = product_with_custom_domain.id
        response = client.get(f"/public/product/{product_id}/", HTTP_HOST="trust.example.com")

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
        response = client.get(f"/product/{other_product.id}/", HTTP_HOST="trust.example.com")

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

        response = client.get(f"/product/{private_product.id}/", HTTP_HOST="trust.example.com")

        # Should be forbidden or not found
        assert response.status_code in [403, 404]


class TestCustomDomainGatedComponents:
    """Gated components must resolve by slug, the same as public ones.

    A gated component is published: the Trust Center landing page and the
    product page both list it, and its page carries the "Request Access" gate.
    Resolving only PUBLIC slugs made every one of those links 404 on a custom
    domain, so the gate was unreachable and the component read as missing.
    """

    @pytest.fixture
    def gated_component(self, db, custom_domain_team):
        return Component.objects.create(
            name="Gated Policy Docs",
            component_type=Component.ComponentType.DOCUMENT,
            team=custom_domain_team,
            visibility=Component.Visibility.GATED,
            is_global=True,
        )

    def test_gated_component_resolves_by_slug(self, client, gated_component):
        response = client.get(f"/component/{gated_component.slug}/", HTTP_HOST="trust.example.com")

        assert response.status_code == 200
        assert b"Request Access" in response.content

    def test_gated_component_is_listed_on_the_landing_page_it_links_from(self, client, gated_component):
        response = client.get("/", HTTP_HOST="trust.example.com")

        assert response.status_code == 200
        assert gated_component.name.encode() in response.content

    def test_private_component_still_does_not_resolve_by_slug(self, client, custom_domain_team):
        """Widening the slug scan to gated must not also publish private ones."""
        private_component = Component.objects.create(
            name="Internal Only",
            component_type=Component.ComponentType.DOCUMENT,
            team=custom_domain_team,
            visibility=Component.Visibility.PRIVATE,
            is_global=True,
        )

        response = client.get(f"/component/{private_component.slug}/", HTTP_HOST="trust.example.com")

        assert response.status_code == 404


class TestCustomDomainNonPublicWorkspace:
    """A workspace that has not published its Trust Center publishes nothing.

    The middleware attaches the workspace that owns a BYOD domain whether or not
    it is public, and only the landing page checked. Everything below it kept
    answering, so `/` said "not found" while an artifact URL rendered the
    workspace's branded page — the one thing a non-public workspace is asking
    not to reveal.
    """

    @pytest.fixture
    def private_domain_team(self, db):
        team = Team.objects.create(
            name="Unlisted Company",
            billing_plan="business",
            custom_domain="private.example.com",
            custom_domain_validated=True,
        )
        team.is_public = False
        team.save(update_fields=["is_public"])
        return team

    @pytest.fixture
    def gated_component(self, db, private_domain_team):
        return Component.objects.create(
            name="Gated Policy Docs",
            component_type=Component.ComponentType.DOCUMENT,
            team=private_domain_team,
            visibility=Component.Visibility.GATED,
            is_global=True,
        )

    @pytest.fixture
    def public_component(self, db, private_domain_team):
        return Component.objects.create(
            name="Public Policy Docs",
            component_type=Component.ComponentType.DOCUMENT,
            team=private_domain_team,
            visibility=Component.Visibility.PUBLIC,
            is_global=True,
        )

    def test_landing_page_is_not_found(self, client, private_domain_team):
        response = client.get("/", HTTP_HOST="private.example.com")

        assert response.status_code == 404

    def test_gated_component_slug_is_not_found(self, client, gated_component):
        response = client.get(f"/component/{gated_component.slug}/", HTTP_HOST="private.example.com")

        assert response.status_code == 404
        assert b"Request Access" not in response.content

    def test_gated_component_id_is_not_found(self, client, gated_component):
        response = client.get(f"/component/{gated_component.id}/", HTTP_HOST="private.example.com")

        assert response.status_code == 404

    def test_public_component_slug_is_not_found(self, client, public_component):
        """Public artifacts are published by the workspace, not past it."""
        response = client.get(f"/component/{public_component.slug}/", HTTP_HOST="private.example.com")

        assert response.status_code == 404

    def test_public_product_is_not_found(self, client, private_domain_team):
        product = Product.objects.create(
            name="Listed Product",
            team=private_domain_team,
            is_public=True,
        )

        response = client.get(f"/product/{product.slug or product.id}/", HTTP_HOST="private.example.com")

        assert response.status_code == 404

    def test_another_workspaces_component_is_not_found(self, client, private_domain_team):
        """The domain resolves to one workspace or to none — never to all of them."""
        other_team = Team.objects.create(
            name="Other Company",
            billing_plan="community",
            is_public=True,
        )
        other_component = Component.objects.create(
            name="Other Component",
            component_type=Component.ComponentType.DOCUMENT,
            team=other_team,
            visibility=Component.Visibility.PUBLIC,
            is_global=True,
        )

        response = client.get(f"/component/{other_component.id}/", HTTP_HOST="private.example.com")

        assert response.status_code == 404
