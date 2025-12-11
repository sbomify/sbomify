import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from allauth.socialaccount.models import SocialLogin, SocialAccount
from sbomify.apps.core.adapters import CustomSocialAccountAdapter
from django.test import RequestFactory

User = get_user_model()

@pytest.fixture
def adapter():
    return CustomSocialAccountAdapter()

@pytest.fixture
def mock_request():
    return RequestFactory().get("/")

@pytest.fixture
def mock_sociallogin():
    class DummySocialLogin:
        account = type("Account", (), {"provider": "keycloak", "extra_data": {}, "uid": "mock-uid"})()
        user = User()
        is_existing = False

        def connect(self, request, user):
            """Mock connect method to handle connecting to existing users."""
            self.user = user
            self.is_existing = True

    return DummySocialLogin()

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

    def test_populate_user_with_given_name_family_name(self, adapter, mock_request, mock_sociallogin):
        """Test user population with given_name and family_name."""
        data = {
            "email": "test@example.com",
            "email_verified": True,
            "given_name": "John",
            "family_name": "Doe",
            "preferred_username": "johndoe"
        }
        user = adapter.populate_user(mock_request, mock_sociallogin, data)
        assert user.first_name == "John"
        assert user.last_name == "Doe"
        assert user.username == "johndoe"
        assert user.email == "test@example.com"
        assert user.email_verified is True
        assert user.is_active is True

    def test_populate_user_with_first_name_last_name(self, adapter, mock_request, mock_sociallogin):
        """Test user population with first_name and last_name."""
        data = {
            "email": "test2@example.com",
            "email_verified": True,
            "first_name": "Jane",
            "last_name": "Smith",
            "preferred_username": "janesmith"
        }
        user = adapter.populate_user(mock_request, mock_sociallogin, data)
        assert user.first_name == "Jane"
        assert user.last_name == "Smith"
        assert user.username == "janesmith"
        assert user.email == "test2@example.com"
        assert user.email_verified is True
        assert user.is_active is True