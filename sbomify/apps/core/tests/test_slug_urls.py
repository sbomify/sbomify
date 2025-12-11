"""
Tests for slug-based URL routing on custom domains.

These tests verify that slug-based URLs work correctly on custom domains
while ID-based URLs continue to work on the main app domain.
"""

import pytest
from django.core.cache import cache

from sbomify.apps.core.models import Component, Product, Project, Release
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
    team.is_public = True
    team.save(update_fields=["is_public"])
    return team


@pytest.fixture
def product_with_slug(db, custom_domain_team):
    """Create a public product with a predictable slug."""
    product = Product.objects.create(
        name="My Test Product",  # slug will be "my-test-product"
        description="Test Description",
        team=custom_domain_team,
        is_public=True,
    )
    return product


@pytest.fixture
def project_with_slug(db, custom_domain_team, product_with_slug):
    """Create a public project with a predictable slug."""
    project = Project.objects.create(
        name="My Test Project",  # slug will be "my-test-project"
        team=custom_domain_team,
        is_public=True,
    )
    project.products.add(product_with_slug)
    return project


@pytest.fixture
def component_with_slug(db, custom_domain_team):
    """Create a public component with a predictable slug."""
    component = Component.objects.create(
        name="My Test Component",  # slug will be "my-test-component"
        component_type=Component.ComponentType.SBOM,
        team=custom_domain_team,
        is_public=True,
        is_global=True,
    )
    return component


@pytest.fixture
def release_with_slug(db, product_with_slug):
    """Create a release with a predictable slug."""
    release = Release.objects.create(
        name="v1.0.0",  # slug will be "v100"
        product=product_with_slug,
        description="First release",
    )
    return release


class TestSlugGeneration:
    """Test that slugs are correctly generated from names."""

    def test_product_slug(self, product_with_slug):
        """Test that product slug is generated correctly."""
        assert product_with_slug.slug == "my-test-product"

    def test_project_slug(self, project_with_slug):
        """Test that project slug is generated correctly."""
        assert project_with_slug.slug == "my-test-project"

    def test_component_slug(self, component_with_slug):
        """Test that component slug is generated correctly."""
        assert component_with_slug.slug == "my-test-component"

    def test_release_slug(self, release_with_slug):
        """Test that release slug is generated correctly."""
        assert release_with_slug.slug == "v100"

    def test_unicode_name_slug(self, db, custom_domain_team):
        """Test that unicode names produce valid slugs."""
        product = Product.objects.create(
            name="Café Product",
            team=custom_domain_team,
            is_public=True,
        )
        # With allow_unicode=True, the slug preserves unicode characters
        assert product.slug == "café-product"

    def test_special_characters_slug(self, db, custom_domain_team):
        """Test that special characters are handled in slugs."""
        product = Product.objects.create(
            name="Product #1 (Test) - Version",
            team=custom_domain_team,
            is_public=True,
        )
        assert product.slug == "product-1-test-version"


class TestSlugRoutingOnCustomDomain:
    """Test slug-based URL routing on custom domains."""

    def test_product_by_slug(self, client, product_with_slug):
        """Test that /product/{slug}/ works on custom domain."""
        response = client.get(
            f"/product/{product_with_slug.slug}/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 200
        assert product_with_slug.name.encode() in response.content

    def test_project_by_slug(self, client, project_with_slug):
        """Test that /project/{slug}/ works on custom domain."""
        response = client.get(
            f"/project/{project_with_slug.slug}/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 200

    def test_component_by_slug(self, client, component_with_slug):
        """Test that /component/{slug}/ works on custom domain."""
        response = client.get(
            f"/component/{component_with_slug.slug}/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 200

    def test_product_id_fallback_on_custom_domain(self, client, product_with_slug):
        """Test that ID-based URLs still work on custom domain for backward compatibility."""
        response = client.get(
            f"/product/{product_with_slug.id}/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 200
        assert product_with_slug.name.encode() in response.content

    def test_nonexistent_slug_returns_404(self, client, custom_domain_team):
        """Test that non-existent slug returns 404."""
        response = client.get(
            "/product/nonexistent-product-slug/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 404

    def test_wrong_workspace_slug_returns_404(self, client, db, custom_domain_team):
        """Test that accessing another workspace's product by slug returns 404."""
        # Create another team and product with same name
        other_team = Team.objects.create(
            name="Other Company",
            billing_plan="community",
            is_public=True,
        )
        other_product = Product.objects.create(
            name="My Test Product",  # Same name, different team
            team=other_team,
            is_public=True,
        )

        # Try to access other team's product on custom domain using slug
        response = client.get(
            f"/product/{other_product.slug}/",
            HTTP_HOST="trust.example.com"
        )

        # Should return 404 since we're looking for the slug in the custom domain's team
        assert response.status_code == 404


class TestSlugRoutingOnMainDomain:
    """Test that ID-based URLs still work on main app domain."""

    def test_product_by_id_on_main_domain(self, client, product_with_slug):
        """Test that /public/product/{id}/ works on main app domain."""
        response = client.get(f"/public/product/{product_with_slug.id}/")
        assert response.status_code == 200
        assert product_with_slug.name.encode() in response.content

    def test_project_by_id_on_main_domain(self, client, project_with_slug):
        """Test that /public/project/{id}/ works on main app domain."""
        response = client.get(f"/public/project/{project_with_slug.id}/")
        assert response.status_code == 200

    def test_component_by_id_on_main_domain(self, client, component_with_slug):
        """Test that /public/component/{id}/ works on main app domain."""
        response = client.get(f"/public/component/{component_with_slug.id}/")
        assert response.status_code == 200


class TestProductReleasesSlug:
    """Test slug-based URL routing for product releases."""

    def test_product_releases_by_slug(self, client, product_with_slug):
        """Test that /product/{slug}/releases/ works on custom domain."""
        response = client.get(
            f"/product/{product_with_slug.slug}/releases/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 200

    def test_release_by_slug(self, client, product_with_slug, release_with_slug):
        """Test that /product/{product_slug}/release/{release_slug}/ works on custom domain."""
        response = client.get(
            f"/product/{product_with_slug.slug}/release/{release_with_slug.slug}/",
            HTTP_HOST="trust.example.com"
        )
        assert response.status_code == 200


class TestSlugResolution:
    """Test the slug resolution utility functions."""

    def test_resolve_product_by_slug(self, rf, product_with_slug, custom_domain_team):
        """Test resolve_product_identifier with slug on custom domain."""
        from sbomify.apps.core.url_utils import resolve_product_identifier

        # Simulate custom domain request
        request = rf.get("/product/my-test-product/")
        request.is_custom_domain = True
        request.custom_domain_team = custom_domain_team

        product = resolve_product_identifier(request, "my-test-product")
        assert product is not None
        assert product.id == product_with_slug.id

    def test_resolve_product_by_id_fallback(self, rf, product_with_slug, custom_domain_team):
        """Test resolve_product_identifier with ID fallback on custom domain."""
        from sbomify.apps.core.url_utils import resolve_product_identifier

        # Simulate custom domain request with ID
        request = rf.get(f"/product/{product_with_slug.id}/")
        request.is_custom_domain = True
        request.custom_domain_team = custom_domain_team

        product = resolve_product_identifier(request, product_with_slug.id)
        assert product is not None
        assert product.id == product_with_slug.id

    def test_resolve_product_by_id_on_main_domain(self, rf, product_with_slug):
        """Test resolve_product_identifier with ID on main app domain."""
        from sbomify.apps.core.url_utils import resolve_product_identifier

        # Simulate main app request
        request = rf.get(f"/public/product/{product_with_slug.id}/")
        request.is_custom_domain = False

        product = resolve_product_identifier(request, product_with_slug.id)
        assert product is not None
        assert product.id == product_with_slug.id

    def test_resolve_nonexistent_slug_returns_none(self, rf, custom_domain_team):
        """Test resolve_product_identifier returns None for non-existent slug."""
        from sbomify.apps.core.url_utils import resolve_product_identifier

        request = rf.get("/product/nonexistent-slug/")
        request.is_custom_domain = True
        request.custom_domain_team = custom_domain_team

        product = resolve_product_identifier(request, "nonexistent-slug")
        assert product is None


class TestUrlGeneration:
    """Test the get_public_path function with slugs."""

    def test_product_url_with_slug_on_custom_domain(self):
        """Test product URL generation with slug on custom domain."""
        from sbomify.apps.core.url_utils import get_public_path

        url = get_public_path("product", "abc123", is_custom_domain=True, slug="my-product")
        assert url == "/product/my-product/"

    def test_product_url_on_main_domain(self):
        """Test product URL generation on main app domain (uses ID)."""
        from sbomify.apps.core.url_utils import get_public_path

        url = get_public_path("product", "abc123", is_custom_domain=False, slug="my-product")
        assert url == "/public/product/abc123/"

    def test_release_url_with_slugs_on_custom_domain(self):
        """Test release URL generation with slugs on custom domain."""
        from sbomify.apps.core.url_utils import get_public_path

        url = get_public_path(
            "release",
            "rel123",
            is_custom_domain=True,
            product_id="prod123",
            product_slug="my-product",
            release_slug="v100",
        )
        assert url == "/product/my-product/release/v100/"

    def test_component_url_with_slug_on_custom_domain(self):
        """Test component URL generation with slug on custom domain."""
        from sbomify.apps.core.url_utils import get_public_path

        url = get_public_path("component", "comp123", is_custom_domain=True, slug="my-component")
        assert url == "/component/my-component/"

    def test_component_detailed_url_with_slug(self):
        """Test detailed component URL generation with slug on custom domain."""
        from sbomify.apps.core.url_utils import get_public_path

        url = get_public_path(
            "component", "comp123", is_custom_domain=True, slug="my-component", detailed=True
        )
        assert url == "/component/my-component/detailed/"
