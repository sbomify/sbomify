"""
URL generation utilities for custom domain support.

These utilities help generate appropriate URLs based on whether the request
is on a custom domain or the main app domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team


def get_public_url_base(request: HttpRequest, team: Team | None = None) -> str:
    """
    Get the base URL for public pages.

    If the team has a custom domain, returns the custom domain URL.
    Otherwise returns the main app URL.

    Args:
        request: The current HTTP request
        team: The team/workspace (optional, will try to detect from request)

    Returns:
        Base URL (e.g., "https://trust.example.com" or "https://app.sbomify.com")
    """
    # Try to get team from request if not provided
    if team is None and hasattr(request, "custom_domain_team"):
        team = request.custom_domain_team

    # If team has a validated custom domain, use it
    if team and team.custom_domain and team.custom_domain_validated:
        protocol = "https" if request.is_secure() else "http"
        return f"{protocol}://{team.custom_domain}"

    # Otherwise use the main app URL
    return settings.APP_BASE_URL


def should_redirect_to_custom_domain(request: HttpRequest, team: Team) -> bool:
    """
    Check if the request should be redirected to the team's custom domain.

    Returns True if:
    - Team has a validated custom domain
    - Request is NOT already on that custom domain
    - Request is for a public page

    Args:
        request: The current HTTP request
        team: The team/workspace

    Returns:
        Boolean indicating if redirect is needed
    """
    # No redirect needed if team doesn't have a custom domain
    if not team or not team.custom_domain or not team.custom_domain_validated:
        return False

    # No redirect if already on the custom domain
    if hasattr(request, "is_custom_domain") and request.is_custom_domain:
        if hasattr(request, "custom_domain_team") and request.custom_domain_team == team:
            return False

    # Check if we're on the team's custom domain
    from sbomify.apps.teams.utils import normalize_host

    current_host = normalize_host(request.get_host())

    # If we're on the team's custom domain, no redirect needed
    if current_host == team.custom_domain:
        return False

    # If we're not on the custom domain and team has one, redirect
    # This covers requests from the main app domain or other domains
    return True


def build_custom_domain_url(team: Team, path: str, secure: bool = True) -> str:
    """
    Build a full URL using the team's custom domain.

    Args:
        team: The team/workspace
        path: The URL path (should start with /)
        secure: Use HTTPS (default True)

    Returns:
        Full URL with custom domain (e.g., "https://trust.example.com/product/123/")
    """
    if not team or not team.custom_domain:
        return ""

    protocol = "https" if secure else "http"
    # Ensure path starts with /
    if not path.startswith("/"):
        path = f"/{path}"

    return f"{protocol}://{team.custom_domain}{path}"


def get_public_path(resource_type: str, resource_id: str, is_custom_domain: bool = False, **kwargs) -> str:
    """
    Generate the URL path for a public resource.

    On custom domains, paths don't include /public/ prefix.
    On main app domain, paths include /public/ prefix.

    Args:
        resource_type: Type of resource (product, project, component, document, workspace, release)
        resource_id: ID of the resource
        is_custom_domain: Whether the URL is for a custom domain
        **kwargs: Additional parameters (e.g., product_id for release)

    Returns:
        URL path string
    """
    if resource_type == "workspace":
        if is_custom_domain:
            return "/"
        else:
            # Include workspace key if provided
            workspace_key = kwargs.get("workspace_key")
            if workspace_key:
                return f"/public/workspace/{workspace_key}/"
            return "/public/workspace/"

    elif resource_type == "product":
        if is_custom_domain:
            return f"/product/{resource_id}/"
        return f"/public/product/{resource_id}/"

    elif resource_type == "project":
        if is_custom_domain:
            return f"/project/{resource_id}/"
        return f"/public/project/{resource_id}/"

    elif resource_type == "component":
        detailed = kwargs.get("detailed", False)
        if is_custom_domain:
            path = f"/component/{resource_id}/"
            if detailed:
                path = f"/component/{resource_id}/detailed/"
        else:
            path = f"/public/component/{resource_id}/"
            if detailed:
                path = f"/public/component/{resource_id}/detailed/"
        return path

    elif resource_type == "document":
        if is_custom_domain:
            return f"/document/{resource_id}/"
        return f"/public/document/{resource_id}/"

    elif resource_type == "release":
        product_id = kwargs.get("product_id")
        if not product_id:
            raise ValueError("product_id is required for release URLs")

        if is_custom_domain:
            return f"/product/{product_id}/release/{resource_id}/"
        return f"/public/product/{product_id}/release/{resource_id}/"

    elif resource_type == "product_releases":
        if is_custom_domain:
            return f"/product/{resource_id}/releases/"
        return f"/public/product/{resource_id}/releases/"

    else:
        raise ValueError(f"Unknown resource type: {resource_type}")


def is_public_url_path(path: str) -> bool:
    """
    Check if a URL path is for a public resource.

    Args:
        path: The URL path

    Returns:
        Boolean indicating if this is a public URL
    """
    public_prefixes = [
        "/public/workspace/",
        "/public/product/",
        "/public/project/",
        "/public/component/",
        "/public/document/",
    ]

    return any(path.startswith(prefix) for prefix in public_prefixes)


def get_custom_domain_context(request: HttpRequest) -> tuple[bool, "Team | None"]:
    """
    Extract custom domain context from a request.

    Returns:
        Tuple of (is_custom_domain, team)
    """
    is_custom_domain = getattr(request, "is_custom_domain", False)
    team = getattr(request, "custom_domain_team", None) if is_custom_domain else None
    return is_custom_domain, team


def verify_custom_domain_ownership(
    request: HttpRequest,
    model_class: type[Model],
    resource_id: str,
    team_field: str = "team",
) -> HttpResponse | None:
    """
    Verify that a resource belongs to the custom domain's workspace.

    This function checks if we're on a custom domain and, if so, verifies
    that the requested resource belongs to that domain's workspace.

    Args:
        request: The HTTP request
        model_class: The Django model class to query
        resource_id: The ID of the resource to verify
        team_field: The field name that references the Team (default: "team")

    Returns:
        None if verification passes (or not on custom domain)
        HttpResponseNotFound if verification fails

    Example:
        error = verify_custom_domain_ownership(request, Product, product_id)
        if error:
            return error_response(request, error)
    """
    is_custom_domain = getattr(request, "is_custom_domain", False)
    if not is_custom_domain:
        return None

    custom_domain_team = getattr(request, "custom_domain_team", None)
    if not custom_domain_team:
        return None

    try:
        resource = model_class.objects.only("id", team_field).get(pk=resource_id)
        resource_team = getattr(resource, team_field, None)
        if resource_team != custom_domain_team:
            return HttpResponseNotFound("Not found")
    except model_class.DoesNotExist:
        return HttpResponseNotFound("Not found")

    return None


def add_custom_domain_to_context(
    request: HttpRequest,
    context: dict,
    team: "Team | None" = None,
) -> dict:
    """
    Add custom domain context variables to a template context dict.

    Args:
        request: The HTTP request
        context: The existing template context dict
        team: Optional team instance (if already fetched)

    Returns:
        Updated context dict with is_custom_domain and custom_domain keys
    """
    is_custom_domain = getattr(request, "is_custom_domain", False)

    context["is_custom_domain"] = is_custom_domain

    if is_custom_domain and team:
        context["custom_domain"] = getattr(team, "custom_domain", None)
    else:
        context["custom_domain"] = None

    return context
