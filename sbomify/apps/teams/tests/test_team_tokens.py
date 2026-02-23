"""Tests for team tokens view."""

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team


@pytest.mark.django_db
class TestTeamTokensView:
    """Test cases for TeamTokensView."""

    def test_get_requires_authentication(self, client: Client):
        """Test that GET requires authentication."""
        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": "test"}))
        assert response.status_code == 302

    def test_get_requires_team_membership(self, client: Client, sample_user: AbstractBaseUser):
        """Test that GET requires team membership."""
        client.force_login(sample_user)
        team = Team.objects.create(name="Test Team")
        # Ensure team has a key
        if not team.key:
            team.key = number_to_random_token(team.pk)
            team.save()

        # Ensure no current_team in session that would allow access
        session = client.session
        if "current_team" in session:
            del session["current_team"]
        session.save()

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code in (403, 404)

    def test_get_renders_template(self, client: Client, sample_team_with_owner_member):
        """Test that GET renders the template correctly."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200
        assert b"Generate New Token" in response.content
        assert b"Your Tokens" in response.content

    def test_get_shows_existing_tokens(self, client: Client, sample_team_with_owner_member):
        """Test that GET shows existing access tokens scoped to this team."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        AccessToken.objects.create(
            user=user,
            description="Scoped Token",
            encoded_token="test_token_string",
            team=team,
        )

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200
        assert b"Scoped Token" in response.content

    def test_post_creates_token(self, client: Client, sample_team_with_owner_member):
        """Test that POST creates a new access token scoped to the team."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        initial_count = AccessToken.objects.filter(user=user).count()

        response = client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": "New Test Token"},
        )

        assert response.status_code == 200
        assert AccessToken.objects.filter(user=user).count() == initial_count + 1
        msgs = list(get_messages(response.wsgi_request))
        assert any(m.message == "New access token created" for m in msgs)

        # Verify token is scoped to the team
        new_token = AccessToken.objects.filter(user=user, description="New Test Token").first()
        assert new_token is not None
        assert new_token.team_id == team.id

    def test_post_invalid_form_returns_error(self, client: Client, sample_team_with_owner_member):
        """Test that POST with invalid form returns error."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        initial_count = AccessToken.objects.filter(user=user).count()

        response = client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": ""},
        )

        assert response.status_code == 200
        assert AccessToken.objects.filter(user=user).count() == initial_count

    def test_post_shows_new_token(self, client: Client, sample_team_with_owner_member):
        """Test that POST response includes the new token."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.post(
            reverse("teams:team_tokens", kwargs={"team_key": team.key}),
            {"description": "New Token"},
        )

        assert response.status_code == 200
        token = AccessToken.objects.filter(user=user, description="New Token").first()
        assert token is not None
        assert token.encoded_token in response.content.decode()

    def test_token_listing_filtered_by_team(
        self, client: Client, sample_team_with_owner_member
    ):
        """Create tokens for 2 teams, verify GET only shows current team's tokens."""
        team_a = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user

        # Create a second team
        team_b = Team.objects.create(name="Team B")
        team_b.key = number_to_random_token(team_b.pk)
        team_b.save()
        Member.objects.create(user=user, team=team_b, role="owner")

        # Create tokens for each team
        AccessToken.objects.create(user=user, description="Token A", encoded_token="token_a", team=team_a)
        AccessToken.objects.create(user=user, description="Token B", encoded_token="token_b", team=team_b)

        setup_authenticated_client_session(client, team_a, user)
        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team_a.key}))
        content = response.content.decode()

        assert "Token A" in content
        # Token B should not appear in the scoped tokens list
        # (it may appear in unscoped section only if team is null, but here it's scoped to team_b)
        assert "Token B" not in content

    def test_unscoped_tokens_shown_with_warning(self, client: Client, sample_team_with_owner_member):
        """Create unscoped token, verify deprecation warning in response."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        # Create an unscoped token
        AccessToken.objects.create(user=user, description="Legacy Token", encoded_token="legacy_token", team=None)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        content = response.content.decode()

        assert response.status_code == 200
        assert "Legacy Token" in content
        assert "Unscoped" in content
        assert "Unscoped tokens detected" in content

    def test_member_role_can_access(self, client: Client, sample_team_with_owner_member):
        """Test that members can access tokens view."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        member_user = User.objects.create_user(username="member", email="member@example.com", password="test")
        Member.objects.create(team=team, user=member_user, role="member")

        setup_authenticated_client_session(client, team, member_user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200

    def test_admin_role_can_access(self, client: Client, sample_team_with_owner_member):
        """Test that admins can access tokens view."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        admin_user = User.objects.create_user(username="admin", email="admin@example.com", password="test")
        Member.objects.create(team=team, user=admin_user, role="admin")

        setup_authenticated_client_session(client, team, admin_user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 200

    def test_guest_role_cannot_access(self, client: Client, sample_team_with_owner_member):
        """Test that guests cannot access tokens view."""
        from django.contrib.auth import get_user_model

        team = sample_team_with_owner_member.team

        User = get_user_model()
        guest_user = User.objects.create_user(username="guest", email="guest@example.com", password="test")
        Member.objects.create(team=team, user=guest_user, role="guest")

        setup_authenticated_client_session(client, team, guest_user)

        response = client.get(reverse("teams:team_tokens", kwargs={"team_key": team.key}))
        assert response.status_code == 403
