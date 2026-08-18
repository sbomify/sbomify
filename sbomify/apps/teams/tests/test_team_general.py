"""Tests for team general settings view."""

import pytest
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
        if hasattr(response, "url") and response.url:
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

    def test_update_workspace_name_allows_admin(
        self, client: Client, sample_team_with_owner_member
    ):
        """Renaming the workspace is ADMINISTER, so admins may do it.

        Contrast with test_delete_workspace_requires_owner: deleting the
        workspace stays OWNER_ONLY.
        """
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="test"
        )
        Member.objects.create(team=team, user=admin_user, role="admin")

        setup_authenticated_client_session(client, team, admin_user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": "Admin Renamed This"},
        )

        assert response.status_code == 200
        team.refresh_from_db()
        assert team.name == "Admin Renamed This"


    def test_setting_the_freshness_window(
        self, client: Client, sample_team_with_owner_member
    ):
        """The only way to turn the freshness feature on."""
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": team.name, "sbom_freshness_days": "90"},
        )

        assert response.status_code == 200
        team.refresh_from_db()
        assert team.sbom_freshness_days == 90

    def test_clearing_the_freshness_window_removes_the_policy(
        self, client: Client, sample_team_with_owner_member
    ):
        """An emptied field has to unset the window rather than leave the old
        one standing, otherwise a policy can be set but never withdrawn."""
        team = sample_team_with_owner_member.team
        team.sbom_freshness_days = 90
        team.save(update_fields=["sbom_freshness_days"])
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": team.name, "sbom_freshness_days": ""},
        )

        assert response.status_code == 200
        team.refresh_from_db()
        assert team.sbom_freshness_days is None

    def test_a_zero_day_window_is_stored_not_treated_as_unset(
        self, client: Client, sample_team_with_owner_member
    ):
        """0 means every SBOM is stale immediately, which is a real policy and
        must not collapse into "no policy"."""
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": team.name, "sbom_freshness_days": "0"},
        )

        assert response.status_code == 200
        team.refresh_from_db()
        assert team.sbom_freshness_days == 0

    def test_a_negative_window_is_rejected(
        self, client: Client, sample_team_with_owner_member
    ):
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        client.post(
            reverse("teams:team_general", kwargs={"team_key": team.key}),
            {"name": team.name, "sbom_freshness_days": "-5"},
        )

        team.refresh_from_db()
        assert team.sbom_freshness_days is None

    def test_the_window_round_trips_to_the_form(
        self, client: Client, sample_team_with_owner_member
    ):
        team = sample_team_with_owner_member.team
        team.sbom_freshness_days = 45
        team.save(update_fields=["sbom_freshness_days"])
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.get(reverse("teams:team_general", kwargs={"team_key": team.key}))

        assert response.status_code == 200
        assert 'data-freshness-days="45"' in response.content.decode()
