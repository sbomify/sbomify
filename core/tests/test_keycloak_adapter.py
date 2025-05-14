import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from allauth.socialaccount.models import SocialLogin, SocialAccount
from core.adapters import CustomSocialAccountAdapter

User = get_user_model()

@pytest.fixture
def adapter():
    return CustomSocialAccountAdapter()

@pytest.fixture
def mock_request():
    return HttpRequest()

@pytest.fixture
def mock_sociallogin():
    login = SocialLogin(user=User())
    login.account = SocialAccount(
        provider="keycloak",
        uid="test-keycloak-id",
        extra_data={
            "email_verified": True,
            "given_name": "Test",
            "family_name": "User"
        }
    )
    return login

@pytest.mark.django_db
class TestCustomSocialAccountAdapter:
    def test_populate_user_with_keycloak_data(self, adapter, mock_request, mock_sociallogin):
        """Test that user data is properly populated from Keycloak."""
        # Mock Keycloak data
        data = {
            "email": "test@example.com",
            "email_verified": True,
            "given_name": "John",
            "family_name": "Doe",
            "preferred_username": "johndoe"
        }

        # Populate user
        user = adapter.populate_user(mock_request, mock_sociallogin, data)

        # Verify fields
        assert user.email == "test@example.com"
        assert user.email_verified is True
        assert user.first_name == "John"
        assert user.last_name == "Doe"
        assert user.username == "johndoe"
        assert user.is_active is True

    def test_populate_user_without_preferred_username(self, adapter, mock_request, mock_sociallogin):
        """Test username generation when preferred_username is not provided."""
        # Mock Keycloak data without preferred_username
        data = {
            "email": "test@example.com",
            "email_verified": True,
            "given_name": "John",
            "family_name": "Doe"
        }

        # Populate user
        user = adapter.populate_user(mock_request, mock_sociallogin, data)

        # Verify username is generated from email
        assert user.username == "test.example.com"

    def test_populate_user_with_duplicate_username(self, adapter, mock_request, mock_sociallogin):
        """Test username generation handles duplicates."""
        # Create existing user with the username that would be generated
        existing_user = User.objects.create(
            username="test.example.com",
            email="existing@example.com"
        )

        # Mock Keycloak data
        data = {
            "email": "test@example.com",
            "email_verified": True,
            "given_name": "John",
            "family_name": "Doe"
        }

        # Populate user
        user = adapter.populate_user(mock_request, mock_sociallogin, data)

        # Verify username is unique
        assert user.username == "test.example.com_1"

    def test_pre_social_login_existing_user(self, adapter, mock_request, mock_sociallogin):
        """Test connecting to existing user with same email."""
        # Create existing user
        existing_user = User.objects.create(
            username="existing",
            email="test@example.com"
        )

        # Set up social login with same email
        mock_sociallogin.user.email = "test@example.com"

        # Process pre-social login
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Verify user is connected
        assert mock_sociallogin.is_existing
        assert mock_sociallogin.user.id == existing_user.id

    def test_pre_social_login_new_user(self, adapter, mock_request, mock_sociallogin):
        """Test handling of new user."""
        # Set up social login with new email
        mock_sociallogin.user.email = "new@example.com"

        # Process pre-social login
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Verify user is not connected
        assert not mock_sociallogin.is_existing
        assert mock_sociallogin.user.id is None

    def test_is_auto_signup_allowed(self, adapter, mock_request, mock_sociallogin):
        """Test that auto signup is always allowed."""
        assert adapter.is_auto_signup_allowed(mock_request, mock_sociallogin) is True