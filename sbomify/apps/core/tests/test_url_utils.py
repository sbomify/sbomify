"""
Tests for URL generation utilities.

Tests the helper functions in url_utils.py that generate URLs
with custom domain support.
"""

import pytest
from django.conf import settings
from django.http import HttpRequest
from django.test import RequestFactory

from sbomify.apps.core.url_utils import (
    build_custom_domain_url,
    get_public_path,
    get_public_url_base,
    is_public_url_path,
    should_redirect_to_custom_domain,
)
from sbomify.apps.teams.models import Team


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
    return team


@pytest.fixture
def team_without_custom_domain(db):
    """Create a team without a custom domain."""
    team = Team.objects.create(
        name="Regular Company",
        billing_plan="community",
        is_public=True,
    )
    return team


@pytest.fixture
def request_factory():
    """Provide a request factory."""
    return RequestFactory()


@pytest.mark.django_db
class TestGetPublicPath:
    """Test the get_public_path utility function."""

    def test_workspace_path_custom_domain(self):
        """Test workspace path on custom domain."""
        path = get_public_path('workspace', 'workspace_id', is_custom_domain=True)
        assert path == '/'

    def test_workspace_path_main_domain(self):
        """Test workspace path on main domain."""
        path = get_public_path('workspace', 'workspace_id', is_custom_domain=False, workspace_key='abc123')
        assert path == '/public/workspace/abc123/'

    def test_product_path_custom_domain(self):
        """Test product path on custom domain."""
        path = get_public_path('product', 'prod123', is_custom_domain=True)
        assert path == '/product/prod123/'

    def test_product_path_main_domain(self):
        """Test product path on main domain."""
        path = get_public_path('product', 'prod123', is_custom_domain=False)
        assert path == '/public/product/prod123/'

    def test_project_path_custom_domain(self):
        """Test project path on custom domain."""
        path = get_public_path('project', 'proj123', is_custom_domain=True)
        assert path == '/project/proj123/'

    def test_project_path_main_domain(self):
        """Test project path on main domain."""
        path = get_public_path('project', 'proj123', is_custom_domain=False)
        assert path == '/public/project/proj123/'

    def test_component_path_custom_domain(self):
        """Test component path on custom domain."""
        path = get_public_path('component', 'comp123', is_custom_domain=True)
        assert path == '/component/comp123/'

    def test_component_detailed_path_custom_domain(self):
        """Test component detailed path on custom domain."""
        path = get_public_path('component', 'comp123', is_custom_domain=True, detailed=True)
        assert path == '/component/comp123/detailed/'

    def test_component_path_main_domain(self):
        """Test component path on main domain."""
        path = get_public_path('component', 'comp123', is_custom_domain=False)
        assert path == '/public/component/comp123/'

    def test_document_path_custom_domain(self):
        """Test document path on custom domain."""
        path = get_public_path('document', 'doc123', is_custom_domain=True)
        assert path == '/document/doc123/'

    def test_document_path_main_domain(self):
        """Test document path on main domain."""
        path = get_public_path('document', 'doc123', is_custom_domain=False)
        assert path == '/public/document/doc123/'

    def test_release_path_custom_domain(self):
        """Test release path on custom domain."""
        path = get_public_path('release', 'rel123', is_custom_domain=True, product_id='prod123')
        assert path == '/product/prod123/release/rel123/'

    def test_release_path_main_domain(self):
        """Test release path on main domain."""
        path = get_public_path('release', 'rel123', is_custom_domain=False, product_id='prod123')
        assert path == '/public/product/prod123/release/rel123/'

    def test_product_releases_path_custom_domain(self):
        """Test product releases path on custom domain."""
        path = get_public_path('product_releases', 'prod123', is_custom_domain=True)
        assert path == '/product/prod123/releases/'

    def test_product_releases_path_main_domain(self):
        """Test product releases path on main domain."""
        path = get_public_path('product_releases', 'prod123', is_custom_domain=False)
        assert path == '/public/product/prod123/releases/'

    def test_invalid_resource_type(self):
        """Test that invalid resource type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown resource type"):
            get_public_path('invalid_type', 'id123', is_custom_domain=False)

    def test_release_without_product_id(self):
        """Test that release without product_id raises ValueError."""
        with pytest.raises(ValueError, match="product_id is required"):
            get_public_path('release', 'rel123', is_custom_domain=True)


@pytest.mark.django_db
class TestBuildCustomDomainUrl:
    """Test the build_custom_domain_url utility function."""

    def test_build_url_with_custom_domain(self, custom_domain_team):
        """Test building a URL with custom domain."""
        url = build_custom_domain_url(custom_domain_team, '/product/123/', secure=True)
        assert url == 'https://trust.example.com/product/123/'

    def test_build_url_http(self, custom_domain_team):
        """Test building a URL with HTTP."""
        url = build_custom_domain_url(custom_domain_team, '/product/123/', secure=False)
        assert url == 'http://trust.example.com/product/123/'

    def test_build_url_adds_leading_slash(self, custom_domain_team):
        """Test that leading slash is added if missing."""
        url = build_custom_domain_url(custom_domain_team, 'product/123/', secure=True)
        assert url == 'https://trust.example.com/product/123/'

    def test_build_url_without_custom_domain(self, team_without_custom_domain):
        """Test building URL for team without custom domain."""
        url = build_custom_domain_url(team_without_custom_domain, '/product/123/')
        assert url == ''

    def test_build_url_none_team(self):
        """Test building URL with None team."""
        url = build_custom_domain_url(None, '/product/123/')
        assert url == ''


@pytest.mark.django_db
class TestShouldRedirectToCustomDomain:
    """Test the should_redirect_to_custom_domain utility function."""

    def test_redirect_needed_on_main_domain(self, request_factory, custom_domain_team):
        """Test that redirect is needed when on main app domain."""
        request = request_factory.get('/')
        request.META['HTTP_HOST'] = 'app.sbomify.com'
        request.is_custom_domain = False

        should_redirect = should_redirect_to_custom_domain(request, custom_domain_team)
        assert should_redirect is True

    def test_no_redirect_on_custom_domain(self, request_factory, custom_domain_team):
        """Test that no redirect when already on custom domain."""
        request = request_factory.get('/')
        request.META['HTTP_HOST'] = 'trust.example.com'
        request.is_custom_domain = True
        request.custom_domain_team = custom_domain_team

        should_redirect = should_redirect_to_custom_domain(request, custom_domain_team)
        assert should_redirect is False

    def test_no_redirect_without_custom_domain(self, request_factory, team_without_custom_domain):
        """Test that no redirect when team has no custom domain."""
        request = request_factory.get('/')
        request.META['HTTP_HOST'] = 'app.sbomify.com'
        request.is_custom_domain = False

        should_redirect = should_redirect_to_custom_domain(request, team_without_custom_domain)
        assert should_redirect is False

    def test_no_redirect_unvalidated_domain(self, request_factory, db):
        """Test that no redirect for unvalidated custom domain."""
        team = Team.objects.create(
            name="Unvalidated",
            custom_domain="pending.example.com",
            custom_domain_validated=False,
        )
        request = request_factory.get('/')
        request.META['HTTP_HOST'] = 'app.sbomify.com'

        should_redirect = should_redirect_to_custom_domain(request, team)
        assert should_redirect is False

    def test_no_redirect_none_team(self, request_factory):
        """Test that no redirect with None team."""
        request = request_factory.get('/')

        should_redirect = should_redirect_to_custom_domain(request, None)
        assert should_redirect is False


@pytest.mark.django_db
class TestGetPublicUrlBase:
    """Test the get_public_url_base utility function."""

    def test_custom_domain_url_base(self, request_factory, custom_domain_team):
        """Test URL base for custom domain."""
        request = request_factory.get('/', secure=True)
        request.custom_domain_team = custom_domain_team

        base_url = get_public_url_base(request, custom_domain_team)
        assert base_url == 'https://trust.example.com'

    def test_custom_domain_url_base_http(self, request_factory, custom_domain_team):
        """Test URL base for custom domain with HTTP."""
        request = request_factory.get('/', secure=False)
        request.custom_domain_team = custom_domain_team

        base_url = get_public_url_base(request, custom_domain_team)
        assert base_url == 'http://trust.example.com'

    def test_main_app_url_base(self, request_factory, team_without_custom_domain):
        """Test URL base for team without custom domain."""
        request = request_factory.get('/')

        base_url = get_public_url_base(request, team_without_custom_domain)
        assert base_url == settings.APP_BASE_URL

    def test_url_base_from_request_attribute(self, request_factory, custom_domain_team):
        """Test URL base detection from request.custom_domain_team."""
        request = request_factory.get('/', secure=True)
        request.custom_domain_team = custom_domain_team

        # Don't pass team parameter, should detect from request
        base_url = get_public_url_base(request, None)
        assert base_url == 'https://trust.example.com'


@pytest.mark.django_db
class TestIsPublicUrlPath:
    """Test the is_public_url_path utility function."""

    def test_public_workspace_path(self):
        """Test that /public/workspace/ is recognized."""
        assert is_public_url_path('/public/workspace/abc123/') is True

    def test_public_product_path(self):
        """Test that /public/product/ is recognized."""
        assert is_public_url_path('/public/product/123/') is True

    def test_public_project_path(self):
        """Test that /public/project/ is recognized."""
        assert is_public_url_path('/public/project/456/') is True

    def test_public_component_path(self):
        """Test that /public/component/ is recognized."""
        assert is_public_url_path('/public/component/789/') is True

    def test_public_document_path(self):
        """Test that /public/document/ is recognized."""
        assert is_public_url_path('/public/document/doc1/') is True

    def test_private_product_path(self):
        """Test that /product/ (without public) is not recognized."""
        assert is_public_url_path('/product/123/') is False

    def test_dashboard_path(self):
        """Test that /dashboard is not recognized."""
        assert is_public_url_path('/dashboard') is False

    def test_api_path(self):
        """Test that /api/ is not recognized."""
        assert is_public_url_path('/api/v1/products/') is False

    def test_root_path(self):
        """Test that / is not recognized."""
        assert is_public_url_path('/') is False
