"""Tests for team naming logic."""

import pytest
from django.contrib.auth import get_user_model

from sbomify.apps.teams.models import get_team_name_for_user

User = get_user_model()


@pytest.mark.django_db
class TestGetTeamNameForUser:
    """Test suite for get_team_name_for_user function."""

    def test_team_name_with_first_name(self):
        """Test team name when user has first_name set."""
        user = User.objects.create(
            username="john.example.com", email="john@example.com", first_name="John", last_name="Doe"
        )

        team_name = get_team_name_for_user(user)

        assert team_name == "John's Workspace"

    def test_team_name_without_first_name_email_based_username(self):
        """Test team name extraction from email-based username (user.example.com)."""
        user = User.objects.create(username="jane.example.com", email="jane@example.com")

        team_name = get_team_name_for_user(user)

        # Should extract "jane" from "jane.example.com"
        assert team_name == "jane's Workspace"

    def test_team_name_without_first_name_email_username(self):
        """Test team name extraction from email username (user@example.com)."""
        user = User.objects.create(username="bob@example.com", email="bob@example.com")

        team_name = get_team_name_for_user(user)

        # Should extract "bob" from "bob@example.com"
        assert team_name == "bob's Workspace"

    def test_team_name_with_simple_username(self):
        """Test team name with simple username (no @ or .)."""
        user = User.objects.create(username="alice", email="alice@example.com")

        team_name = get_team_name_for_user(user)

        assert team_name == "alice's Workspace"

    def test_team_name_with_numbered_username(self):
        """Test team name with numbered username (e.g. user.example.com_1)."""
        user = User.objects.create(username="test.example.com_1", email="test@example.com")

        team_name = get_team_name_for_user(user)

        # Should extract "test" from "test.example.com_1"
        assert team_name == "test's Workspace"

    def test_team_name_without_username(self):
        """Test team name when user has no username."""

        class UserWithoutUsername:
            first_name = ""
            username = ""

        user = UserWithoutUsername()

        team_name = get_team_name_for_user(user)

        assert team_name == "My Workspace"

    def test_team_name_empty_first_name_and_username(self):
        """Test team name when both first_name and username are empty."""
        user = User.objects.create(username="", email="")

        team_name = get_team_name_for_user(user)

        assert team_name == "My Workspace"

    def test_team_name_preserves_old_behavior_for_sso_users(self):
        """Test that SSO users without first_name get clean team names."""
        # This mimics an SSO user who didn't provide first_name
        # Username would be generated as "user.example.com"
        user = User.objects.create(username="john.example.com", email="john@example.com", first_name="")

        team_name = get_team_name_for_user(user)

        # Should extract "john" not use full "john.example.com"
        assert team_name == "john's Workspace"
        assert team_name != "john.example.com's Workspace"
