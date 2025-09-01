"""
Tests for Component Detailed Page Vue to Django migration
Testing the SBOM upload, metadata display, and actions functionality
"""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from teams.models import Team, Member
from sboms.models import Component, SBOM
from unittest.mock import patch
import json

User = get_user_model()


class ComponentDetailedPageMigrationTestCase(TestCase):
    """Test component detailed page Vue to Django SSR migration"""

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

        # Create test component
        self.component = Component.objects.create(
            name='Test Component',
            component_type='sbom',
            team=self.team,
            is_public=False
        )

    def test_sbom_component_detailed_page_renders(self):
        """Test that SBOM component detailed page renders correctly with new templates"""
        # Create an SBOM for the component
        sbom = SBOM.objects.create(
            name='Test SBOM',
            component=self.component,
            format='spdx',
            format_version='2.3',
            version='1.0.0',
            source='manual_upload'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check that SBOM upload card is present
        self.assertContains(response, 'Upload SBOM File')
        self.assertContains(response, 'Drop your SBOM file here')

        # Check that SBOM metadata card is present
        self.assertContains(response, 'SBOM Metadata')
        self.assertContains(response, 'Uploaded On')
        self.assertContains(response, 'Source')
        self.assertContains(response, 'Format')

        # Check that SBOM actions card is present
        self.assertContains(response, 'Actions')
        self.assertContains(response, 'Download SBOM')
        self.assertContains(response, 'Browse SBOM')
        self.assertContains(response, 'View Vulnerabilities')

    def test_sbom_metadata_display_correct_data(self):
        """Test that SBOM metadata displays the correct information"""
        sbom = SBOM.objects.create(
            name='Test SBOM v2',
            component=self.component,
            format='cyclonedx',
            format_version='1.4',
            version='2.0.0',
            source='api',
            sbom_filename='test-sbom.json',
            ntia_compliance_status='compliant'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check SBOM format display
        self.assertContains(response, 'CycloneDX')
        self.assertContains(response, '1.4')

        # Check version display
        self.assertContains(response, '2.0.0')

        # Check source display
        self.assertContains(response, 'API')

        # Check filename display
        self.assertContains(response, 'test-sbom.json')

        # Check NTIA compliance
        self.assertContains(response, 'Compliant')

        # Check SBOM ID is present
        self.assertContains(response, sbom.id)

    def test_sbom_actions_with_permissions(self):
        """Test that SBOM actions show correctly for users with CRUD permissions"""
        sbom = SBOM.objects.create(
            name='Test SBOM Actions',
            component=self.component,
            format='spdx',
            format_version='2.3'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check download link
        expected_download_url = f'/api/v1/sboms/{sbom.id}/download'
        self.assertContains(response, expected_download_url)

        # Check browse link
        expected_browse_url = f'/sbom/{sbom.id}/'
        self.assertContains(response, expected_browse_url)

        # Check vulnerabilities link
        expected_vuln_url = f'/sbom/{sbom.id}/vulnerabilities/'
        self.assertContains(response, expected_vuln_url)

        # Check delete button (should be present for owner)
        self.assertContains(response, 'Delete SBOM')
        self.assertContains(response, 'delete-sbom-btn')

    def test_sbom_actions_without_permissions(self):
        """Test that SBOM actions hide delete button for users without CRUD permissions"""
        # Create guest user
        guest_user = User.objects.create_user(
            username='guestuser',
            email='guest@example.com',
            password='guestpass123'
        )

        Member.objects.create(
            user=guest_user,
            team=self.team,
            role='guest'
        )

        # Login as guest
        self.client.logout()
        self.client.login(username='guestuser', password='guestpass123')

        # Set session for guest
        session = self.client.session
        session['current_team'] = {
            'id': self.team.id,
            'key': self.team.key,
            'name': self.team.name,
            'role': 'guest'
        }
        session.save()

        sbom = SBOM.objects.create(
            name='Test SBOM Guest',
            component=self.component,
            format='spdx',
            format_version='2.3'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check download and browse links are still present
        self.assertContains(response, 'Download SBOM')
        self.assertContains(response, 'Browse SBOM')

        # Check delete button is NOT present for guest
        self.assertNotContains(response, 'delete-sbom-btn')

    def test_sbom_upload_card_with_permissions(self):
        """Test that SBOM upload card shows correctly for users with CRUD permissions"""
        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check upload area is present
        self.assertContains(response, 'upload-area')
        self.assertContains(response, 'sbomFileInput')
        self.assertContains(response, 'Drop your SBOM file here')
        self.assertContains(response, 'click to browse')

        # Check file type hints
        self.assertContains(response, 'CycloneDX (.json, .cdx)')
        self.assertContains(response, 'SPDX (.json, .spdx)')
        self.assertContains(response, 'max 10MB')

    def test_sbom_upload_card_without_permissions(self):
        """Test that SBOM upload card shows permission message for users without CRUD permissions"""
        # Create guest user
        guest_user = User.objects.create_user(
            username='guestuser2',
            email='guest2@example.com',
            password='guestpass123'
        )

        Member.objects.create(
            user=guest_user,
            team=self.team,
            role='guest'
        )

        # Login as guest
        self.client.logout()
        self.client.login(username='guestuser2', password='guestpass123')

        # Set session for guest
        session = self.client.session
        session['current_team'] = {
            'id': self.team.id,
            'key': self.team.key,
            'name': self.team.name,
            'role': 'guest'
        }
        session.save()

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check permission message is shown
        self.assertContains(response, "You don't have permission to upload SBOMs")

        # Check upload area is NOT present
        self.assertNotContains(response, 'sbomFileInput')
        self.assertNotContains(response, 'Drop your SBOM file here')

    def test_component_without_sbom(self):
        """Test component detailed page for component without any SBOMs"""
        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check upload section is still present
        self.assertContains(response, 'Upload SBOM File')

        # Check that metadata card shows loading/empty state appropriately
        self.assertContains(response, 'SBOM Metadata')

        # Check that actions card shows no SBOM message
        self.assertContains(response, 'No SBOM available for this component')

    def test_ntia_compliance_status_display(self):
        """Test that NTIA compliance status displays correctly"""
        # Test compliant status
        compliant_sbom = SBOM.objects.create(
            name='Compliant SBOM',
            component=self.component,
            format='spdx',
            ntia_compliance_status='compliant'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'badge bg-success-subtle text-success')
        self.assertContains(response, 'fa-check-circle')
        self.assertContains(response, 'Compliant')

        # Test non-compliant status
        compliant_sbom.ntia_compliance_status = 'non_compliant'
        compliant_sbom.save()

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'badge bg-danger-subtle text-danger')
        self.assertContains(response, 'fa-times-circle')
        self.assertContains(response, 'Non-Compliant')

        # Test unknown status
        compliant_sbom.ntia_compliance_status = 'unknown'
        compliant_sbom.save()

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'badge bg-secondary-subtle text-secondary')
        self.assertContains(response, 'fa-question-circle')
        self.assertContains(response, 'Unknown')

    def test_document_component_detailed_page(self):
        """Test that document component detailed page still works (not yet migrated)"""
        doc_component = Component.objects.create(
            name='Test Document',
            component_type='document',
            team=self.team
        )

        response = self.client.get(f'/component/{doc_component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Should still render the page (even if using Vue components for now)
        self.assertContains(response, 'Test Document')

    def test_collapsible_functionality_markup(self):
        """Test that collapsible functionality markup is present"""
        sbom = SBOM.objects.create(
            name='Test SBOM Collapsible',
            component=self.component,
            format='spdx'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check for collapsible toggle buttons
        self.assertContains(response, 'data-bs-toggle="collapse"')
        self.assertContains(response, 'fa-chevron-up')
        self.assertContains(response, 'fa-chevron-down')

        # Check for collapsible content areas
        self.assertContains(response, 'collapse show')  # Metadata should be expanded by default
        self.assertContains(response, 'collapse')      # Upload should be collapsed by default

    def test_responsive_layout_classes(self):
        """Test that responsive layout classes are present"""
        sbom = SBOM.objects.create(
            name='Test SBOM Responsive',
            component=self.component,
            format='spdx'
        )

        response = self.client.get(f'/component/{self.component.id}/detailed/')
        self.assertEqual(response.status_code, 200)

        # Check for responsive grid classes
        self.assertContains(response, 'col-12 col-lg-6')  # Metadata and actions cards
        self.assertContains(response, 'row mb-4')         # Upload section
        self.assertContains(response, 'row')              # Details section
