"""
TEA (Transparency Exchange API) utility functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import HttpRequest

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team


def get_workspace_from_request(
    request: HttpRequest, workspace_key: str | None = None, check_tea_enabled: bool = True
) -> "Team | None":
    """
    Resolve workspace from request for TEA API access.

    Resolution order:
    1. Custom domain: request.custom_domain_team (via middleware)
    2. URL path parameter: workspace_key lookup

    Args:
        request: The HTTP request
        workspace_key: Optional workspace key from URL path
        check_tea_enabled: Whether to check if TEA is enabled (default: True)

    Returns:
        Team instance or None if not found or TEA not enabled
    """
    from sbomify.apps.teams.models import Team

    team = None

    # Check custom domain first
    if getattr(request, "is_custom_domain", False):
        team = getattr(request, "custom_domain_team", None)

    # Fall back to workspace_key from URL
    if not team and workspace_key:
        try:
            team = Team.objects.get(key=workspace_key, is_public=True)
        except Team.DoesNotExist:
            return None

    # Check if TEA is enabled for this workspace
    if team and check_tea_enabled and not team.tea_enabled:
        return None

    return team


def get_artifact_mime_type(sbom_format: str) -> str:
    """
    Get MIME type for SBOM format.

    Args:
        sbom_format: SBOM format string (e.g., 'cyclonedx', 'spdx')

    Returns:
        MIME type string
    """
    mime_types = {
        "cyclonedx": "application/vnd.cyclonedx+json",
        "spdx": "application/spdx+json",
    }
    return mime_types.get(sbom_format.lower(), "application/json")
