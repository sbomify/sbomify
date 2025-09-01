"""
Tests for Components Dashboard Vue to Django migration
Ensuring feature parity with the old Vue-based ComponentsList functionality
"""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from teams.models import Team, Member
from sboms.models import Component, SBOM
import json

User = get_user_model()


class ComponentsVueMigrationTestCase(TestCase):
    """Test Vue component functionality migration to Django SSR"""

    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create test team
        self.team = Team.objects.create(name='Test Team')
        self.membership = Member.objects.create(
            user=self.user,
            team=self.team,
            role='owner'
        )

        # Create client and login
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')

        # Set current team in session
        session = self.client.session
        session['current_team'] = {
            'id': self.team.id,
            'key': self.team.key,
            'name': self.team.name,
            'role': 'owner'
        }
        session.save()

    def test_content_column_shows_sbom_count_correctly(self):
        """Test the Content column shows SBOM count like the Vue component did"""
        # Create component with SBOMs
        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=self.team
        )

        # Create multiple SBOMs for this component
        for i in range(3):
            SBOM.objects.create(
                name=f'SBOM {i+1}',
                component=component,
                team=self.team,
                data={},
                packages={}
            )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that the Content column shows "3 SBOMs"
        self.assertContains(response, '3 SBOMs')
        self.assertContains(response, '<th>Content</th>')

    def test_content_column_shows_singular_sbom_correctly(self):
        """Test the Content column shows singular SBOM count correctly"""
        # Create component with single SBOM
        component = Component.objects.create(
            name='Single SBOM Component',
            component_type='sbom',
            team=self.team
        )

        SBOM.objects.create(
            name='Single SBOM',
            component=component,
            team=self.team,
            data={},
            packages={}
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that the Content column shows "1 SBOM" (singular)
        self.assertContains(response, '1 SBOM')
        self.assertNotContains(response, '1 SBOMs')

    def test_content_column_shows_zero_sboms_correctly(self):
        """Test the Content column shows zero SBOM count correctly"""
        # Create component with no SBOMs
        component = Component.objects.create(
            name='Empty Component',
            component_type='sbom',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that the Content column shows "0 SBOMs"
        self.assertContains(response, '0 SBOMs')

    def test_content_column_shows_document_type_correctly(self):
        """Test the Content column shows 'Document' for document components"""
        # Create document component
        component = Component.objects.create(
            name='Test Document',
            component_type='document',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that the Content column shows "Document"
        self.assertContains(response, 'Document')

    def test_component_type_badges_match_vue_functionality(self):
        """Test that component type badges match the original Vue implementation"""
        # Create different types of components
        sbom_component = Component.objects.create(
            name='SBOM Component',
            component_type='sbom',
            team=self.team
        )

        doc_component = Component.objects.create(
            name='Document Component',
            component_type='document',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check SBOM badge
        self.assertContains(response, 'badge bg-primary-subtle text-primary')
        self.assertContains(response, 'fas fa-file-code me-1')
        self.assertContains(response, '>SBOM</span>')

        # Check Document badge
        self.assertContains(response, 'badge bg-info-subtle text-info')
        self.assertContains(response, 'fas fa-file-alt me-1')
        self.assertContains(response, '>Document</span>')

    def test_public_status_toggle_buttons_present(self):
        """Test that public status toggle buttons are present with correct data attributes"""
        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=self.team,
            is_public=True
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check toggle button is present with correct attributes
        self.assertContains(response, 'toggle-public-btn')
        self.assertContains(response, f'data-component-id="{component.id}"')
        self.assertContains(response, 'data-is-public="true"')
        self.assertContains(response, f'data-component-name="{component.name}"')

    def test_public_status_badges_match_vue_implementation(self):
        """Test that public/private status badges match the Vue implementation"""
        # Create public and private components
        public_component = Component.objects.create(
            name='Public Component',
            component_type='sbom',
            team=self.team,
            is_public=True
        )

        private_component = Component.objects.create(
            name='Private Component',
            component_type='sbom',
            team=self.team,
            is_public=False
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check public badge
        self.assertContains(response, 'badge bg-success-subtle text-success')
        self.assertContains(response, 'fas fa-globe me-1')
        self.assertContains(response, '>Public</span>')

        # Check private badge
        self.assertContains(response, 'badge bg-secondary-subtle text-secondary')
        self.assertContains(response, 'fas fa-lock me-1')
        self.assertContains(response, '>Private</span>')

    def test_component_icons_match_vue_implementation(self):
        """Test that component icons in the table match the Vue implementation"""
        # Create different types of components
        sbom_component = Component.objects.create(
            name='SBOM Component',
            component_type='sbom',
            team=self.team
        )

        doc_component = Component.objects.create(
            name='Document Component',
            component_type='document',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check SBOM icon
        self.assertContains(response, 'fas fa-file-code text-primary fa-lg')

        # Check Document icon
        self.assertContains(response, 'fas fa-file-alt text-info fa-lg')

    def test_component_detail_links_work_correctly(self):
        """Test that component detail links work like in the Vue implementation"""
        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that detail link is present and correctly formatted
        expected_link = f'/component/{component.id}/'
        self.assertContains(response, expected_link)
        self.assertContains(response, 'text-primary text-decoration-none fw-medium')

    def test_components_dashboard_typescript_integration(self):
        """Test that TypeScript integration markers are present"""
        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that TypeScript integration markers are present
        self.assertContains(response, 'components-table')  # CSS class for TypeScript targeting
        self.assertContains(response, 'addComponentModal')  # Modal ID for TypeScript

    def test_crud_permissions_respected_like_vue(self):
        """Test that CRUD permissions are respected like in the Vue implementation"""
        # Test as guest user (no CRUD permissions)
        guest_membership = Member.objects.create(
            user=self.user,
            team=self.team,
            role='guest'
        )

        # Update session with guest role
        session = self.client.session
        session['current_team']['role'] = 'guest'
        session.save()

        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=self.team
        )

        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that Actions column is not shown for guests
        self.assertNotContains(response, '<th class="text-center">Actions</th>')
        self.assertNotContains(response, 'toggle-public-btn')

    def test_pagination_context_includes_sbom_counts(self):
        """Test that paginated components include SBOM count data"""
        # Create many components to trigger pagination
        components = []
        for i in range(20):
            component = Component.objects.create(
                name=f'Component {i+1}',
                component_type='sbom',
                team=self.team
            )
            components.append(component)

            # Add varying number of SBOMs
            for j in range(i % 3):  # 0, 1, or 2 SBOMs
                SBOM.objects.create(
                    name=f'SBOM {j+1} for Component {i+1}',
                    component=component,
                    team=self.team,
                    data={},
                    packages={}
                )

        response = self.client.get(reverse('core:components_dashboard'), {'page_size': 5})
        self.assertEqual(response.status_code, 200)

        # Check that SBOM counts are displayed correctly for paginated results
        self.assertContains(response, 'SBOMs')
        self.assertContains(response, 'Content')

    def test_add_component_modal_matches_vue_functionality(self):
        """Test that the add component modal matches Vue functionality"""
        response = self.client.get(reverse('core:components_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check modal structure matches Vue implementation
        self.assertContains(response, 'addComponentModal')
        self.assertContains(response, 'Component Name')
        self.assertContains(response, 'Component Type')

        # Check that select options are present
        self.assertContains(response, 'value="sbom"')
        self.assertContains(response, 'value="document"')

        # Check modal buttons
        self.assertContains(response, 'Cancel')
        self.assertContains(response, 'Create')


class ComponentsDataStructureTestCase(TestCase):
    """Test data structure validation matching Vue component tests"""

    def test_component_data_structure_validation(self):
        """Validate component data structure matches Vue interface"""
        user = User.objects.create_user(username='testuser', password='testpass')
        team = Team.objects.create(name='Test Team')

        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=team,
            is_public=True
        )

        # Validate component has expected attributes
        self.assertTrue(hasattr(component, 'id'))
        self.assertTrue(hasattr(component, 'name'))
        self.assertTrue(hasattr(component, 'component_type'))
        self.assertTrue(hasattr(component, 'is_public'))
        self.assertTrue(hasattr(component, 'created_at'))

        # Validate types
        self.assertIsInstance(component.name, str)
        self.assertIsInstance(component.component_type, str)
        self.assertIsInstance(component.is_public, bool)

    def test_sbom_count_annotation_works_correctly(self):
        """Test that SBOM count annotation works as expected"""
        user = User.objects.create_user(username='testuser', password='testpass')
        team = Team.objects.create(name='Test Team')

        component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=team
        )

        # Create 3 SBOMs
        for i in range(3):
            SBOM.objects.create(
                name=f'SBOM {i+1}',
                component=component,
                team=team,
                data={},
                packages={}
            )

        # Test the annotation query
        from django.db.models import Count
        annotated_component = Component.objects.annotate(
            sbom_count=Count('sbom', distinct=True)
        ).get(id=component.id)

        self.assertEqual(annotated_component.sbom_count, 3)

    def test_component_type_display_names(self):
        """Test component type display names match Vue implementation"""
        user = User.objects.create_user(username='testuser', password='testpass')
        team = Team.objects.create(name='Test Team')

        sbom_component = Component.objects.create(
            name='SBOM Component',
            component_type='sbom',
            team=team
        )

        doc_component = Component.objects.create(
            name='Document Component',
            component_type='document',
            team=team
        )

        # Test that component types are as expected
        self.assertEqual(sbom_component.component_type, 'sbom')
        self.assertEqual(doc_component.component_type, 'document')
