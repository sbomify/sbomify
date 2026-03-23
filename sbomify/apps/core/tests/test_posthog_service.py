"""Tests for the PostHog server-side service module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings


@pytest.fixture(autouse=True)
def _reset_posthog_state():
    """Reset the posthog_service global state before each test."""
    from sbomify.apps.core import posthog_service

    posthog_service._client = None
    posthog_service._initialized = False
    yield
    posthog_service._client = None
    posthog_service._initialized = False


class TestHashEmail:
    """Tests for the hash_email() PII minimization function."""

    def test_hashes_email(self) -> None:
        from sbomify.apps.core.posthog_service import hash_email

        result = hash_email("test@example.com")
        assert len(result) == 16
        assert result.isalnum()

    def test_same_email_same_hash(self) -> None:
        from sbomify.apps.core.posthog_service import hash_email

        assert hash_email("test@example.com") == hash_email("test@example.com")

    def test_case_insensitive(self) -> None:
        from sbomify.apps.core.posthog_service import hash_email

        assert hash_email("Test@Example.com") == hash_email("test@example.com")

    def test_empty_returns_empty(self) -> None:
        from sbomify.apps.core.posthog_service import hash_email

        assert hash_email("") == ""

    def test_different_emails_different_hashes(self) -> None:
        from sbomify.apps.core.posthog_service import hash_email

        assert hash_email("a@example.com") != hash_email("b@example.com")


class TestGetClient:
    """Tests for _get_client() lazy initialization."""

    @override_settings(POSTHOG_API_KEY="")
    def test_returns_none_when_api_key_empty(self) -> None:
        from sbomify.apps.core.posthog_service import _get_client

        assert _get_client() is None

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_returns_client_when_configured(self) -> None:
        with patch("sbomify.apps.core.posthog_service.Posthog", create=True) as mock_cls:
            # Need to patch inside the lazy import
            with patch.dict("sys.modules", {"posthog": MagicMock(Posthog=mock_cls)}):
                from sbomify.apps.core.posthog_service import _get_client

                client = _get_client()
                assert client is not None
                mock_cls.assert_called_once()

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_initializes_only_once(self) -> None:
        with patch("sbomify.apps.core.posthog_service.Posthog", create=True) as mock_cls:
            with patch.dict("sys.modules", {"posthog": MagicMock(Posthog=mock_cls)}):
                from sbomify.apps.core.posthog_service import _get_client

                _get_client()
                _get_client()
                _get_client()
                mock_cls.assert_called_once()

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="http://insecure.example.com", DEBUG=False)
    def test_enforces_https_in_production(self) -> None:
        with patch("sbomify.apps.core.posthog_service.Posthog", create=True) as mock_cls:
            with patch.dict("sys.modules", {"posthog": MagicMock(Posthog=mock_cls)}):
                from sbomify.apps.core.posthog_service import _get_client

                _get_client()
                call_args = mock_cls.call_args
                assert call_args[1]["host"] == "https://insecure.example.com"

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="http://localhost:8000", DEBUG=True)
    def test_allows_http_in_debug_mode(self) -> None:
        with patch("sbomify.apps.core.posthog_service.Posthog", create=True) as mock_cls:
            with patch.dict("sys.modules", {"posthog": MagicMock(Posthog=mock_cls)}):
                from sbomify.apps.core.posthog_service import _get_client

                _get_client()
                call_args = mock_cls.call_args
                assert call_args[1]["host"] == "http://localhost:8000"


class TestCapture:
    """Tests for the capture() function."""

    @override_settings(POSTHOG_API_KEY="")
    def test_noop_when_disabled(self) -> None:
        from sbomify.apps.core.posthog_service import capture

        # Should not raise
        capture("user_123", "test:event", {"key": "value"})

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_calls_client_capture(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.capture("user_42", "billing:checkout_completed", {"plan": "business"})

        mock_client.capture.assert_called_once_with(
            "user_42", "billing:checkout_completed", properties={"plan": "business"}
        )

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_passes_groups_when_provided(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.capture("user_42", "sbom:uploaded", {"sbom_id": "abc"}, groups={"workspace": "team_key"})

        mock_client.capture.assert_called_once_with(
            "user_42", "sbom:uploaded", properties={"sbom_id": "abc"}, groups={"workspace": "team_key"}
        )

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_swallows_exceptions(self) -> None:
        mock_client = MagicMock()
        mock_client.capture.side_effect = RuntimeError("PostHog is down")
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        # Should not raise
        posthog_service.capture("user_42", "test:event")

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_sends_empty_dict_when_no_properties(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.capture("user_42", "user:signed_up")

        mock_client.capture.assert_called_once_with("user_42", "user:signed_up", properties={})


class TestSessionCorrelation:
    """Tests for session ID correlation between frontend and backend."""

    def test_get_session_id_from_cookie(self) -> None:
        from sbomify.apps.core.posthog_service import get_session_id

        request = MagicMock()
        request.COOKIES = {"ph_session_id": "abc123-session"}
        assert get_session_id(request) == "abc123-session"

    def test_get_session_id_returns_empty_when_no_cookie(self) -> None:
        from sbomify.apps.core.posthog_service import get_session_id

        request = MagicMock()
        request.COOKIES = {}
        assert get_session_id(request) == ""

    def test_get_session_id_handles_no_cookies_attr(self) -> None:
        from sbomify.apps.core.posthog_service import get_session_id

        assert get_session_id("not_a_request") == ""

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_capture_attaches_session_id_from_request(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        request = MagicMock()
        request.COOKIES = {"ph_session_id": "sess_xyz"}

        posthog_service.capture("user_42", "sbom:downloaded", {"sbom_id": "s1"}, request=request)

        call_args = mock_client.capture.call_args
        assert call_args[1]["properties"]["$session_id"] == "sess_xyz"
        assert call_args[1]["properties"]["sbom_id"] == "s1"

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_capture_skips_session_id_when_no_cookie(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        request = MagicMock()
        request.COOKIES = {}

        posthog_service.capture("user_42", "sbom:downloaded", request=request)

        call_args = mock_client.capture.call_args
        assert "$session_id" not in call_args[1]["properties"]

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_capture_works_without_request(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.capture("system", "sbom:uploaded")

        call_args = mock_client.capture.call_args
        assert "$session_id" not in call_args[1]["properties"]


class TestIdentify:
    """Tests for the identify() function."""

    @override_settings(POSTHOG_API_KEY="")
    def test_noop_when_disabled(self) -> None:
        from sbomify.apps.core.posthog_service import identify

        identify("user_123", {"email": "test@example.com"})

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_calls_client_identify(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.identify("user_42", {"email": "test@example.com", "name": "Test User"})

        mock_client.identify.assert_called_once_with(
            "user_42", properties={"email": "test@example.com", "name": "Test User"}
        )

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_swallows_exceptions(self) -> None:
        mock_client = MagicMock()
        mock_client.identify.side_effect = RuntimeError("PostHog is down")
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.identify("user_42", {"email": "test@example.com"})


class TestGroupIdentify:
    """Tests for the group_identify() function."""

    @override_settings(POSTHOG_API_KEY="")
    def test_noop_when_disabled(self) -> None:
        from sbomify.apps.core.posthog_service import group_identify

        group_identify("workspace", "team_abc", {"billing_plan": "business"})

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_calls_client_group_identify(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.group_identify("workspace", "team_abc", {"billing_plan": "business"})

        mock_client.group_identify.assert_called_once_with(
            "workspace", "team_abc", properties={"billing_plan": "business"}
        )

    @override_settings(POSTHOG_API_KEY="phc_test_key", POSTHOG_HOST="https://us.i.posthog.com")
    def test_swallows_exceptions(self) -> None:
        mock_client = MagicMock()
        mock_client.group_identify.side_effect = RuntimeError("PostHog is down")
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.group_identify("workspace", "team_abc")


class TestShutdown:
    """Tests for the shutdown() function."""

    def test_resets_state(self) -> None:
        from sbomify.apps.core import posthog_service

        posthog_service._client = MagicMock()
        posthog_service._initialized = True

        posthog_service.shutdown()

        assert posthog_service._client is None
        assert posthog_service._initialized is False

    def test_calls_client_shutdown(self) -> None:
        mock_client = MagicMock()
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.shutdown()

        mock_client.shutdown.assert_called_once()

    def test_swallows_shutdown_exceptions(self) -> None:
        mock_client = MagicMock()
        mock_client.shutdown.side_effect = RuntimeError("Shutdown failed")
        from sbomify.apps.core import posthog_service

        posthog_service._client = mock_client
        posthog_service._initialized = True

        posthog_service.shutdown()

        assert posthog_service._client is None

    def test_noop_when_no_client(self) -> None:
        from sbomify.apps.core import posthog_service

        posthog_service._client = None
        posthog_service._initialized = True

        # Should not raise
        posthog_service.shutdown()
