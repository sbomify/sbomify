"""
Integration tests for workspace page rendering.

Tests the complete refactoring from Vue components to Django templates,
ensuring all workspace-related pages render correctly.
"""

import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from teams.models import Team, Member
from core.utils import number_to_random_token, token_to_number

User = get_user_model()


class WorkspaceRenderingIntegrationTest(TestCase):
    """Test that workspace pages render correctly after Vue-to-Django refactoring."""

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

        # Create test teams
        self.team1 = Team.objects.create(name="Test Team 1")
        self.team1.key = number_to_random_token(self.team1.pk)
        self.team1.save()

        self.team2 = Team.objects.create(name="Test Team 2")
        self.team2.key = number_to_random_token(self.team2.pk)
        self.team2.save()

        # Create memberships
        self.owner_membership = Member.objects.create(
            user=self.owner_user,
            team=self.team1,
            role="owner",
            is_default_team=True
        )

        self.admin_membership = Member.objects.create(
            user=self.admin_user,
            team=self.team1,
            role="admin",
            is_default_team=False
        )

        self.member_membership = Member.objects.create(
            user=self.member_user,
            team=self.team1,
            role="member",
            is_default_team=True
        )

        # Additional membership for testing multiple teams
        Member.objects.create(
            user=self.owner_user,
            team=self.team2,
            role="member",
            is_default_team=False
        )

    def test_workspace_dashboard_renders_for_authenticated_user(self):
        """Test that workspace dashboard renders correctly for authenticated users."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspaces")
        self.assertContains(response, "Manage your teams and collaborative workspaces")

        # Should contain team names
        self.assertContains(response, "Test Team 1")
        self.assertContains(response, "Test Team 2")

        # Should contain the teams table component
        self.assertContains(response, "teams-table-wrapper")

        # Should contain role badges
        self.assertContains(response, "Owner")
        self.assertContains(response, "Member")

        # Should contain add workspace modal
        self.assertContains(response, "Add Workspace")

    def test_workspace_dashboard_redirects_unauthenticated_user(self):
        """Test that unauthenticated users are redirected to login."""
        response = self.client.get(reverse('teams:teams_dashboard'))

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_workspace_dashboard_shows_auto_created_workspace_for_new_user(self):
        """Test that new users automatically get a default workspace."""
        user_new = User.objects.create_user(
            username="newuser@example.com",
            email="newuser@example.com"
        )

        self.client.force_login(user_new)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)
        # Should show the auto-created workspace (HTML entities may be encoded)
        self.assertContains(response, "newuser@example.com")
        self.assertContains(response, "Workspace")
        self.assertContains(response, "Owner")
        self.assertContains(response, "Default")

    def test_workspace_dashboard_displays_team_statistics(self):
        """Test that team statistics are displayed correctly."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Should show member counts
        self.assertContains(response, "3")  # Team 1 has 3 members
        self.assertContains(response, "Member")

        # Should show new statistics labels
        self.assertContains(response, "Product")
        self.assertContains(response, "Project")
        self.assertContains(response, "Component")

    def test_workspace_dashboard_shows_default_team_badge(self):
        """Test that default team is marked with a badge."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Default")
        self.assertContains(response, "fa-star")

    def test_workspace_dashboard_contains_settings_links(self):
        """Test that settings links are present for all teams."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Should contain links to team settings
        team1_settings_url = reverse('teams:team_settings', kwargs={'team_key': self.team1.key})
        team2_settings_url = reverse('teams:team_settings', kwargs={'team_key': self.team2.key})

        self.assertContains(response, team1_settings_url)
        self.assertContains(response, team2_settings_url)

        # Should contain settings icons
        self.assertContains(response, "fa-cog")

    def test_workspace_dashboard_shows_set_default_button_for_non_default_teams(self):
        """Test that non-default teams show set default button."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Should contain set default form for team2 (not default)
        set_default_url = reverse('teams:set_default_team', kwargs={'membership_id': 4})  # team2 membership
        self.assertContains(response, set_default_url)

    def test_workspace_add_form_creates_new_team(self):
        """Test that adding a new workspace works correctly."""
        self.client.force_login(self.owner_user)

        response = self.client.post(reverse('teams:teams_dashboard'), {
            'name': 'New Test Team'
        })

        # Should redirect back to dashboard
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('teams:teams_dashboard'))

        # Team should be created
        new_team = Team.objects.get(name='New Test Team')
        self.assertIsNotNone(new_team.key)

        # Membership should be created
        membership = Member.objects.get(user=self.owner_user, team=new_team)
        self.assertEqual(membership.role, 'owner')

    def test_workspace_dashboard_api_data_serialization(self):
        """Test that API data is properly serialized for templates."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Should not contain raw QuerySet or model objects
        self.assertNotContains(response, "<QuerySet")
        self.assertNotContains(response, "teams.models.Team")
        self.assertNotContains(response, "teams.models.Member")

        # Should contain properly serialized data
        context_teams_data = response.context['teams_data']
        self.assertIsInstance(context_teams_data, list)

        if context_teams_data:
            team_data = context_teams_data[0]
            self.assertIsInstance(team_data, dict)
            self.assertIn('key', team_data)
            self.assertIn('name', team_data)
            self.assertIn('role', team_data)
            self.assertIn('member_count', team_data)
            self.assertIn('invitation_count', team_data)
            self.assertIn('is_default_team', team_data)
            self.assertIn('membership_id', team_data)

    def test_workspace_dashboard_responsive_design_elements(self):
        """Test that responsive design elements are present."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Should contain Bootstrap responsive classes
        self.assertContains(response, "col-md-6")
        self.assertContains(response, "col-lg-4")
        self.assertContains(response, "d-flex")

        # Should contain responsive utilities
        self.assertContains(response, "mb-4")
        self.assertContains(response, "h-100")

    def test_workspace_dashboard_accessibility_features(self):
        """Test that accessibility features are present."""
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

        # Should contain proper ARIA labels
        self.assertContains(response, 'aria-label')
        self.assertContains(response, 'aria-hidden')

        # Should contain semantic HTML
        self.assertContains(response, '<h1')
        self.assertContains(response, '<h5')

        # Should contain proper form labels
        self.assertContains(response, 'form-label')

    def test_workspace_dashboard_performance_optimizations(self):
        """Test that performance optimizations are in place."""
        self.client.force_login(self.owner_user)

        # Should use the optimized API function that uses select_related and prefetch_related
        # Realistic query count: session, user, count query for pagination, membership+team (select_related),
        # member_set, invitation_set, product/project/component counts (3 per team), billing
        with self.assertNumQueries(16):  # Reasonable query count for the functionality with pagination and statistics
            response = self.client.get(reverse('teams:teams_dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_workspace_dashboard_pagination_with_many_teams(self):
        """Test that pagination works correctly with many teams (100+ scenario)."""
        # Create 25 additional teams for a total of 27 teams (2 existing + 25 new)
        teams_to_create = 25
        for i in range(teams_to_create):
            team = Team.objects.create(
                name=f"Test Team {i + 3}",  # Start from 3 since we have Test Team 1 and 2
                key=number_to_random_token(i + 1000)  # Unique keys
            )
            Member.objects.create(
                user=self.owner_user,
                team=team,
                role="owner"
            )

        self.client.force_login(self.owner_user)

        # Test default pagination (15 per page)
        response = self.client.get(reverse('teams:teams_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Showing 1-15")  # Should show first 15
        self.assertContains(response, "of 27")  # Should show total count
        self.assertContains(response, "Search workspaces")  # Should have search functionality
        self.assertContains(response, "Show:")  # Should have page size selector

        # Test page 2
        response = self.client.get(reverse('teams:teams_dashboard') + '?page=2')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Showing 16-27")  # Should show remaining teams
        self.assertContains(response, "of 27")  # Should show total count

        # Test search functionality
        response = self.client.get(reverse('teams:teams_dashboard') + '?search=Test Team 1')
        self.assertEqual(response.status_code, 200)
        # Should find 11 teams with "Test Team 1" in name (Test Team 1, Test Team 10-19)
        self.assertContains(response, "Showing 1-11")  # Should show all found teams
        self.assertContains(response, "of 11")  # Should show search result count

        # Test custom page size
        response = self.client.get(reverse('teams:teams_dashboard') + '?page_size=25')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Showing 1-25")  # Should show 25 per page
        self.assertContains(response, "of 27")  # Should show total count

    def test_workspace_dashboard_shows_statistics(self):
        """Test that workspace cards show product/project/component statistics."""
        # Create some test data for statistics
        from sboms.models import Product, Project, Component

        # Create test products, projects, and components for the test team
        Product.objects.create(name="Test Product 1", team=self.team1)
        Product.objects.create(name="Test Product 2", team=self.team1)

        Project.objects.create(name="Test Project 1", team=self.team1)
        Project.objects.create(name="Test Project 2", team=self.team1)
        Project.objects.create(name="Test Project 3", team=self.team1)

        Component.objects.create(name="Test Component 1", team=self.team1)

        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('teams:teams_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check that the statistics are displayed in the response
        self.assertContains(response, "Product")  # Product label
        self.assertContains(response, "Project")  # Project label
        self.assertContains(response, "Component")  # Component label

        # Check for the actual counts (these will appear as numbers in stat-number divs)
        response_content = response.content.decode()

        # Look for the statistics in the HTML structure
        self.assertIn("stat-number", response_content)  # Statistics section exists

        # Check that the new statistics are included in the context data
        context_teams_data = response.context['teams_data']
        self.assertIsInstance(context_teams_data, list)

        if context_teams_data:
            team_data = context_teams_data[0]
            self.assertIn('product_count', team_data)
            self.assertIn('project_count', team_data)
            self.assertIn('component_count', team_data)
            # Verify the counts are integers
            self.assertIsInstance(team_data['product_count'], int)
            self.assertIsInstance(team_data['project_count'], int)
            self.assertIsInstance(team_data['component_count'], int)
