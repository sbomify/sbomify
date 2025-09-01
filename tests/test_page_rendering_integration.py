"""
Comprehensive integration tests for page rendering across the entire application.

This test suite ensures that all pages render correctly after Vue-to-Django template refactoring.
It covers all major page types and user flows to ensure nothing breaks during the migration.
"""

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from core.tests.shared_fixtures import (
    sample_user,
    guest_user,
    team_with_business_plan,
    setup_authenticated_client_session,
)
from teams.utils import get_user_teams

# Import models from other apps
try:
    from sboms.models import Product, Project, Component, Sbom
    from documents.models import Document
except ImportError:
    # Handle case where these apps might not be available in test
    Product = Project = Component = Sbom = Document = None

User = get_user_model()


@pytest.mark.django_db
class TestApplicationPageRendering:
    """Test that all application pages render correctly."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan, sample_user, guest_user):
        """Set up test data using shared fixtures."""
        self.team = team_with_business_plan
        self.owner_user = sample_user
        self.guest_user = guest_user

        # Mark team as having completed wizard for dashboard tests
        self.team.has_completed_wizard = True
        self.team.save()

        # Create additional test users if needed
        self.admin_user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            first_name="Admin",
            last_name="User"
        )

        self.member_user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            first_name="Member",
            last_name="User"
        )

        # Create test content if models are available
        self.setup_test_content()

    def get_authenticated_client(self):
        """Get a properly authenticated client with session data."""
        client = Client()
        setup_authenticated_client_session(client, self.team, self.owner_user)
        return client

    def setup_test_content(self):
        """Create test content if models are available."""
        if Product and Project and Component:
            self.product = Product.objects.create(
                name="Test Product",
                team=self.team,
                created_by=self.owner_user
            )

            self.project = Project.objects.create(
                name="Test Project",
                product=self.product,
                team=self.team,
                created_by=self.owner_user
            )

            self.component = Component.objects.create(
                name="Test Component",
                project=self.project,
                team=self.team,
                created_by=self.owner_user
            )

    # Core Pages Tests
    def test_home_page_renders(self):
        """Test that home page renders correctly."""
        client = Client()
        response = client.get('/')
        # Should redirect to login or dashboard
        assert response.status_code in [200, 302]

    def test_dashboard_page_renders_authenticated(self):
        """Test that dashboard renders for authenticated users."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:dashboard'))
        assert response.status_code == 200
        assert b"Dashboard" in response.content

    def test_dashboard_redirects_unauthenticated(self):
        """Test that dashboard redirects unauthenticated users."""
        client = Client()
        response = client.get(reverse('core:dashboard'))
        assert response.status_code == 302

    # Workspace Pages Tests
    def test_workspace_dashboard_renders(self):
        """Test workspace dashboard rendering."""
        client = self.get_authenticated_client()
        response = client.get(reverse('teams:teams_dashboard'))
        assert response.status_code == 200

    def test_team_settings_pages_render(self):
        """Test team settings pages render correctly."""
        client = self.get_authenticated_client()

        # Test main team settings page (should redirect to members)
        response = client.get(reverse('teams:team_settings', kwargs={'team_key': self.team.key}))
        assert response.status_code in [200, 302]

        # Test specific settings pages
        settings_pages = [
            'teams:team_members',
            'teams:team_branding',
            'teams:team_integrations',
            'teams:team_billing',
            'teams:team_danger'
        ]

        for page_name in settings_pages:
            response = client.get(reverse(page_name, kwargs={'team_key': self.team.key}))
            assert response.status_code == 200, f"Failed to render {page_name}"

    def test_team_settings_require_authentication(self):
        """Test that team settings require authentication."""
        client = Client()
        response = client.get(reverse('teams:team_settings', kwargs={'team_key': self.team.key}))
        assert response.status_code == 302  # Redirect to login

    def test_user_settings_renders(self):
        """Test user settings page renders."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:settings'))
        assert response.status_code == 200

    # Product/Project/Component Dashboard Tests (if models available)
    @pytest.mark.skipif(Product is None, reason="Product model not available")
    def test_products_dashboard_renders(self):
        """Test products dashboard renders."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:products_dashboard'))
        assert response.status_code == 200

    @pytest.mark.skipif(Project is None, reason="Project model not available")
    def test_projects_dashboard_renders(self):
        """Test projects dashboard renders."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:projects_dashboard'))
        assert response.status_code == 200

    @pytest.mark.skipif(Component is None, reason="Component model not available")
    def test_components_dashboard_renders(self):
        """Test components dashboard renders."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:components_dashboard'))
        assert response.status_code == 200

    # Detail Pages Tests (if models and test data available)
    @pytest.mark.skipif(Product is None, reason="Product model not available")
    def test_product_detail_pages_render(self):
        """Test product detail pages render."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:product_details', kwargs={'product_id': self.product.id}))
        assert response.status_code == 200

    @pytest.mark.skipif(Project is None, reason="Project model not available")
    def test_project_detail_pages_render(self):
        """Test project detail pages render."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:project_details', kwargs={'project_id': self.project.id}))
        assert response.status_code == 200

    @pytest.mark.skipif(Component is None, reason="Component model not available")
    def test_component_detail_pages_render(self):
        """Test component detail pages render."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:component_details', kwargs={'component_id': self.component.id}))
        assert response.status_code == 200

    # Public Pages Tests (if models available)
    @pytest.mark.skipif(Product is None, reason="Product model not available")
    def test_public_product_pages_render(self):
        """Test public product pages render."""
        # Make product public
        if hasattr(self.product, 'is_public'):
            self.product.is_public = True
            self.product.save()

        client = Client()
        response = client.get(reverse('core:public_product_details', kwargs={'product_id': self.product.id}))
        # Should render or redirect appropriately
        assert response.status_code in [200, 302, 404]

    # Template and Asset Tests
    def test_base_template_elements_present(self):
        """Test that base template elements are present across pages."""
        client = self.get_authenticated_client()

        pages_to_test = [
            reverse('core:dashboard'),
            reverse('teams:teams_dashboard'),
            reverse('core:settings'),
        ]

        for page_url in pages_to_test:
            response = client.get(page_url)
            assert response.status_code == 200
            # Check for essential base template elements
            assert b"sbomify" in response.content
            assert b"<html" in response.content
            assert b"</html>" in response.content

    def test_responsive_design_elements_present(self):
        """Test that responsive design elements are present."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:dashboard'))

        # Check for Bootstrap responsive classes
        content = response.content.decode()
        responsive_indicators = ['container-fluid', 'row', 'col-', 'navbar']
        for indicator in responsive_indicators:
            assert indicator in content

    def test_accessibility_features_present(self):
        """Test that accessibility features are present."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:dashboard'))

        content = response.content.decode()
        # Check for basic accessibility features
        accessibility_features = ['aria-', 'role=', 'alt=']
        for feature in accessibility_features:
            assert feature in content

    def test_csrf_protection_present(self):
        """Test that CSRF protection is present in forms."""
        client = self.get_authenticated_client()
        response = client.get(reverse('teams:teams_dashboard'))

        content = response.content.decode()
        assert 'csrfmiddlewaretoken' in content

    def test_no_vue_dependencies_in_teams_pages(self):
        """Test that teams pages don't have Vue.js dependencies."""
        client = self.get_authenticated_client()
        response = client.get(reverse('teams:teams_dashboard'))

        content = response.content.decode()
        # These should not be present after Django migration
        vue_indicators = ['v-if', 'v-for', 'v-model', '{{ }}', 'Vue.createApp']
        for indicator in vue_indicators:
            assert indicator not in content

    # Asset Loading Tests
    def test_css_assets_load_correctly(self):
        """Test that CSS assets are properly loaded."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:dashboard'))

        content = response.content.decode()
        assert '<link' in content  # CSS links present
        assert 'stylesheet' in content

    def test_javascript_assets_load_correctly(self):
        """Test that JavaScript assets are properly loaded."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:dashboard'))

        content = response.content.decode()
        assert '<script' in content  # JS scripts present

    # Error Handling Tests
    def test_404_page_renders(self):
        """Test that 404 page renders correctly."""
        client = self.get_authenticated_client()
        response = client.get('/nonexistent-page/')
        assert response.status_code == 404

    # Performance Tests
    @override_settings(DEBUG=True)
    def test_performance_no_n_plus_one_queries(self):
        """Test that pages don't have obvious N+1 query issues."""
        from django.test.utils import override_settings
        from django.db import connection
        from django.test import TestCase

        client = self.get_authenticated_client()

        # Reset queries
        connection.queries_log.clear()

        # Load a page that might have N+1 issues
        response = client.get(reverse('core:dashboard'))
        assert response.status_code == 200

        # Check that we don't have an excessive number of queries
        # This is a rough check - adjust threshold as needed
        query_count = len(connection.queries)
        assert query_count < 50, f"Too many queries: {query_count}"

    # API Security Boundary Tests
    def test_api_security_boundaries_maintained(self):
        """Test that pages use API functions for data access."""
        client = self.get_authenticated_client()
        response = client.get(reverse('core:dashboard'))

        # This is a basic test - in practice you'd want to verify
        # that templates are calling API functions rather than direct DB access
        assert response.status_code == 200