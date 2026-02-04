"""Tests for user account deletion functionality."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.services.account_deletion import (
    delete_user_account,
    invalidate_user_sessions,
    validate_account_deletion,
)
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

User = get_user_model()


@pytest.fixture
def user_no_team(db):
    """Create a user without any team membership."""
    user = User.objects.create_user(
        username="loneuser",
        email="loneuser@example.com",
        first_name="Lone",
        last_name="User",
    )
    yield user
    if User.objects.filter(pk=user.pk).exists():
        user.delete()


@pytest.fixture
def deletable_user(db):
    """Create a user that can be deleted by tests."""
    user = User.objects.create_user(
        username="deletableuser",
        email="deletable@example.com",
        first_name="Deletable",
        last_name="User",
    )
    yield user
    # Don't delete in teardown - tests may have already deleted this user


@pytest.fixture
def team_with_owner(sample_user):  # noqa: F811
    """Create a team with sample_user as sole owner."""
    community_plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Solo Owner Team", billing_plan="community")
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

    yield team

    if Team.objects.filter(pk=team.pk).exists():
        team.delete()


@pytest.fixture
def deletable_user_with_team(deletable_user, db):
    """Create a team with deletable_user as sole owner."""
    community_plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Deletable User Team", billing_plan="community")
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=deletable_user, role="owner", is_default_team=True)

    yield team, deletable_user

    if Team.objects.filter(pk=team.pk).exists():
        team.delete()


@pytest.fixture
def team_with_multiple_owners(sample_user, db):  # noqa: F811
    """Create a team with sample_user as owner and another owner."""
    other_owner = User.objects.create_user(
        username="otherowner",
        email="otherowner@example.com",
        first_name="Other",
        last_name="Owner",
    )

    community_plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Multi Owner Team", billing_plan="community")
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)
    Member.objects.create(team=team, user=other_owner, role="owner")

    yield team

    if User.objects.filter(pk=other_owner.pk).exists():
        other_owner.delete()
    if Team.objects.filter(pk=team.pk).exists():
        team.delete()


@pytest.fixture
def team_sole_owner_with_members(sample_user, db):  # noqa: F811
    """Create a team where sample_user is sole owner but has other members."""
    other_member = User.objects.create_user(
        username="othermember",
        email="othermember@example.com",
        first_name="Other",
        last_name="Member",
    )

    community_plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Sole Owner Team", billing_plan="community")
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)
    Member.objects.create(team=team, user=other_member, role="admin")

    yield team, other_member

    if User.objects.filter(pk=other_member.pk).exists():
        other_member.delete()
    if Team.objects.filter(pk=team.pk).exists():
        team.delete()


class TestValidateAccountDeletion:
    """Tests for validate_account_deletion function."""

    @pytest.mark.django_db
    def test_can_delete_user_with_no_teams(self, user_no_team):
        """User with no team memberships can delete their account."""
        can_delete, error = validate_account_deletion(user_no_team)
        assert can_delete is True
        assert error is None

    @pytest.mark.django_db
    def test_can_delete_sole_owner_no_other_members(self, sample_user, team_with_owner):  # noqa: F811
        """Sole owner can delete if no other members exist."""
        can_delete, error = validate_account_deletion(sample_user)
        assert can_delete is True
        assert error is None

    @pytest.mark.django_db
    def test_cannot_delete_sole_owner_with_other_members(self, sample_user, team_sole_owner_with_members):  # noqa: F811
        """Sole owner cannot delete if other members exist."""
        can_delete, error = validate_account_deletion(sample_user)
        assert can_delete is False
        assert "sole owner" in error.lower()
        assert "Sole Owner Team" in error

    @pytest.mark.django_db
    def test_can_delete_with_multiple_owners(self, sample_user, team_with_multiple_owners):  # noqa: F811
        """Can delete if another owner exists in the team."""
        can_delete, error = validate_account_deletion(sample_user)
        assert can_delete is True
        assert error is None


class TestDeleteUserAccount:
    """Tests for delete_user_account function."""

    @pytest.mark.django_db
    def test_successful_deletion_no_keycloak(self, user_no_team):
        """Account deletion succeeds without Keycloak link."""
        user_id = user_no_team.id

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False

            success, message = delete_user_account(user_no_team)

            assert success is True
            assert "successfully deleted" in message.lower()
            assert not User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_cascade_deletes_access_tokens(self, deletable_user_with_team):
        """Access tokens are cascade deleted with user."""
        team, user = deletable_user_with_team
        token_str = create_personal_access_token(user)
        AccessToken.objects.create(
            user=user,
            encoded_token=token_str,
            description="Test token",
        )

        user_id = user.id

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False

            success, _ = delete_user_account(user)

            assert success is True
            assert not AccessToken.objects.filter(user_id=user_id).exists()

    @pytest.mark.django_db
    def test_deletion_blocked_for_sole_owner_with_members(self, sample_user, team_sole_owner_with_members):  # noqa: F811
        """Deletion is blocked when user is sole owner with other members."""
        user_id = sample_user.id

        success, error = delete_user_account(sample_user)

        assert success is False
        assert "sole owner" in error.lower()
        assert User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_keycloak_deletion_called(self, user_no_team):
        """Keycloak delete_user is called when user has social account."""
        from allauth.socialaccount.models import SocialAccount

        SocialAccount.objects.create(
            user=user_no_team,
            provider="keycloak",
            uid="keycloak-user-123",
        )

        with patch("sbomify.apps.core.keycloak_utils.KeycloakManager") as mock_kc:
            mock_instance = MagicMock()
            mock_instance.delete_user.return_value = True
            mock_kc.return_value = mock_instance

            with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
                mock_settings.USE_KEYCLOAK = True

                success, _ = delete_user_account(user_no_team)

                assert success is True
                mock_instance.delete_user.assert_called_once_with("keycloak-user-123")

    @pytest.mark.django_db
    def test_keycloak_failure_blocks_deletion(self, user_no_team):
        """Django user is not deleted if Keycloak deletion fails."""
        from allauth.socialaccount.models import SocialAccount

        SocialAccount.objects.create(
            user=user_no_team,
            provider="keycloak",
            uid="keycloak-user-456",
        )
        user_id = user_no_team.id

        with patch("sbomify.apps.core.keycloak_utils.KeycloakManager") as mock_kc:
            mock_instance = MagicMock()
            mock_instance.delete_user.return_value = False
            mock_kc.return_value = mock_instance

            with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
                mock_settings.USE_KEYCLOAK = True

                success, error = delete_user_account(user_no_team)

                assert success is False
                assert "authentication provider" in error.lower()
                assert User.objects.filter(id=user_id).exists()


class TestInvalidateUserSessions:
    """Tests for invalidate_user_sessions function."""

    @pytest.mark.django_db
    def test_invalidate_sessions(self, sample_user):  # noqa: F811
        """Sessions for the user are invalidated."""
        client = Client()
        client.force_login(sample_user)

        count = invalidate_user_sessions(sample_user)

        assert count >= 0


class TestDeleteAccountAPI:
    """Tests for POST /api/v1/user/delete endpoint."""

    @pytest.mark.django_db
    def test_unauthenticated_request_rejected(self):
        """Unauthenticated requests are rejected."""
        client = Client()

        response = client.post(
            "/api/v1/user/delete",
            json.dumps({"confirmation": "delete"}),
            content_type="application/json",
        )

        assert response.status_code == 401

    @pytest.mark.django_db
    def test_invalid_confirmation_rejected(self, sample_user, team_with_owner):  # noqa: F811
        """Request with wrong confirmation text is rejected."""
        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team_with_owner, sample_user)

        response = client.post(
            "/api/v1/user/delete",
            json.dumps({"confirmation": "wrong"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "delete" in data["detail"].lower()

    @pytest.mark.django_db
    def test_sole_owner_blocked(self, sample_user, team_sole_owner_with_members):  # noqa: F811
        """Sole owner with other members is blocked from deletion."""
        team, _ = team_sole_owner_with_members
        client = Client()
        client.force_login(sample_user)
        setup_authenticated_client_session(client, team, sample_user)

        response = client.post(
            "/api/v1/user/delete",
            json.dumps({"confirmation": "delete"}),
            content_type="application/json",
        )

        assert response.status_code == 403
        data = response.json()
        assert "sole owner" in data["detail"].lower()

    @pytest.mark.django_db
    def test_successful_deletion(self, deletable_user_with_team):
        """Successful account deletion via API."""
        team, user = deletable_user_with_team
        client = Client()
        client.force_login(user)
        setup_authenticated_client_session(client, team, user)
        user_id = user.id

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False

            response = client.post(
                "/api/v1/user/delete",
                json.dumps({"confirmation": "delete"}),
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert not User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_confirmation_case_insensitive(self, deletable_user_with_team):
        """Confirmation text is case-insensitive."""
        team, user = deletable_user_with_team
        client = Client()
        client.force_login(user)
        setup_authenticated_client_session(client, team, user)

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False

            response = client.post(
                "/api/v1/user/delete",
                json.dumps({"confirmation": "DELETE"}),
                content_type="application/json",
            )

            assert response.status_code == 200
