from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


@pytest.fixture
def user_no_team(django_user_model):
    """Create a user that does not belong to any team."""
    user = django_user_model.objects.create_user(
        username="user_no_team",
        email="user_no_team@example.com",
        password="testpass123",
    )
    yield user
    if User.objects.filter(id=user.id).exists():
        user.delete()


@pytest.fixture
def deletable_user_with_team(django_user_model):
    """Create a user who is the sole owner and sole member of a team."""
    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Member, Team

    user = django_user_model.objects.create_user(
        username="deletable_user",
        email="deletable@example.com",
        password="testpass123",
    )
    team = Team.objects.create(name="Deletable Team", billing_plan="community")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

    yield team, user

    if User.objects.filter(id=user.id).exists():
        user.delete()
    if Team.objects.filter(pk=team.pk).exists():
        team.delete()


class TestSoftDelete:
    """Tests for soft-delete field on User model."""

    @pytest.mark.django_db
    def test_user_has_deleted_at_field(self, user_no_team):
        """User model has deleted_at field, initially None."""
        assert user_no_team.deleted_at is None

    @pytest.mark.django_db
    def test_deleted_at_can_be_set(self, user_no_team):
        """deleted_at can be set to a datetime."""
        now = timezone.now()
        user_no_team.deleted_at = now
        user_no_team.save()
        user_no_team.refresh_from_db()
        assert user_no_team.deleted_at == now


class TestValidateAccountDeletion:
    """Tests for validate_account_deletion function."""

    @pytest.mark.django_db
    def test_user_with_no_teams_can_delete(self, user_no_team):
        """User with no team memberships can delete their account."""
        from sbomify.apps.core.services.account_deletion import validate_account_deletion

        can_delete, error = validate_account_deletion(user_no_team)
        assert can_delete is True
        assert error is None

    @pytest.mark.django_db
    def test_sole_owner_with_other_members_blocked(self, django_user_model):
        """Sole owner of workspace with other members cannot delete."""
        from sbomify.apps.core.services.account_deletion import validate_account_deletion
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Member, Team

        owner = django_user_model.objects.create_user(
            username="owner", email="owner@example.com", password="testpass123"
        )
        other_user = django_user_model.objects.create_user(
            username="other", email="other@example.com", password="testpass123"
        )
        team = Team.objects.create(name="Shared Team", billing_plan="community")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(user=owner, team=team, role="owner", is_default_team=True)
        Member.objects.create(user=other_user, team=team, role="admin")

        can_delete, error = validate_account_deletion(owner)
        assert can_delete is False
        assert "sole owner" in error

        other_user.delete()
        owner.delete()
        team.delete()

    @pytest.mark.django_db
    def test_sole_owner_sole_member_can_delete(self, deletable_user_with_team):
        """Sole owner who is also the only member can delete (orphaned workspace)."""
        from sbomify.apps.core.services.account_deletion import validate_account_deletion

        _team, user = deletable_user_with_team
        can_delete, error = validate_account_deletion(user)
        assert can_delete is True
        assert error is None


class TestSoftDeleteUserAccount:
    """Tests for soft_delete_user_account function."""

    @pytest.mark.django_db
    def test_soft_delete_deactivates_user(self, user_no_team):
        """Soft delete sets is_active=False and deleted_at."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            success, message = soft_delete_user_account(user_no_team)

        assert success is True
        assert "scheduled for deletion" in message
        user_no_team.refresh_from_db()
        assert user_no_team.is_active is False
        assert user_no_team.deleted_at is not None
        assert User.objects.filter(id=user_no_team.id).exists()

    @pytest.mark.django_db
    def test_soft_delete_cleans_invitations(self, user_no_team):
        """Soft delete removes incoming invitations for user's email."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Invitation, Team

        team = Team.objects.create(name="Other Team", billing_plan="community")
        team.key = number_to_random_token(team.pk)
        team.save()
        Invitation.objects.create(team=team, email=user_no_team.email, role="admin")

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            soft_delete_user_account(user_no_team)

        assert not Invitation.objects.filter(email=user_no_team.email).exists()
        team.delete()

    @pytest.mark.django_db
    def test_soft_delete_revokes_access_tokens(self, user_no_team):
        """Soft delete removes all access tokens for the user."""
        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        AccessToken.objects.create(user=user_no_team, name="test-token", token="tok_test123")

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            soft_delete_user_account(user_no_team)

        assert not AccessToken.objects.filter(user=user_no_team).exists()

    @pytest.mark.django_db
    def test_soft_delete_deletes_orphaned_workspace(self, deletable_user_with_team):
        """Soft delete removes workspaces where user is sole owner and sole member."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account
        from sbomify.apps.teams.models import Team

        team, user = deletable_user_with_team
        team_id = team.pk

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            soft_delete_user_account(user)

        assert not Team.objects.filter(pk=team_id).exists()

    @pytest.mark.django_db
    def test_soft_delete_cancels_stripe_for_orphaned_workspace(self, deletable_user_with_team):
        """Soft delete cancels Stripe subscription for orphaned workspaces."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        team, user = deletable_user_with_team
        team.billing_plan_limits = {
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
        }
        team.save()

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            with patch("sbomify.apps.core.services.account_deletion.is_billing_enabled", return_value=True):
                with patch("sbomify.apps.core.services.account_deletion.get_stripe_client") as mock_stripe:
                    mock_client = MagicMock()
                    mock_stripe.return_value = mock_client
                    soft_delete_user_account(user)

                    mock_client.cancel_subscription.assert_called_once_with("sub_test123", prorate=True)
                    mock_client.delete_customer.assert_called_once_with("cus_test123")


class TestHardDeleteUser:
    """Tests for hard_delete_user function."""

    @pytest.mark.django_db
    def test_hard_delete_removes_user(self, user_no_team):
        """hard_delete_user permanently removes a soft-deleted user."""
        from sbomify.apps.core.services.account_deletion import hard_delete_user

        user_id = user_no_team.id
        user_no_team.is_active = False
        user_no_team.deleted_at = timezone.now() - timedelta(days=15)
        user_no_team.save()

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            result = hard_delete_user(user_no_team)

        assert result is True
        assert not User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_hard_delete_skips_active_user(self, user_no_team):
        """hard_delete_user refuses to delete an active user."""
        from sbomify.apps.core.services.account_deletion import hard_delete_user

        result = hard_delete_user(user_no_team)
        assert result is False
        assert User.objects.filter(id=user_no_team.id).exists()


class TestDeleteUserAccount:
    """Tests for delete_user_account (backward-compat wrapper)."""

    @pytest.mark.django_db
    def test_delete_user_account_calls_soft_delete(self, user_no_team):
        """delete_user_account delegates to soft_delete_user_account."""
        from sbomify.apps.core.services.account_deletion import delete_user_account

        with patch("sbomify.apps.core.services.account_deletion.settings") as mock_settings:
            mock_settings.USE_KEYCLOAK = False
            success, message = delete_user_account(user_no_team)

        assert success is True
        assert "scheduled for deletion" in message
        user_no_team.refresh_from_db()
        assert user_no_team.is_active is False
        assert user_no_team.deleted_at is not None
