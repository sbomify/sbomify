"""Tests for core cron tasks."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class TestPurgeSoftDeletedUsers:
    """Tests for the purge_soft_deleted_users cron task."""

    @pytest.mark.django_db
    def test_purges_expired_user(self, django_user_model):
        """Users past the grace period are hard-deleted."""
        from sbomify.apps.core.cron import purge_soft_deleted_users
        from sbomify.apps.core.services.account_deletion import SOFT_DELETE_GRACE_DAYS

        user = django_user_model.objects.create_user(
            username="expired_user", email="expired@example.com", password="test",
            is_active=False,
        )
        user.deleted_at = timezone.now() - timedelta(days=SOFT_DELETE_GRACE_DAYS + 1)
        user.save()
        user_id = user.id

        with patch("sbomify.apps.core.services.account_deletion._delete_keycloak_user", return_value=True):
            purge_soft_deleted_users()

        assert not User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_does_not_purge_within_grace_period(self, django_user_model):
        """Users within the grace period are NOT purged."""
        from sbomify.apps.core.cron import purge_soft_deleted_users

        user = django_user_model.objects.create_user(
            username="recent_user", email="recent@example.com", password="test",
            is_active=False,
        )
        user.deleted_at = timezone.now() - timedelta(days=5)
        user.save()
        user_id = user.id

        purge_soft_deleted_users()

        assert User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_does_not_purge_active_users(self, django_user_model):
        """Active users are never purged even if deleted_at is set."""
        from sbomify.apps.core.cron import purge_soft_deleted_users
        from sbomify.apps.core.services.account_deletion import SOFT_DELETE_GRACE_DAYS

        user = django_user_model.objects.create_user(
            username="active_user", email="active@example.com", password="test",
            is_active=True,
        )
        user.deleted_at = timezone.now() - timedelta(days=SOFT_DELETE_GRACE_DAYS + 10)
        user.save()
        user_id = user.id

        purge_soft_deleted_users()

        assert User.objects.filter(id=user_id).exists()

    @pytest.mark.django_db
    def test_noop_when_no_users_to_purge(self):
        """Task completes cleanly when no users need purging."""
        from sbomify.apps.core.cron import purge_soft_deleted_users

        purge_soft_deleted_users()

    @pytest.mark.django_db
    def test_continues_after_individual_failure(self, django_user_model):
        """Task continues processing remaining users if one fails."""
        from sbomify.apps.core.cron import purge_soft_deleted_users
        from sbomify.apps.core.services.account_deletion import SOFT_DELETE_GRACE_DAYS

        user1 = django_user_model.objects.create_user(
            username="fail_user", email="fail@example.com", password="test",
            is_active=False,
        )
        user1.deleted_at = timezone.now() - timedelta(days=SOFT_DELETE_GRACE_DAYS + 1)
        user1.save()

        user2 = django_user_model.objects.create_user(
            username="succeed_user", email="succeed@example.com", password="test",
            is_active=False,
        )
        user2.deleted_at = timezone.now() - timedelta(days=SOFT_DELETE_GRACE_DAYS + 1)
        user2.save()
        user2_id = user2.id

        call_count = 0

        def mock_hard_delete(user):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Simulated failure")
            user.delete()
            return True

        with patch("sbomify.apps.core.services.account_deletion.hard_delete_user", side_effect=mock_hard_delete):
            purge_soft_deleted_users()

        assert not User.objects.filter(id=user2_id).exists()
