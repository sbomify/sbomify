"""
Integration tests for workspace detail pages navigation and rendering.

Tests that all workspace detail pages render correctly with proper navigation
and that all navbar items appear on all pages.
"""

import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from teams.models import Team, Member
from core.utils import number_to_random_token

User = get_user_model()


class WorkspaceDetailPagesTest(TestCase):
    """Test workspace detail pages rendering and navigation."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create test users
        self.owner_user = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            first_name="Owner",
            last_name="User"
        )

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

        # Create test workspace
        self.workspace = Team.objects.create(name="Test Workspace", billing_plan="community")
        self.workspace.key = number_to_random_token(self.workspace.pk)
        self.workspace.save()

        # Create memberships with different roles
        self.owner_membership = Member.objects.create(
            user=self.owner_user,
            team=self.workspace,
            role="owner",
            is_default_team=True
        )

        self.admin_membership = Member.objects.create(
            user=self.admin_user,
            team=self.workspace,
            role="admin",
            is_default_team=False
        )

        self.member_membership = Member.objects.create(
            user=self.member_user,
            team=self.workspace,
            role="member",
            is_default_team=False
        )

    def test_workspace_members_page_renders(self):
        """Test that workspace members page renders correctly."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_members', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspace Members")
        self.assertContains(response, self.workspace.name)
        self.assertContains(response, "Owner User")  # Owner should be visible
        self.assertContains(response, "Admin User")  # Admin should be visible
        self.assertContains(response, "Member User")  # Member should be visible

    def test_workspace_branding_page_renders(self):
        """Test that workspace branding page renders correctly."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_branding', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspace Branding")
        self.assertContains(response, self.workspace.name)

    def test_workspace_integrations_page_renders_for_owner(self):
        """Test that workspace integrations page renders correctly for owner."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspace Integrations")
        self.assertContains(response, self.workspace.name)

    def test_workspace_billing_page_renders_for_owner(self):
        """Test that workspace billing page renders correctly for owner."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_billing', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspace Billing")
        self.assertContains(response, self.workspace.name)

    def test_workspace_danger_zone_page_renders_for_owner(self):
        """Test that workspace danger zone page renders correctly for owner."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_danger', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Danger Zone")
        self.assertContains(response, self.workspace.name)

    def test_workspace_settings_redirect(self):
        """Test that workspace settings redirects to members page."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_settings', kwargs={'team_key': self.workspace.key}))

        # Should redirect to members page
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('teams:team_members', kwargs={'team_key': self.workspace.key})
        self.assertRedirects(response, expected_url)

    def test_all_pages_show_navigation_tabs_for_owner(self):
        """Test that all workspace pages show the correct navigation tabs for owner."""
        self.client.force_login(self.owner_user)

        pages_to_test = [
            ('teams:team_members', 'Members'),
            ('teams:team_branding', 'Branding'),
            ('teams:team_integrations', 'Integrations'),
            ('teams:team_billing', 'Billing'),
            ('teams:team_danger', 'Danger Zone'),
        ]

        for url_name, expected_tab in pages_to_test:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, kwargs={'team_key': self.workspace.key}))

                self.assertEqual(response.status_code, 200)

                # Check that all expected navigation tabs are present
                self.assertContains(response, 'href="{}"'.format(
                    reverse('teams:team_members', kwargs={'team_key': self.workspace.key})
                ))
                self.assertContains(response, 'href="{}"'.format(
                    reverse('teams:team_branding', kwargs={'team_key': self.workspace.key})
                ))
                self.assertContains(response, 'href="{}"'.format(
                    reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key})
                ))
                self.assertContains(response, 'href="{}"'.format(
                    reverse('teams:team_billing', kwargs={'team_key': self.workspace.key})
                ))
                self.assertContains(response, 'href="{}"'.format(
                    reverse('teams:team_danger', kwargs={'team_key': self.workspace.key})
                ))

                # Check navigation items are visible
                self.assertContains(response, "Members")
                self.assertContains(response, "Branding")
                self.assertContains(response, "Integrations")
                self.assertContains(response, "Billing")
                self.assertContains(response, "Danger Zone")

    def test_admin_can_access_admin_pages(self):
        """Test that admins can access admin-accessible pages."""
        self.client.force_login(self.admin_user)

        # Admins can access members and branding pages
        accessible_pages = [
            ('teams:team_members', 'Members'),
            ('teams:team_branding', 'Branding'),
        ]

        for url_name, expected_tab in accessible_pages:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, kwargs={'team_key': self.workspace.key}))

                self.assertEqual(response.status_code, 200)

                # Check basic navigation is present (limited to what admins see)
                self.assertContains(response, "Members")
                self.assertContains(response, "Branding")

                # Check owner-only tabs are NOT present for admins
                self.assertNotContains(response, "Integrations")
                self.assertNotContains(response, "Billing")
                self.assertNotContains(response, "Danger Zone")

    def test_member_cannot_access_restricted_pages(self):
        """Test that regular members cannot access restricted pages."""
        self.client.force_login(self.member_user)

        # Members cannot access these pages (they require owner or admin role)
        restricted_pages = [
            'teams:team_members',  # Requires owner/admin
            'teams:team_branding',  # Requires owner/admin
            'teams:team_integrations',  # Requires owner
            'teams:team_billing',  # Requires owner
            'teams:team_danger',  # Requires owner
        ]

        for url_name in restricted_pages:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, kwargs={'team_key': self.workspace.key}))

                # Should be forbidden or redirect
                self.assertIn(response.status_code, [403, 302])

    def test_breadcrumb_navigation_present_on_all_pages(self):
        """Test that breadcrumb navigation is present on all workspace pages."""
        self.client.force_login(self.owner_user)

        pages_to_test = [
            'teams:team_members',
            'teams:team_branding',
            'teams:team_integrations',
            'teams:team_billing',
            'teams:team_danger',
        ]

        for url_name in pages_to_test:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, kwargs={'team_key': self.workspace.key}))

                self.assertEqual(response.status_code, 200)

                # Check breadcrumb elements are present
                self.assertContains(response, 'aria-label="breadcrumb"')
                self.assertContains(response, "Workspaces")  # First breadcrumb item
                self.assertContains(response, self.workspace.name)  # Workspace name in breadcrumb

    def test_page_titles_are_correct(self):
        """Test that all workspace pages have correct titles."""
        self.client.force_login(self.owner_user)

        expected_titles = {
            'teams:team_members': 'Workspace Members',
            'teams:team_branding': 'Workspace Branding',
            'teams:team_integrations': 'Workspace Integrations',
            'teams:team_billing': 'Workspace Billing',
            'teams:team_danger': 'Danger Zone',
        }

        for url_name, expected_title in expected_titles.items():
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, kwargs={'team_key': self.workspace.key}))

                self.assertEqual(response.status_code, 200)
                # Check for title components (allowing for whitespace variations)
                self.assertContains(response, f"{expected_title}")
                self.assertContains(response, f"{self.workspace.name}")
                self.assertContains(response, "sbomify")

    def test_workspace_tables_use_standard_styling(self):
        """Test that workspace tables use the standard dashboard table styling."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:team_members', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Check for standard table classes
        self.assertContains(response, "dashboard-table")
        self.assertContains(response, "table-responsive")
        self.assertContains(response, "card border-light shadow-brand")

        # Check that the table structure follows standards
        self.assertContains(response, "card-header")
        self.assertContains(response, "card-body")

    def test_dependency_track_not_selectable_for_community_plan(self):
        """Test that Dependency Track cannot be selected on Community plan."""
        # Create a community plan workspace
        self.workspace.billing_plan = 'community'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Check that Dependency Track card is present but disabled
        self.assertContains(response, 'data-provider="dependency_track"', count=0)  # Should not have data-provider attribute
        self.assertContains(response, 'Dependency Track')
        self.assertContains(response, 'Business+ Required')
        self.assertContains(response, 'fa-lock')  # Lock icon should be present
        self.assertContains(response, 'disabled')  # Card should have disabled class

        # Check that OSV Scanner is available
        self.assertContains(response, 'data-provider="osv"')
        self.assertContains(response, 'cursor-pointer')

    def test_dependency_track_selectable_for_business_plan(self):
        """Test that Dependency Track can be selected on Business+ plans."""
        # Create a business plan workspace
        self.workspace.billing_plan = 'business'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Check that Dependency Track card is selectable
        self.assertContains(response, 'data-provider="dependency_track"')
        self.assertContains(response, 'cursor-pointer')
        self.assertContains(response, 'Available', count=2)  # Both OSV and DT should show "Available"

        # Should not have lock icon for Dependency Track on business plan
        content = response.content.decode('utf-8')
        # Find the Dependency Track section
        dt_start = content.find('Dependency Track')
        if dt_start != -1:
            # Look for the card containing Dependency Track (search backwards and forwards)
            card_start = content.rfind('<div class="card', 0, dt_start)
            card_end = content.find('</div>', dt_start)
            if card_start != -1 and card_end != -1:
                # Find the end of this card
                card_end = content.find('</div>', card_end + 20)  # Go to next closing div
                dt_card_content = content[card_start:card_end]
                self.assertNotIn('fa-lock', dt_card_content)

    def test_dependency_track_selectable_for_enterprise_plan(self):
        """Test that Dependency Track and custom servers are available on Enterprise plan."""
        # Create an enterprise plan workspace
        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Check that Dependency Track card is selectable
        self.assertContains(response, 'data-provider="dependency_track"')
        self.assertContains(response, 'cursor-pointer')

        # Check for Enterprise badge
        self.assertContains(response, 'Enterprise')

        # Check that server selection section exists (even if hidden initially)
        self.assertContains(response, 'server-selection-section')
        self.assertContains(response, 'Shared Server Pool')

    def test_integration_typescript_functionality(self):
        """Test that the integrations page includes the necessary TypeScript."""
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Check that TypeScript bundle is compiled and included
        self.assertContains(response, 'teams.js')

        # Check that billing plan data attribute is present for TypeScript
        self.assertContains(response, 'data-billing-plan=')

        # Check that necessary data attributes are present for TypeScript
        self.assertContains(response, 'data-provider="osv"')

        # Check that hidden form inputs exist for TypeScript to update
        self.assertContains(response, 'id="selectedProvider"')
        self.assertContains(response, 'name="vulnerability_provider"')

    def test_enterprise_server_selection_functionality(self):
        """Test that Enterprise users can see and select custom servers."""
        # Set up enterprise workspace
        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Check that billing plan is correctly set in template
        self.assertContains(response, 'data-billing-plan="enterprise"')

        # Check that both providers are available and selectable
        self.assertContains(response, 'data-provider="osv"')
        self.assertContains(response, 'data-provider="dependency_track"')

        # Check that server selection section exists (but may be hidden initially)
        self.assertContains(response, 'server-selection-section')
        self.assertContains(response, 'Shared Server Pool')
        self.assertContains(response, 'data-server=""')  # Shared pool option

        # Check that server selection input exists
        self.assertContains(response, 'id="selectedServer"')
        self.assertContains(response, 'name="custom_dt_server_id"')

        # Check that TypeScript bundle is loaded for interactive functionality
        self.assertContains(response, 'teams.js')

    def test_vulnerability_settings_save_and_persist(self):
        """Test that vulnerability settings are properly saved and persist on reload."""
        self.workspace.billing_plan = 'business'  # Can use Dependency Track
        self.workspace.save()

        self.client.force_login(self.owner_user)

        # First, check that default is OSV
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="osv"')  # Default in hidden input

        # Submit form to change to Dependency Track
        post_data = {
            'vulnerability_provider': 'dependency_track',
            'custom_dt_server_id': ''
        }
        response = self.client.post(
            reverse('teams:update_vulnerability_settings', kwargs={'team_key': self.workspace.key}),
            data=post_data,
            follow=True
        )

        # Should redirect back to integrations page with success message
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'successfully')

        # Now reload the page and verify Dependency Track is selected
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))
        self.assertEqual(response.status_code, 200)

        # Should show dependency_track as the selected value
        self.assertContains(response, 'value="dependency_track"')

        # And the Dependency Track card should have the success styling
        self.assertContains(response, 'border-success bg-success-subtle')

    def test_vulnerability_settings_enterprise_server_selection(self):
        """Test that Enterprise users can select custom servers."""
        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        self.client.force_login(self.owner_user)

        # Submit form to select Dependency Track with shared server (empty server ID)
        post_data = {
            'vulnerability_provider': 'dependency_track',
            'custom_dt_server_id': ''  # Shared server pool
        }
        response = self.client.post(
            reverse('teams:update_vulnerability_settings', kwargs={'team_key': self.workspace.key}),
            data=post_data,
            follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'successfully')

        # Reload and verify both settings are preserved
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))
        self.assertEqual(response.status_code, 200)

        # Should show dependency_track selected
        self.assertContains(response, 'value="dependency_track"')
        # Should show empty server ID (shared pool)
        self.assertContains(response, 'value=""')  # selectedServer input

    def test_custom_dependency_track_servers_display(self):
        """Test that custom DT servers are displayed for Enterprise users."""
        from vulnerability_scanning.models import DependencyTrackServer

        # Create a test DT server
        test_server = DependencyTrackServer.objects.create(
            name="Test Custom Server",
            url="https://dt-test.example.com",
            api_key="test-key",
            priority=1,
            max_concurrent_scans=10,
            is_active=True,
            health_status="healthy"
        )

        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Should show the custom server option
        self.assertContains(response, 'Test Custom Server')
        self.assertContains(response, f'data-server="{test_server.id}"')
        self.assertContains(response, 'Dedicated Dependency Track server')

        # Should also show the shared server pool option
        self.assertContains(response, 'Shared Server Pool')
        self.assertContains(response, 'data-server=""')

        # Clean up
        test_server.delete()

    def test_add_dt_server_page_enterprise_only(self):
        """Test that add DT server page is only accessible for Enterprise users."""
        # Community user should be redirected
        self.workspace.billing_plan = 'community'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:add_dt_server', kwargs={'team_key': self.workspace.key}))

        # Should redirect to integrations page with error message
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        # Enterprise user should see the page
        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        response = self.client.get(reverse('teams:add_dt_server', kwargs={'team_key': self.workspace.key}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Dependency Track Server')
        self.assertContains(response, 'Server Configuration')

    def test_dt_server_management_in_integrations_page(self):
        """Test that DT server management section appears for Enterprise users."""
        from vulnerability_scanning.models import DependencyTrackServer

        # Create a test DT server
        test_server = DependencyTrackServer.objects.create(
            name="Test Custom Server",
            url="https://dt-test.example.com",
            api_key="test-key",
            priority=1,
            max_concurrent_scans=10,
            is_active=True,
            health_status="healthy"
        )

        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))

        self.assertEqual(response.status_code, 200)

        # Should show server management section
        self.assertContains(response, 'Server Management')
        self.assertContains(response, 'Add Server')
        self.assertContains(response, 'Test Custom Server')
        self.assertContains(response, 'https://dt-test.example.com')

        # Should show delete button with modal pattern
        self.assertContains(response, 'data-bs-toggle="modal"')
        self.assertContains(response, 'data-bs-target="#deleteDtServerModal"')
        self.assertContains(response, f'data-item-id="{test_server.id}"')
        self.assertContains(response, f'data-item-name="{test_server.name}"')

        # Should include the standard delete confirmation modal
        self.assertContains(response, 'id="deleteDtServerModal"')
        self.assertContains(response, "Delete Dependency Track Server")

        # Clean up
        test_server.delete()

    def test_custom_dependency_track_server_selection_and_save(self):
        """Test that Enterprise users can select and save custom DT servers."""
        from vulnerability_scanning.models import DependencyTrackServer, TeamVulnerabilitySettings

        # Create a test DT server
        test_server = DependencyTrackServer.objects.create(
            name="Test Custom Server",
            url="https://dt-test.example.com",
            api_key="test-key",
            priority=1,
            max_concurrent_scans=10,
            is_active=True,
            health_status="healthy"
        )

        self.workspace.billing_plan = 'enterprise'
        self.workspace.save()

        self.client.force_login(self.owner_user)

        # Submit form to select Dependency Track with custom server
        post_data = {
            'vulnerability_provider': 'dependency_track',
            'custom_dt_server_id': str(test_server.id)
        }
        response = self.client.post(
            reverse('teams:update_vulnerability_settings', kwargs={'team_key': self.workspace.key}),
            data=post_data,
            follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'successfully')

        # Verify the settings were saved to the database
        settings = TeamVulnerabilitySettings.objects.get(team=self.workspace)
        self.assertEqual(settings.vulnerability_provider, 'dependency_track')
        self.assertEqual(settings.custom_dt_server, test_server)

        # Reload the page and verify the custom server is selected
        response = self.client.get(reverse('teams:team_integrations', kwargs={'team_key': self.workspace.key}))
        self.assertEqual(response.status_code, 200)

        # Should show dependency_track selected
        self.assertContains(response, 'value="dependency_track"')
        # Should show the custom server ID selected
        self.assertContains(response, f'value="{test_server.id}"')

        # The custom server card should have success styling
        self.assertContains(response, 'Test Custom Server')
        # Should show server selection section since we're on enterprise with DT selected
        self.assertContains(response, 'server-selection-section')

        # Clean up
        test_server.delete()
