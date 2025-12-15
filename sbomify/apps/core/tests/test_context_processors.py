"""Tests for context processors."""

import os
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.core.context_processors import (
    pending_invitations_context,
    version_context,
)


class TestVersionContext:
    """Tests for the version_context context processor."""

    def test_returns_app_version_from_package_metadata(self) -> None:
        """Test that app_version is returned from package metadata."""
        request = MagicMock()

        with patch("sbomify.apps.core.context_processors.version") as mock_version:
            mock_version.return_value = "1.2.3"
            result = version_context(request)

        assert result["app_version"] == "1.2.3"

    def test_returns_none_when_package_not_found(self) -> None:
        """Test that app_version is None when package is not installed."""
        from importlib.metadata import PackageNotFoundError

        request = MagicMock()

        with patch("sbomify.apps.core.context_processors.version") as mock_version:
            mock_version.side_effect = PackageNotFoundError()
            result = version_context(request)

        assert result["app_version"] is None

    def test_returns_git_commit_from_environment(self) -> None:
        """Test that git commit info is returned from environment variables."""
        request = MagicMock()

        env_vars = {
            "SBOMIFY_GIT_COMMIT_SHORT": "abc1234",
            "SBOMIFY_GIT_COMMIT": "abc1234567890abcdef",
            "SBOMIFY_GIT_REF": "v1.2.3",
            "SBOMIFY_BUILD_TYPE": "release",
            "SBOMIFY_BUILD_DATE": "2024-01-15T10:30:00Z",
        }

        with (
            patch("sbomify.apps.core.context_processors.version") as mock_version,
            patch.dict(os.environ, env_vars, clear=False),
        ):
            mock_version.return_value = "1.2.3"
            result = version_context(request)

        assert result["git_commit"] == "abc1234"
        assert result["git_commit_full"] == "abc1234567890abcdef"
        assert result["git_ref"] == "v1.2.3"
        assert result["build_type"] == "release"
        assert result["build_date"] == "2024-01-15T10:30:00Z"

    def test_returns_none_for_missing_environment_variables(self) -> None:
        """Test that None is returned for missing environment variables."""
        request = MagicMock()

        # Clear any existing SBOMIFY_ environment variables
        env_to_clear = {
            "SBOMIFY_GIT_COMMIT_SHORT": "",
            "SBOMIFY_GIT_COMMIT": "",
            "SBOMIFY_GIT_REF": "",
            "SBOMIFY_BUILD_TYPE": "",
            "SBOMIFY_BUILD_DATE": "",
        }

        with (
            patch("sbomify.apps.core.context_processors.version") as mock_version,
            patch.dict(os.environ, env_to_clear, clear=False),
        ):
            mock_version.return_value = "1.2.3"
            result = version_context(request)

        assert result["git_commit"] is None
        assert result["git_commit_full"] is None
        assert result["git_ref"] is None
        assert result["build_type"] is None
        assert result["build_date"] is None

    def test_branch_build_environment_variables(self) -> None:
        """Test that branch build info is correctly returned."""
        request = MagicMock()

        env_vars = {
            "SBOMIFY_GIT_COMMIT_SHORT": "def5678",
            "SBOMIFY_GIT_COMMIT": "def5678901234567890",
            "SBOMIFY_GIT_REF": "master",
            "SBOMIFY_BUILD_TYPE": "branch",
            "SBOMIFY_BUILD_DATE": "2024-01-15T10:30:00Z",
        }

        with (
            patch("sbomify.apps.core.context_processors.version") as mock_version,
            patch.dict(os.environ, env_vars, clear=False),
        ):
            mock_version.return_value = "1.2.3"
            result = version_context(request)

        assert result["git_commit"] == "def5678"
        assert result["git_ref"] == "master"
        assert result["build_type"] == "branch"


@pytest.mark.django_db
class TestPendingInvitationsContext:
    """Tests for the pending_invitations_context context processor."""

    def test_returns_empty_dict_for_unauthenticated_user(self) -> None:
        """Test that empty dict is returned for unauthenticated users."""
        request = MagicMock()
        request.user.is_authenticated = False

        result = pending_invitations_context(request)

        assert result == {}

    def test_returns_count_for_authenticated_user_with_no_invitations(
        self,
    ) -> None:
        """Test that zero count is returned when user has no invitations."""
        request = MagicMock()
        request.user.is_authenticated = True
        request.user.email = "test@example.com"

        result = pending_invitations_context(request)

        assert result["pending_invitations_count"] == 0
        assert result["has_pending_invitations"] is False
