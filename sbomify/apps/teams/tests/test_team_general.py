"""Tests for team general settings view."""

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member, Team


@pytest.mark.django_db
class TestTeamGeneralView:
    """Test cases for TeamGeneralView."""

    def test_set_default_workspace(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test setting a workspace as default."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        other_team = Team.objects.create(name="Other Team")
        Member.objects.create(team=other_team, user=user, role="owner", is_default_team=True)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"action": "set_default"},
        )

        assert response.status_code == 200
        membership = Member.objects.get(user=user, team=team)
        assert membership.is_default_team is True

        other_membership = Member.objects.get(user=user, team=other_team)
        assert other_membership.is_default_team is False

    def test_set_default_requires_owner(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that only owners can set default workspace."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team
        owner = sample_team_with_owner_member.user

        User = get_user_model()
        member_user = User.objects.create_user(
            username="member", email="member@example.com", password="test"
        )
        Member.objects.create(team=team, user=member_user, role="member")

        setup_authenticated_client_session(client, team, member_user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"action": "set_default"},
        )

        assert response.status_code == 403

    def test_delete_workspace(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test deleting a workspace."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        
        # Create other team as default first
        other_team = Team.objects.create(name="Other Team")
        from sbomify.apps.core.utils import number_to_random_token
        if not other_team.key:
            other_team.key = number_to_random_token(other_team.pk)
            other_team.save()
        Member.objects.create(team=other_team, user=user, role="owner", is_default_team=True)
        
        # Ensure the team to delete is NOT the default
        membership = Member.objects.get(user=user, team=team)
        membership.is_default_team = False
        membership.save()
        
        setup_authenticated_client_session(client, team, user)

        team_key = team.key
        team_id = team.id  # Store ID to check deletion
        
        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team_key}),
            {"action": "delete_workspace"},
            follow=False,  # Don't follow redirect to check status code
        )

        # Delete should redirect to dashboard (302)
        assert response.status_code == 302, f"Expected 302, got {response.status_code}"
        if hasattr(response, 'url') and response.url:
            assert response.url == reverse("core:dashboard")
        
        # Verify team is deleted by checking ID (key might be cached)
        assert not Team.objects.filter(id=team_id).exists(), "Team should have been deleted"
        assert not Team.objects.filter(key=team_key).exists(), "Team should have been deleted"

    def test_delete_default_workspace_fails(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that deleting default workspace fails."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        membership = Member.objects.get(user=user, team=team)
        membership.is_default_team = True
        membership.save()

        setup_authenticated_client_session(client, team, user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"action": "delete_workspace"},
        )

        assert response.status_code == 200
        assert Team.objects.filter(key=team.key).exists()

    def test_delete_workspace_requires_owner(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that only owners can delete workspace."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team
        owner = sample_team_with_owner_member.user

        User = get_user_model()
        admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="test"
        )
        Member.objects.create(team=team, user=admin_user, role="admin")

        setup_authenticated_client_session(client, team, admin_user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"action": "delete_workspace"},
        )

        assert response.status_code == 403
        assert Team.objects.filter(key=team.key).exists()

    def test_delete_workspace_switches_to_default(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that deleting workspace switches to default workspace."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        
        # Create default team first
        default_team = Team.objects.create(name="Default Team")
        from sbomify.apps.core.utils import number_to_random_token
        if not default_team.key:
            default_team.key = number_to_random_token(default_team.pk)
            default_team.save()
        
        # Ensure the team to delete is NOT the default
        membership = Member.objects.get(user=user, team=team)
        membership.is_default_team = False
        membership.save()
        
        # Create default team membership
        Member.objects.create(team=default_team, user=user, role="owner", is_default_team=True)

        setup_authenticated_client_session(client, team, user)

        default_team_key = default_team.key
        team_key_to_delete = team.key

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team_key_to_delete}),
            {"action": "delete_workspace"},
            follow=True,  # Follow redirect to verify session update
        )

        # Delete should redirect to dashboard
        assert response.status_code == 200  # After following redirect
        session = client.session
        # The session should be switched to the default team
        assert session["current_team"]["key"] == default_team_key, \
            f"Expected {default_team_key}, got {session['current_team']['key']}"

    def test_update_workspace_name(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test updating workspace name."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": "Updated Team Name"},
        )

        assert response.status_code == 200
        team.refresh_from_db()
        assert team.name == "Updated Team Name"

    def test_update_workspace_name_requires_owner(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that only owners can update workspace name."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team
        owner = sample_team_with_owner_member.user

        User = get_user_model()
        admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="test"
        )
        Member.objects.create(team=team, user=admin_user, role="admin")

        setup_authenticated_client_session(client, team, admin_user)

        original_name = team.name
        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": "Unauthorized Name Change"},
        )

        assert response.status_code == 403
        team.refresh_from_db()
        assert team.name == original_name

