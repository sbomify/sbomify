"""Thin GitHub REST API helper for OIDC binding setup.

Resolves a user-supplied ``"org/repo"`` to the immutable
``(repository_owner_id, repository_id)`` pair we pin on the
``OIDCBinding`` to defeat account-resurrection attacks.

Authentication
--------------

Public repository metadata is readable without any auth token, so v1
calls ``GET /repos/{owner}/{repo}`` unauthenticated. The 60 req/hour
unauthenticated rate limit is fine for binding-create traffic (one
call per binding, almost never repeated).

If a workspace owner needs to bind a PRIVATE repository, they'd hit
``404 Not Found`` from this endpoint — a future iteration can let
them paste a fine-grained PAT scoped to ``Repository → Metadata: Read``
and we'd forward it as a Bearer token. Out of scope for v1.

Error model
-----------

The single typed error ``GitHubResolveError`` carries an explicit
``kind`` field so the API layer maps cleanly to user-facing
responses:

* ``"not_found"`` — repo doesn't exist OR is private and unauthenticated
* ``"rate_limited"`` — GitHub rate limit hit (60/h unauthenticated)
* ``"unavailable"`` — network failure / GitHub 5xx
* ``"malformed"`` — caller passed something that isn't ``"org/repo"``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import requests
from django.conf import settings

from sbomify.logging import getLogger

logger = getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_FETCH_TIMEOUT_SECONDS = 5

# Public — re-used by ``forms.OIDCBindingForm.clean_repository`` so the
# form and this resolver agree on what counts as a parseable slug.
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
REPO_SLUG_HELP_TEXT = "Repository must be in the form 'org/repo' (letters, digits, '.', '_', '-' only)."

GitHubResolveErrorKind = Literal["not_found", "rate_limited", "unavailable", "malformed"]


class GitHubResolveError(Exception):
    """Raised when ``resolve_repository`` cannot resolve to numeric IDs."""

    def __init__(self, kind: GitHubResolveErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: GitHubResolveErrorKind = kind


@dataclass(frozen=True)
class ResolvedRepository:
    """Result of a successful ``resolve_repository`` call."""

    repository: str  # canonical "org/repo" as GitHub returns it (case-corrected)
    repository_owner: str  # canonical owner login
    repository_id: int
    repository_owner_id: int


def resolve_repository(repo_slug: str) -> ResolvedRepository:
    """Resolve ``"org/repo"`` → immutable IDs via the GitHub REST API.

    Returns the canonical-cased name (GitHub normalises case in
    responses) and the immutable numeric IDs the OIDC binding will
    pin. Raises ``GitHubResolveError`` for any failure.

    The caller is expected to be a workspace admin in a binding-create
    flow, so failures bubble up to a form-validation error rather
    than a silent skip.
    """
    if not REPO_PATTERN.fullmatch(repo_slug or ""):
        raise GitHubResolveError("malformed", REPO_SLUG_HELP_TEXT)

    url = f"{_GITHUB_API_BASE}/repos/{repo_slug}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": getattr(settings, "GITHUB_USER_AGENT", "sbomify"),
    }
    try:
        response = requests.get(url, headers=headers, timeout=_FETCH_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.info("GitHub repo lookup failed (%s): %s", url, exc)
        raise GitHubResolveError("unavailable", str(exc)) from exc

    if response.status_code == 404:
        raise GitHubResolveError(
            "not_found",
            f"Repository '{repo_slug}' was not found. If it is private, "
            "sbomify can't read its metadata without a PAT (not yet supported "
            "for OIDC binding setup).",
        )
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise GitHubResolveError(
            "rate_limited",
            "GitHub API rate limit exceeded. Try again in a few minutes.",
        )
    if response.status_code >= 500:
        raise GitHubResolveError(
            "unavailable",
            f"GitHub API returned {response.status_code}",
        )
    if response.status_code != 200:
        raise GitHubResolveError(
            "unavailable",
            f"Unexpected status {response.status_code} from GitHub API",
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise GitHubResolveError("unavailable", "GitHub API returned non-JSON") from exc

    try:
        return ResolvedRepository(
            repository=body["full_name"],
            repository_owner=body["owner"]["login"],
            repository_id=int(body["id"]),
            repository_owner_id=int(body["owner"]["id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubResolveError(
            "unavailable",
            "GitHub API response missing expected fields",
        ) from exc
