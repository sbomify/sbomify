"""
Integration tests for components dashboard Django template migration.
Tests the migration from Vue components to Django templates with SSR.
"""
import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from teams.models import Team, Member
from sboms.models import Component

User = get_user_model()


class ComponentsDashboardMigrationTestCase(TestCase):
    """Test components dashboard template migration from Vue to Django SSR."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create test team
        self.team = Team.objects.create(
            name='Test Team',
            key='test-team',
            branding_info={
                'brand_color': '#007bff',
                'accent_color': '#6c757d'
            }
        )

        # Create team membership
        self.membership = Member.objects.create(
            user=self.user,
            team=self.team,
            role='owner',
            is_default_team=True
        )

        # Create test components
        self.sbom_component = Component.objects.create(
            name='Test SBOM Component',
            team=self.team,
            component_type=Component.ComponentType.SBOM,
            is_public=True
        )

        self.document_component = Component.objects.create(
            name='Test Document Component',
            team=self.team,
            component_type=Component.ComponentType.DOCUMENT,
            is_public=False
        )

        self.private_component = Component.objects.create(
            name='Private Component',
            team=self.team,
            component_type=Component.ComponentType.SBOM,
            is_public=False
        )

    def login_user(self):
        """Helper method to log in the test user."""
        self.client.login(username='testuser', password='testpass123')
        # Set up session for current team
        session = self.client.session
        session['current_team'] = {
            'id': self.team.id,
            'name': self.team.name,
            'key': self.team.key,
            'role': 'owner'
        }
        session.save()

    def test_components_dashboard_redirects_without_trailing_slash(self):
        """Test that /components redirects to /components/ properly."""
        self.login_user()
        response = self.client.get('/components')
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response.url.endswith('/components/'))

    def test_components_dashboard_requires_authentication(self):
        """Test that components dashboard requires authentication."""
        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_components_dashboard_renders_correctly(self):
        """Test that components dashboard renders with Django templates."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sbomify Components')
        self.assertContains(response, 'Manage individual software components')

        # Check that Django template structure is present (not Vue)
        self.assertContains(response, 'components-table')
        self.assertContains(response, 'addComponentModal')

        # Ensure no Vue component placeholders exist
        self.assertNotContains(response, 'vc-components-list')
        self.assertNotContains(response, 'vc-add-component-form')

    def test_components_dashboard_displays_components(self):
        """Test that components are displayed in the table."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Check components are displayed
        self.assertContains(response, self.sbom_component.name)
        self.assertContains(response, self.document_component.name)
        self.assertContains(response, self.private_component.name)

        # Check component types are displayed
        self.assertContains(response, 'SBOM')
        self.assertContains(response, 'Document')

        # Check public/private status badges
        self.assertContains(response, 'Public')
        self.assertContains(response, 'Private')

    def test_components_dashboard_pagination(self):
        """Test pagination functionality works with Django templates."""
        self.login_user()

        # Create enough components to trigger pagination (20 + existing 3 = 23 total)
        for i in range(20):
            Component.objects.create(
                name=f'Component {i}',
                team=self.team,
                component_type=Component.ComponentType.SBOM
            )

        # Test with small page size to force pagination
        response = self.client.get(reverse('core:components_dashboard'), {'page_size': 5})
        self.assertEqual(response.status_code, 200)

        # Check that pagination context is available and working
        self.assertIn('pagination_meta', response.context)
        self.assertGreater(response.context['pagination_meta'].paginator.count, 5)

        # Test that only 5 components are shown on this page
        components_shown = len(response.context['components'])
        self.assertEqual(components_shown, 5)

    def test_components_dashboard_permissions(self):
        """Test that permission-based content is displayed correctly."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        # Owner should see add button and actions
        self.assertContains(response, 'Add Component')
        self.assertContains(response, 'Actions')

        # Change to guest role
        self.membership.role = 'guest'
        self.membership.save()

        # Update session to reflect new role
        session = self.client.session
        session['current_team'] = {
            'id': self.team.id,
            'name': self.team.name,
            'key': self.team.key,
            'role': 'guest'
        }
        session.save()

        # Get fresh response with guest permissions
        response = self.client.get(reverse('core:components_dashboard'))

        # Guest should not see Actions column header (key indicator of permissions)
        self.assertNotContains(response, '<th class="text-center">Actions</th>')
        # Guest should not see the add button in header
        self.assertNotContains(response, 'data-bs-target="#addComponentModal"')

    def test_add_component_modal_rendered(self):
        """Test that add component modal is rendered with correct fields."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        # Check modal is present
        self.assertContains(response, 'addComponentModal')
        self.assertContains(response, 'Add Component')

        # Check form fields are present
        self.assertContains(response, 'Component Name')
        self.assertContains(response, 'Component Type')

        # Check component type options
        self.assertContains(response, 'SBOM')
        self.assertContains(response, 'Document')

    def test_component_table_icons_and_styling(self):
        """Test that component icons and styling are applied correctly."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        # Check component type icons
        self.assertContains(response, 'fa-file-code')  # SBOM icon
        self.assertContains(response, 'fa-file-alt')   # Document icon

        # Check status icons
        self.assertContains(response, 'fa-globe')      # Public icon
        self.assertContains(response, 'fa-lock')       # Private icon

    def test_no_components_empty_state(self):
        """Test empty state when no components exist."""
        # Delete all components
        Component.objects.all().delete()

        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No components added')
        self.assertContains(response, 'Create your first component')

    def test_components_dashboard_context_data(self):
        """Test that proper context data is passed to template."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        # Check context contains expected data
        self.assertIn('components', response.context)
        self.assertIn('has_crud_permissions', response.context)
        self.assertIn('component_form_fields', response.context)
        self.assertIn('pagination_meta', response.context)

        # Check permission is correct for owner
        self.assertTrue(response.context['has_crud_permissions'])

        # Check form fields are properly configured
        form_fields = response.context['component_form_fields']
        self.assertEqual(len(form_fields), 2)
        self.assertEqual(form_fields[0]['name'], 'name')
        self.assertEqual(form_fields[1]['name'], 'component_type')

    def test_component_links_work_correctly(self):
        """Test that component links in the table work correctly."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        # Check component detail links
        component_url = f'/component/{self.sbom_component.id}/'
        self.assertContains(response, component_url)

    def test_responsive_table_structure(self):
        """Test that table has responsive attributes for mobile."""
        self.login_user()
        response = self.client.get(reverse('core:components_dashboard'))

        # Check responsive table wrapper
        self.assertContains(response, 'table-responsive')

        # Check data-label attributes for mobile
        self.assertContains(response, 'data-label="Component"')
        self.assertContains(response, 'data-label="Type"')
        self.assertContains(response, 'data-label="Public?"')
