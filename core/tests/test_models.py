import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from social_django.models import UserSocialAuth

from teams.models import get_team_name_for_user


@pytest.mark.django_db
class TestUser:
    def test_default_team_name(self, sample_user: AbstractBaseUser):
        sample_user.first_name = ""
        sample_user.save()
        assert get_team_name_for_user(sample_user) == "My Team"

    def test_team_name_with_first_name(self, sample_user: AbstractBaseUser):
        sample_user.first_name = "John"
        sample_user.save()
        assert get_team_name_for_user(sample_user) == "John's Team"

    def test_team_name_with_company(self, sample_user: AbstractBaseUser):
        sample_user.first_name = ""
        sample_user.save()
        social_auth = UserSocialAuth.objects.create(
            user=sample_user,
            provider="auth0",
            extra_data={"user_metadata": {"company": "Acme Corp"}}
        )
        social_auth.save()
        assert get_team_name_for_user(sample_user) == "Acme Corp"

    def test_team_name_company_takes_precedence(self, sample_user: AbstractBaseUser):
        sample_user.first_name = "John"
        sample_user.save()
        social_auth = UserSocialAuth.objects.create(
            user=sample_user,
            provider="auth0",
            extra_data={"user_metadata": {"company": "Acme Corp"}}
        )
        social_auth.save()
        assert get_team_name_for_user(sample_user) == "Acme Corp"