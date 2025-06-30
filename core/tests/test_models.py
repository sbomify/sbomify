import pytest
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.base_user import AbstractBaseUser

from teams.models import get_team_name_for_user


@pytest.mark.django_db
class TestUser:
    def test_default_team_name(self, sample_user: AbstractBaseUser):
        sample_user.first_name = ""
        sample_user.save()
        assert get_team_name_for_user(sample_user) == "testuser's Workspace"

    def test_team_name_with_first_name(self, sample_user: AbstractBaseUser):
        sample_user.first_name = "John"
        sample_user.save()
        assert get_team_name_for_user(sample_user) == "John's Workspace"

    def test_user_with_social_auth(self, sample_user):
        """Test user with social auth."""
        social_auth = SocialAccount.objects.create(
            user=sample_user,
            provider="keycloak",
            extra_data={
                "user_metadata": {
                    "company": "Test Company",
                    "supplier_contact": {"name": "Test Supplier", "email": "test@supplier.com"},
                }
            },
        )
        social_auth.save()

        # Test that the user has social auth
        assert SocialAccount.objects.filter(user=sample_user).exists()
        assert SocialAccount.objects.filter(user=sample_user, provider="keycloak").exists()

    def test_user_with_multiple_social_auths(self, sample_user):
        """Test user with multiple social auths."""
        social_auth = SocialAccount.objects.create(
            user=sample_user,
            provider="keycloak",
            extra_data={
                "user_metadata": {
                    "company": "Test Company",
                    "supplier_contact": {"name": "Test Supplier", "email": "test@supplier.com"},
                }
            },
        )
        social_auth.save()

        # Test that the user has social auth
        assert SocialAccount.objects.filter(user=sample_user).exists()
        assert SocialAccount.objects.filter(user=sample_user, provider="keycloak").exists()
