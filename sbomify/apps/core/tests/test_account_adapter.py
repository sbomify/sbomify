"""Tests for CustomAccountAdapter."""

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from sbomify.apps.core.adapters import CustomAccountAdapter

User = get_user_model()


@pytest.fixture
def adapter():
    """Fixture for CustomAccountAdapter instance."""
    return CustomAccountAdapter()


@pytest.fixture
def mock_request():
    """Fixture for mock HTTP request."""
    return RequestFactory().get("/")


@pytest.fixture
def mock_signup_form():
    """Fixture for mock signup form with cleaned data."""

    class MockForm:
        def __init__(self, email):
            self.cleaned_data = {"email": email}

    return MockForm


@pytest.mark.django_db
class TestCustomAccountAdapter:
    """Test suite for CustomAccountAdapter."""

    def test_save_user_populates_email(self, adapter, mock_request, mock_signup_form):
        """Test that save_user populates user.email from form data."""
        user = User()
        form = mock_signup_form("newuser@example.com")

        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        assert saved_user.email == "newuser@example.com"
        assert saved_user.username == "newuser.example.com"

    def test_save_user_generates_username_from_email(self, adapter, mock_request, mock_signup_form):
        """Test that username is generated from email."""
        user = User()
        form = mock_signup_form("john.doe@company.com")

        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        assert saved_user.username == "john.doe.company.com"
        assert saved_user.email == "john.doe@company.com"

    def test_save_user_handles_duplicate_username(self, adapter, mock_request, mock_signup_form):
        """Test that duplicate usernames are handled by appending counter."""
        # Create existing user with username that would be generated
        User.objects.create(username="test.example.com", email="existing@example.com")

        user = User()
        form = mock_signup_form("test@example.com")

        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        assert saved_user.username == "test.example.com_1"
        assert saved_user.email == "test@example.com"

    def test_save_user_handles_multiple_duplicate_usernames(self, adapter, mock_request, mock_signup_form):
        """Test handling multiple duplicate usernames."""
        # Create existing users with conflicting usernames
        User.objects.create(username="test.example.com", email="existing1@example.com")
        User.objects.create(username="test.example.com_1", email="existing2@example.com")

        user = User()
        form = mock_signup_form("test@example.com")

        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        assert saved_user.username == "test.example.com_2"
        assert saved_user.email == "test@example.com"

    def test_save_user_sanitizes_email(self, adapter, mock_request, mock_signup_form):
        """Test that email is sanitized (whitespace stripped)."""
        user = User()
        form = mock_signup_form("  spaced@example.com  ")

        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        assert saved_user.email == "spaced@example.com"
        assert saved_user.username == "spaced.example.com"

    def test_save_user_with_commit_true(self, adapter, mock_request, mock_signup_form):
        """Test that user is saved to database when commit=True."""
        user = User()
        form = mock_signup_form("committed@example.com")

        saved_user = adapter.save_user(mock_request, user, form, commit=True)

        # Verify user was saved to database
        assert saved_user.pk is not None
        db_user = User.objects.get(email="committed@example.com")
        assert db_user.email == "committed@example.com"
        assert db_user.username == "committed.example.com"

    def test_save_user_without_email(self, adapter, mock_request):
        """Test handling when form has no email."""

        class EmptyForm:
            cleaned_data = {}

        user = User()
        form = EmptyForm()

        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        # Should not crash, but email won't be set
        assert saved_user.email == ""

    def test_save_user_with_invalid_email_format(self, adapter, mock_request):
        """Test handling of invalid email format."""

        class InvalidEmailForm:
            cleaned_data = {"email": "not-an-email"}

        user = User()
        form = InvalidEmailForm()

        # Should not crash even with invalid email
        # The parent class may set the email, but we log a warning
        saved_user = adapter.save_user(mock_request, user, form, commit=False)

        # The email gets set by parent class before validation, so it will be present
        # but a warning is logged about invalid format
        assert saved_user.email == "not-an-email"  # Parent class sets it
