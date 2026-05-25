"""Unit tests for the GitHub REST resolver."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from sbomify.apps.oidc.github_api import GitHubResolveError, resolve_repository


def _mock_response(mocker: Any, *, status_code: int = 200, body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body if body is not None else {}
    resp.text = text
    mocker.patch("sbomify.apps.oidc.github_api.requests.get", return_value=resp)
    return resp


class TestSlugValidation:
    def test_empty_string_is_malformed(self) -> None:
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("")
        assert exc_info.value.kind == "malformed"

    @pytest.mark.parametrize(
        "bad",
        [
            "no-slash",
            "too/many/slashes",
            "spaces in/repo",
            "../../etc/passwd",  # path traversal attempt
            "trailing/",
            "/leading",
            "org/repo;rm -rf",
        ],
    )
    def test_malformed_slugs_rejected(self, bad: str) -> None:
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository(bad)
        assert exc_info.value.kind == "malformed"


class TestSuccess:
    def test_happy_path_returns_canonical_ids(self, mocker: Any) -> None:
        _mock_response(
            mocker,
            body={
                "id": 12345,
                "full_name": "octo-org/Example",  # GitHub returns canonical case
                "owner": {"id": 67890, "login": "octo-org"},
            },
        )

        result = resolve_repository("octo-org/example")
        assert result.repository_id == 12345
        assert result.repository_owner_id == 67890
        assert result.repository == "octo-org/Example"
        assert result.repository_owner == "octo-org"

    def test_resolves_via_repos_endpoint(self, mocker: Any) -> None:
        """Hits ``/repos/{owner}/{repo}`` with the expected headers."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": 1, "full_name": "a/b", "owner": {"id": 2, "login": "a"}}
        get_mock = mocker.patch("sbomify.apps.oidc.github_api.requests.get", return_value=resp)

        resolve_repository("a/b")

        get_mock.assert_called_once()
        call = get_mock.call_args
        assert call.args[0] == "https://api.github.com/repos/a/b"
        assert call.kwargs["headers"]["Accept"] == "application/vnd.github+json"
        assert call.kwargs["headers"]["X-GitHub-Api-Version"] == "2022-11-28"
        assert "User-Agent" in call.kwargs["headers"]


class TestFailureMapping:
    def test_404_maps_to_not_found(self, mocker: Any) -> None:
        _mock_response(mocker, status_code=404, body={"message": "Not Found"})
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("ghost/repo")
        assert exc_info.value.kind == "not_found"

    def test_403_with_rate_limit_text_maps_to_rate_limited(self, mocker: Any) -> None:
        _mock_response(
            mocker,
            status_code=403,
            body={"message": "API rate limit exceeded"},
            text="API rate limit exceeded for 1.2.3.4",
        )
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("octo/repo")
        assert exc_info.value.kind == "rate_limited"

    def test_500_maps_to_unavailable(self, mocker: Any) -> None:
        _mock_response(mocker, status_code=502, text="bad gateway")
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("octo/repo")
        assert exc_info.value.kind == "unavailable"

    def test_connection_error_maps_to_unavailable(self, mocker: Any) -> None:
        mocker.patch(
            "sbomify.apps.oidc.github_api.requests.get",
            side_effect=requests.exceptions.ConnectionError("dns boom"),
        )
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("octo/repo")
        assert exc_info.value.kind == "unavailable"

    def test_malformed_json_maps_to_unavailable(self, mocker: Any) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not JSON")
        mocker.patch("sbomify.apps.oidc.github_api.requests.get", return_value=resp)
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("octo/repo")
        assert exc_info.value.kind == "unavailable"

    def test_missing_id_field_maps_to_unavailable(self, mocker: Any) -> None:
        """A 200 response that's missing 'id' or 'owner.id' shouldn't crash."""
        _mock_response(mocker, body={"full_name": "a/b"})  # no id, no owner
        with pytest.raises(GitHubResolveError) as exc_info:
            resolve_repository("a/b")
        assert exc_info.value.kind == "unavailable"
