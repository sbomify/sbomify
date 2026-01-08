from typing import Protocol

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import RequestFactory

from sbomify.apps.core.adapters import CustomSocialAccountAdapter

User = get_user_model()


class SocialAccount(Protocol):
    """Protocol for social account objects."""

    provider: str
    extra_data: dict
    uid: str


class MockSocialLoginProtocol(Protocol):
    """Protocol for mock social login objects used in testing."""

    account: SocialAccount
    user: "User"  # type: ignore[type-arg]
    is_existing: bool

    def connect(self, request: HttpRequest, user: "User") -> None:  # type: ignore[type-arg]
        """Connect this social login to an existing user."""
        ...


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


def create_mock_sociallogin(user, provider: str, extra_data: dict, uid: str = "test-uid") -> MockSocialLoginProtocol:
    """Create a mock social login object for testing.

    Args:
        user: The Django user to associate with the social login
        provider: The social provider name (e.g., 'keycloak', 'github', 'google')
        extra_data: The extra_data dict from the social provider
        uid: The unique identifier from the provider

    Returns:
        MockSocialLoginProtocol: A mock social login object suitable for testing adapter methods
    """

    class MockSocialLogin:
        account = type("Account", (), {"provider": provider, "extra_data": extra_data, "uid": uid})()
        is_existing = True

        def __init__(self, user):
            self.user = user

        def connect(self, request, user):
            self.user = user
            self.is_existing = True

    return MockSocialLogin(user)


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
            "preferred_username": "johndoe",
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
        data = {"email": "test@example.com", "email_verified": True, "given_name": "John", "family_name": "Doe"}

        # Populate user
        user = adapter.populate_user(mock_request, mock_sociallogin, data)

        # Verify username is generated from email
        assert user.username == "test.example.com"

    def test_populate_user_with_duplicate_username(self, adapter, mock_request, mock_sociallogin):
        """Test username generation handles duplicates."""
        # Create existing user with the username that would be generated
        User.objects.create(username="test.example.com", email="existing@example.com")

        # Mock Keycloak data
        data = {"email": "test@example.com", "email_verified": True, "given_name": "John", "family_name": "Doe"}

        # Populate user
        user = adapter.populate_user(mock_request, mock_sociallogin, data)

        # Verify username is unique
        assert user.username == "test.example.com_1"

    def test_pre_social_login_existing_user(self, adapter, mock_request, mock_sociallogin):
        """Test connecting to existing user with same email."""
        # Create existing user
        existing_user = User.objects.create(username="existing", email="test@example.com")

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
            "preferred_username": "johndoe",
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
            "preferred_username": "janesmith",
        }
        user = adapter.populate_user(mock_request, mock_sociallogin, data)
        assert user.first_name == "Jane"
        assert user.last_name == "Smith"
        assert user.username == "janesmith"
        assert user.email == "test2@example.com"
        assert user.email_verified is True
        assert user.is_active is True

    def test_pre_social_login_syncs_email_verified_on_existing_user(self, adapter, mock_request):
        """Test that email_verified is synced from Keycloak on every login for existing users."""
        existing_user = User.objects.create(
            username="sync_test_user", email="sync_test@example.com", email_verified=False
        )
        mock_sociallogin = create_mock_sociallogin(
            user=existing_user,
            provider="keycloak",
            extra_data={"email_verified": True},
            uid="sync-test-uid",
        )

        adapter.pre_social_login(mock_request, mock_sociallogin)

        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_does_not_sync_if_unchanged(self, adapter, mock_request):
        """Test that email_verified is not updated if already in sync."""
        existing_user = User.objects.create(username="no_sync_user", email="no_sync@example.com", email_verified=True)
        mock_sociallogin = create_mock_sociallogin(
            user=existing_user,
            provider="keycloak",
            extra_data={"email_verified": True},
            uid="no-sync-uid",
        )

        adapter.pre_social_login(mock_request, mock_sociallogin)

        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_syncs_email_verified_to_false(self, adapter, mock_request):
        """Test that email_verified can be synced from True to False."""
        existing_user = User.objects.create(
            username="sync_false_user", email="sync_false@example.com", email_verified=True
        )
        mock_sociallogin = create_mock_sociallogin(
            user=existing_user,
            provider="keycloak",
            extra_data={"email_verified": False},
            uid="sync-false-uid",
        )

        adapter.pre_social_login(mock_request, mock_sociallogin)

        existing_user.refresh_from_db()
        assert existing_user.email_verified is False

    def test_pre_social_login_syncs_email_verified_from_github(self, adapter, mock_request):
        """Test that email_verified is synced from GitHub on login."""
        existing_user = User.objects.create(username="github_user", email="github@example.com", email_verified=False)
        mock_sociallogin = create_mock_sociallogin(
            user=existing_user,
            provider="github",
            extra_data={"email_verified": True},
            uid="github-uid",
        )

        adapter.pre_social_login(mock_request, mock_sociallogin)

        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_syncs_email_verified_from_google(self, adapter, mock_request):
        """Test that email_verified is synced from Google on login (uses verified_email field)."""
        existing_user = User.objects.create(username="google_user", email="google@example.com", email_verified=False)
        # Note: Google uses 'verified_email' instead of 'email_verified'
        mock_sociallogin = create_mock_sociallogin(
            user=existing_user,
            provider="google",
            extra_data={"verified_email": True},
            uid="google-uid",
        )

        adapter.pre_social_login(mock_request, mock_sociallogin)

        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_does_not_sync_unknown_provider(self, adapter, mock_request):
        """Test that email_verified is not synced for unknown providers."""
        existing_user = User.objects.create(username="unknown_user", email="unknown@example.com", email_verified=False)
        mock_sociallogin = create_mock_sociallogin(
            user=existing_user,
            provider="unknown_provider",
            extra_data={"email_verified": True},
            uid="unknown-uid",
        )

        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Should NOT sync - unknown provider
        existing_user.refresh_from_db()
        assert existing_user.email_verified is False
