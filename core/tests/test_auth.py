from unittest.mock import patch

import pytest
from social_core.backends.base import BaseAuth
from social_core.exceptions import AuthFailed
from social_core.strategy import BaseStrategy

from core.auth import SafeAuth0OAuth2
from core.pipeline.auth0 import require_email


class MockStorage:
    class MockPartial:
        def prepare(self, *args, **kwargs):
            return None

    def __init__(self):
        self.partial = self.MockPartial()


class MockStrategy(BaseStrategy):
    def __init__(self):
        self.settings = {}
        self.storage = MockStorage()
        super().__init__(storage=self.storage)


class MockAuth0Backend(BaseAuth):
    name = "auth0"


@pytest.fixture
def auth0_backend():
    return MockAuth0Backend()


@pytest.fixture
def strategy():
    return MockStrategy()


def test_require_email_existing_user(sample_user, auth0_backend, strategy):
    """Test that existing users with email pass through."""
    result = require_email(
        strategy=strategy,
        backend=auth0_backend,
        details={},
        user=sample_user,
        is_new=False,
        pipeline_index=0
    )
    assert result["is_new"] is False
    assert result["email_verified"] is False
    assert result["details"]["email"] == sample_user.email


def test_require_email_new_user_no_email(auth0_backend, strategy):
    """Test that new users without email are rejected."""
    with pytest.raises(AuthFailed) as exc:
        require_email(
            strategy=strategy,
            backend=auth0_backend,
            details={},
            user=None,
            is_new=True,
            pipeline_index=0
        )
    assert "Email is required to register" in str(exc.value)


def test_require_email_new_user_unverified(auth0_backend, strategy):
    """Test that new users with unverified email are rejected."""
    with pytest.raises(AuthFailed) as exc:
        require_email(
            strategy=strategy,
            backend=auth0_backend,
            details={"email": "test@example.com"},
            user=None,
            is_new=True,
            response={"email_verified": False},
            pipeline_index=0
        )
    assert "verify your email address" in str(exc.value)


def test_require_email_new_user_verified(auth0_backend, strategy):
    """Test that new users with verified email pass through."""
    result = require_email(
        strategy=strategy,
        backend=auth0_backend,
        details={"email": "test@example.com"},
        user=None,
        is_new=True,
        response={"email_verified": True},
        pipeline_index=0
    )
    assert result["email_verified"] is True
    assert result["is_new"] is True


@pytest.mark.django_db
def test_require_email_existing_user_no_response(sample_user, auth0_backend, strategy):
    """Test that existing users work even without response data."""
    result = require_email(
        strategy=strategy,
        backend=auth0_backend,
        details={"email": sample_user.email},
        user=sample_user,
        is_new=False,
        response=None,
        pipeline_index=0
    )
    assert result["email_verified"] is False  # Default when no response
    assert result["is_new"] is False
    assert result["details"]["email"] == sample_user.email


@patch("core.auth.Auth0OAuth2.get_json")
def test_safe_auth0_backend_missing_email(mock_get_json):
    """Test that our custom Auth0 backend handles missing email."""
    mock_get_json.return_value = {"keys": []}  # Mock JWKS response

    backend = SafeAuth0OAuth2()
    response = {
        "user_email": "test@example.com",  # Email in alternate field
        "name": "Test User"
    }
    details = backend.get_user_details(response)
    assert details["email"] == "test@example.com"


@patch("core.auth.Auth0OAuth2.get_json")
def test_safe_auth0_backend_alternate_email_fields(mock_get_json):
    """Test that our custom Auth0 backend tries multiple email fields."""
    mock_get_json.return_value = {"keys": []}  # Mock JWKS response

    backend = SafeAuth0OAuth2()

    # Test with verified_email
    response = {
        "verified_email": "test@example.com",
        "name": "Test User"
    }
    details = backend.get_user_details(response)
    assert details["email"] == "test@example.com"

    # Test with user_email
    response = {
        "user_email": "test@example.com",
        "name": "Test User"
    }
    details = backend.get_user_details(response)
    assert details["email"] == "test@example.com"


@patch("core.auth.Auth0OAuth2.get_json")
def test_safe_auth0_backend_normal_response(mock_get_json):
    """Test that our custom Auth0 backend works with normal responses."""
    mock_get_json.return_value = {"keys": []}  # Mock JWKS response

    backend = SafeAuth0OAuth2()
    response = {
        "email": "test@example.com",
        "name": "Test User"
    }
    details = backend.get_user_details(response)
    assert details["email"] == "test@example.com"