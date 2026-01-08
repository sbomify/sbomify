import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from sbomify.apps.core.adapters import CustomSocialAccountAdapter

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
        # Create existing user with email_verified=False
        existing_user = User.objects.create(
            username="sync_test_user", email="sync_test@example.com", email_verified=False
        )

        # Create a sociallogin with email_verified=True from Keycloak
        class SyncTestSocialLogin:
            account = type(
                "Account", (), {"provider": "keycloak", "extra_data": {"email_verified": True}, "uid": "sync-test-uid"}
            )()
            user = existing_user
            is_existing = True

            def connect(self, request, user):
                self.user = user
                self.is_existing = True

        mock_sociallogin = SyncTestSocialLogin()

        # Process pre-social login - should sync email_verified
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Refresh from database and verify email_verified was synced
        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_does_not_sync_if_unchanged(self, adapter, mock_request):
        """Test that email_verified is not updated if already in sync."""
        # Create existing user with email_verified=True
        existing_user = User.objects.create(username="no_sync_user", email="no_sync@example.com", email_verified=True)

        # Create a sociallogin with email_verified=True (same value)
        class NoSyncSocialLogin:
            account = type(
                "Account", (), {"provider": "keycloak", "extra_data": {"email_verified": True}, "uid": "no-sync-uid"}
            )()
            user = existing_user
            is_existing = True

            def connect(self, request, user):
                self.user = user
                self.is_existing = True

        mock_sociallogin = NoSyncSocialLogin()

        # Process pre-social login - should not trigger a save
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Verify email_verified is still True
        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_syncs_email_verified_to_false(self, adapter, mock_request):
        """Test that email_verified can be synced from True to False."""
        # Create existing user with email_verified=True
        existing_user = User.objects.create(
            username="sync_false_user", email="sync_false@example.com", email_verified=True
        )

        # Create a sociallogin with email_verified=False from Keycloak
        class SyncFalseSocialLogin:
            account = type(
                "Account",
                (),
                {"provider": "keycloak", "extra_data": {"email_verified": False}, "uid": "sync-false-uid"},
            )()
            user = existing_user
            is_existing = True

            def connect(self, request, user):
                self.user = user
                self.is_existing = True

        mock_sociallogin = SyncFalseSocialLogin()

        # Process pre-social login - should sync email_verified to False
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Refresh from database and verify email_verified was synced to False
        existing_user.refresh_from_db()
        assert existing_user.email_verified is False

    def test_pre_social_login_syncs_email_verified_from_github(self, adapter, mock_request):
        """Test that email_verified is synced from GitHub on login."""
        # Create existing user with email_verified=False
        existing_user = User.objects.create(username="github_user", email="github@example.com", email_verified=False)

        # Create a sociallogin with email_verified=True from GitHub
        class GitHubSocialLogin:
            account = type(
                "Account",
                (),
                {"provider": "github", "extra_data": {"email_verified": True}, "uid": "github-uid"},
            )()
            user = existing_user
            is_existing = True

            def connect(self, request, user):
                self.user = user
                self.is_existing = True

        mock_sociallogin = GitHubSocialLogin()

        # Process pre-social login - should sync email_verified
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Refresh from database and verify email_verified was synced
        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_syncs_email_verified_from_google(self, adapter, mock_request):
        """Test that email_verified is synced from Google on login (uses verified_email field)."""
        # Create existing user with email_verified=False
        existing_user = User.objects.create(username="google_user", email="google@example.com", email_verified=False)

        # Create a sociallogin with verified_email=True from Google (note: different field name)
        class GoogleSocialLogin:
            account = type(
                "Account",
                (),
                {"provider": "google", "extra_data": {"verified_email": True}, "uid": "google-uid"},
            )()
            user = existing_user
            is_existing = True

            def connect(self, request, user):
                self.user = user
                self.is_existing = True

        mock_sociallogin = GoogleSocialLogin()

        # Process pre-social login - should sync email_verified
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Refresh from database and verify email_verified was synced
        existing_user.refresh_from_db()
        assert existing_user.email_verified is True

    def test_pre_social_login_does_not_sync_unknown_provider(self, adapter, mock_request):
        """Test that email_verified is not synced for unknown providers."""
        # Create existing user with email_verified=False
        existing_user = User.objects.create(username="unknown_user", email="unknown@example.com", email_verified=False)

        # Create a sociallogin from an unknown provider
        class UnknownSocialLogin:
            account = type(
                "Account",
                (),
                {"provider": "unknown_provider", "extra_data": {"email_verified": True}, "uid": "unknown-uid"},
            )()
            user = existing_user
            is_existing = True

            def connect(self, request, user):
                self.user = user
                self.is_existing = True

        mock_sociallogin = UnknownSocialLogin()

        # Process pre-social login - should NOT sync email_verified
        adapter.pre_social_login(mock_request, mock_sociallogin)

        # Refresh from database and verify email_verified was NOT changed
        existing_user.refresh_from_db()
        assert existing_user.email_verified is False
