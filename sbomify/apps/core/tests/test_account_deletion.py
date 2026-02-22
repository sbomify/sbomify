import pytest
from django.utils import timezone


@pytest.fixture
def user_no_team(django_user_model):
    """Create a user that does not belong to any team."""
    user = django_user_model.objects.create_user(
        username="user_no_team",
        email="user_no_team@example.com",
        password="testpass123",
    )
    yield user
    user.delete()


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
