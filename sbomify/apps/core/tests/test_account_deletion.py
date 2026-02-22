from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

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

        result = validate_account_deletion(user_no_team)
        assert result.ok is True

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

        result = validate_account_deletion(owner)
        assert result.ok is False
        assert "sole owner" in result.error

    @pytest.mark.django_db
    def test_sole_owner_sole_member_can_delete(self, deletable_user_with_team):
        """Sole owner who is also the only member can delete (orphaned workspace)."""
        from sbomify.apps.core.services.account_deletion import validate_account_deletion

        _team, user = deletable_user_with_team
        result = validate_account_deletion(user)
        assert result.ok is True

    @pytest.mark.django_db
    def test_co_owner_can_delete(self, django_user_model):
        """Owner can delete when another owner exists (not sole owner)."""
        from sbomify.apps.core.services.account_deletion import validate_account_deletion
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Member, Team

        owner1 = django_user_model.objects.create_user(
            username="owner1", email="owner1@example.com", password="testpass123"
        )
        owner2 = django_user_model.objects.create_user(
            username="owner2", email="owner2@example.com", password="testpass123"
        )
        team = Team.objects.create(name="Co-Owned Team", billing_plan="community")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(user=owner1, team=team, role="owner", is_default_team=True)
        Member.objects.create(user=owner2, team=team, role="owner")

        result = validate_account_deletion(owner1)
        assert result.ok is True


class TestInvalidateUserSessions:
    """Tests for invalidate_user_sessions function."""

    @pytest.mark.django_db
    def test_deletes_user_sessions(self, user_no_team):
        """Sessions belonging to the user are deleted."""
        from sbomify.apps.core.services.account_deletion import invalidate_user_sessions

        store = SessionStore()
        store["_auth_user_id"] = str(user_no_team.id)
        store.create()

        count = invalidate_user_sessions(user_no_team)
        assert count == 1

    @pytest.mark.django_db
    def test_preserves_other_user_sessions(self, user_no_team, django_user_model):
        """Sessions belonging to other users are NOT deleted."""
        from sbomify.apps.core.services.account_deletion import invalidate_user_sessions

        other_user = django_user_model.objects.create_user(
            username="other_session_user", email="other_session@example.com", password="testpass123"
        )
        store = SessionStore()
        store["_auth_user_id"] = str(other_user.id)
        store.create()
        session_key = store.session_key

        count = invalidate_user_sessions(user_no_team)
        assert count == 0

        from django.contrib.sessions.models import Session

        assert Session.objects.filter(session_key=session_key).exists()

    @pytest.mark.django_db
    def test_handles_corrupt_sessions(self, user_no_team):
        """Corrupt sessions are skipped without crashing."""
        from django.contrib.sessions.models import Session

        from sbomify.apps.core.services.account_deletion import invalidate_user_sessions

        Session.objects.create(
            session_key="corrupt_session_key",
            session_data="not-valid-base64!!!",
            expire_date=timezone.now() + timedelta(days=1),
        )

        count = invalidate_user_sessions(user_no_team)
        assert count == 0


class TestSoftDeleteUserAccount:
    """Tests for soft_delete_user_account function."""

    @pytest.mark.django_db
    def test_soft_delete_deactivates_user(self, user_no_team):
        """Soft delete sets is_active=False and deleted_at."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            result = soft_delete_user_account(user_no_team)

        assert result.ok is True
        assert "scheduled for deletion" in result.value
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

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            soft_delete_user_account(user_no_team)

        assert not Invitation.objects.filter(email=user_no_team.email).exists()

    @pytest.mark.django_db
    def test_soft_delete_revokes_access_tokens(self, user_no_team):
        """Soft delete removes all access tokens for the user."""
        from sbomify.apps.access_tokens.models import AccessToken
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        AccessToken.objects.create(user=user_no_team, encoded_token="tok_test123", description="test-token")

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            soft_delete_user_account(user_no_team)

        assert not AccessToken.objects.filter(user=user_no_team).exists()

    @pytest.mark.django_db
    def test_soft_delete_deletes_orphaned_workspace(self, deletable_user_with_team):
        """Soft delete removes workspaces where user is sole owner and sole member."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account
        from sbomify.apps.teams.models import Team

        team, user = deletable_user_with_team
        team_id = team.pk

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            with patch("sbomify.apps.billing.config.is_billing_enabled", return_value=False):
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

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            with patch("sbomify.apps.billing.config.is_billing_enabled", return_value=True):
                with patch("sbomify.apps.billing.stripe_client.StripeClient") as MockStripeClient:
                    mock_client = MagicMock()
                    MockStripeClient.return_value = mock_client
                    soft_delete_user_account(user)

                    mock_client.cancel_subscription.assert_called_once_with("sub_test123", prorate=True)
                    mock_client.delete_customer.assert_called_once_with("cus_test123")

    @pytest.mark.django_db
    def test_soft_delete_aborts_on_keycloak_failure(self, user_no_team):
        """Soft delete fails gracefully when Keycloak disable fails."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=False):
            result = soft_delete_user_account(user_no_team)

        assert result.ok is False
        assert "temporarily unavailable" in result.error
        user_no_team.refresh_from_db()
        assert user_no_team.is_active is True

    @pytest.mark.django_db
    def test_soft_delete_rejects_already_deleted_user(self, user_no_team):
        """Concurrent deletion request is rejected."""
        from sbomify.apps.core.services.account_deletion import soft_delete_user_account

        user_no_team.is_active = False
        user_no_team.deleted_at = timezone.now()
        user_no_team.save()

        result = soft_delete_user_account(user_no_team)
        assert result.ok is False
        assert "already in progress" in result.error


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

        with patch("sbomify.apps.core.services.account_deletion._delete_keycloak_user", return_value=True):
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

    @pytest.mark.django_db
    def test_hard_delete_skips_user_without_deleted_at(self, user_no_team):
        """hard_delete_user refuses to delete inactive user without deleted_at."""
        from sbomify.apps.core.services.account_deletion import hard_delete_user

        user_no_team.is_active = False
        user_no_team.save()

        result = hard_delete_user(user_no_team)
        assert result is False
        assert User.objects.filter(id=user_no_team.id).exists()


class TestDeleteUserAccount:
    """Tests for delete_user_account (backward-compat wrapper)."""

    @pytest.mark.django_db
    def test_delete_user_account_calls_soft_delete(self, user_no_team):
        """delete_user_account delegates to soft_delete_user_account."""
        from sbomify.apps.core.services.account_deletion import delete_user_account

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            result = delete_user_account(user_no_team)

        assert result.ok is True
        assert "scheduled for deletion" in result.value
        user_no_team.refresh_from_db()
        assert user_no_team.is_active is False
        assert user_no_team.deleted_at is not None


class TestDeleteAccountAPI:
    """Tests for POST /api/v1/user/delete endpoint."""

    @pytest.fixture
    def api_user_and_team(self, db):
        BillingPlan.objects.get_or_create(
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
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Member, Team

        user = User.objects.create_user(
            username="api_delete_user",
            email="api_delete@example.com",
            password="testpass123",
        )
        team = Team.objects.create(name="API Delete Team", billing_plan="community")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        yield user, team

    @pytest.mark.django_db
    def test_delete_with_correct_confirmation(self, api_user_and_team):
        """POST /user/delete with correct confirmation soft-deletes user."""
        user, team = api_user_and_team
        client = Client()
        client.force_login(user)
        setup_authenticated_client_session(client, team, user)

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            with patch("sbomify.apps.billing.config.is_billing_enabled", return_value=False):
                response = client.post(
                    "/api/v1/user/delete",
                    data={"confirmation": "delete"},
                    content_type="application/json",
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        user.refresh_from_db()
        assert user.is_active is False

    @pytest.mark.django_db
    def test_delete_with_wrong_confirmation(self, api_user_and_team):
        """POST /user/delete with wrong confirmation text returns 400."""
        user, team = api_user_and_team
        client = Client()
        client.force_login(user)
        setup_authenticated_client_session(client, team, user)

        response = client.post(
            "/api/v1/user/delete",
            data={"confirmation": "wrong"},
            content_type="application/json",
        )

        assert response.status_code == 400

    @pytest.mark.django_db
    def test_delete_case_insensitive_confirmation(self, api_user_and_team):
        """POST /user/delete accepts 'DELETE' (case-insensitive)."""
        user, team = api_user_and_team
        client = Client()
        client.force_login(user)
        setup_authenticated_client_session(client, team, user)

        with patch("sbomify.apps.core.services.account_deletion._disable_keycloak_user", return_value=True):
            with patch("sbomify.apps.billing.config.is_billing_enabled", return_value=False):
                response = client.post(
                    "/api/v1/user/delete",
                    data={"confirmation": "DELETE"},
                    content_type="application/json",
                )

        assert response.status_code == 200

    @pytest.mark.django_db
    def test_delete_unauthenticated_rejected(self):
        """POST /user/delete without auth returns 401."""
        client = Client()
        response = client.post(
            "/api/v1/user/delete",
            data={"confirmation": "delete"},
            content_type="application/json",
        )
        assert response.status_code in (401, 403)
