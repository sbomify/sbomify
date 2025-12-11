"""
URL generation utilities for custom domain support.

These utilities help generate appropriate URLs based on whether the request
is on a custom domain or the main app domain, and resolve resources by slug
on custom domains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.utils.text import slugify

if TYPE_CHECKING:
    from sbomify.apps.core.models import Component, Product, Project, Release
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

    On custom domains, paths use slugs and don't include /public/ prefix.
    On main app domain, paths use IDs and include /public/ prefix.

    Args:
        resource_type: Type of resource (product, project, component, document, workspace, release)
        resource_id: ID of the resource (used for main app domain)
        is_custom_domain: Whether the URL is for a custom domain
        **kwargs: Additional parameters:
            - slug: The slug to use for custom domain URLs
            - product_id: Required for release URLs (ID on main app)
            - product_slug: Product slug for release URLs on custom domains
            - workspace_key: Workspace key for workspace URLs
            - detailed: Boolean for detailed component view

    Returns:
        URL path string
    """
    # Get slug from kwargs, fall back to resource_id if not provided
    slug = kwargs.get("slug", resource_id)

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
            return f"/product/{slug}/"
        return f"/public/product/{resource_id}/"

    elif resource_type == "project":
        if is_custom_domain:
            return f"/project/{slug}/"
        return f"/public/project/{resource_id}/"

    elif resource_type == "component":
        detailed = kwargs.get("detailed", False)
        if is_custom_domain:
            path = f"/component/{slug}/"
            if detailed:
                path = f"/component/{slug}/detailed/"
        else:
            path = f"/public/component/{resource_id}/"
            if detailed:
                path = f"/public/component/{resource_id}/detailed/"
        return path

    elif resource_type == "document":
        if is_custom_domain:
            return f"/document/{slug}/"
        return f"/public/document/{resource_id}/"

    elif resource_type == "release":
        product_id = kwargs.get("product_id")
        product_slug = kwargs.get("product_slug", product_id)
        release_slug = kwargs.get("release_slug", slug)

        if not product_id and not product_slug:
            raise ValueError("product_id or product_slug is required for release URLs")

        if is_custom_domain:
            return f"/product/{product_slug}/release/{release_slug}/"
        return f"/public/product/{product_id}/release/{resource_id}/"

    elif resource_type == "product_releases":
        if is_custom_domain:
            return f"/product/{slug}/releases/"
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


def resolve_product_identifier(
    request: HttpRequest,
    identifier: str,
) -> "Product | None":
    """
    Resolve a product by identifier (slug on custom domains, ID otherwise).

    On custom domains, the identifier is treated as a slug and looked up
    within the custom domain's team. On the main app domain, the identifier
    is treated as a product ID.

    Args:
        request: The HTTP request
        identifier: The product identifier (slug or ID)

    Returns:
        Product instance or None if not found
    """
    from sbomify.apps.core.models import Product

    is_custom_domain = getattr(request, "is_custom_domain", False)
    custom_domain_team = getattr(request, "custom_domain_team", None)

    if is_custom_domain and custom_domain_team:
        # On custom domain: find by slug within the team
        # Slugify the identifier to normalize it
        slug = slugify(identifier, allow_unicode=True)

        # NOTE: This is O(n) where n = number of public products per team.
        # For teams with many products, consider adding a database slug field with an index.
        # Current approach is acceptable for typical team sizes (< 100 products).
        for product in Product.objects.filter(team=custom_domain_team, is_public=True):
            if slugify(product.name, allow_unicode=True) == slug:
                return product

        # Fallback: try by ID within the team (for backward compatibility)
        try:
            return Product.objects.get(pk=identifier, team=custom_domain_team)
        except Product.DoesNotExist:
            pass

        return None
    else:
        # On main app: find by ID only
        try:
            return Product.objects.get(pk=identifier)
        except Product.DoesNotExist:
            return None


def resolve_project_identifier(
    request: HttpRequest,
    identifier: str,
) -> "Project | None":
    """
    Resolve a project by identifier (slug on custom domains, ID otherwise).

    On custom domains, the identifier is treated as a slug and looked up
    within the custom domain's team. On the main app domain, the identifier
    is treated as a project ID.

    Args:
        request: The HTTP request
        identifier: The project identifier (slug or ID)

    Returns:
        Project instance or None if not found
    """
    from sbomify.apps.core.models import Project

    is_custom_domain = getattr(request, "is_custom_domain", False)
    custom_domain_team = getattr(request, "custom_domain_team", None)

    if is_custom_domain and custom_domain_team:
        # On custom domain: find by slug within the team
        slug = slugify(identifier, allow_unicode=True)

        # NOTE: O(n) scan - see resolve_product_identifier for rationale
        for project in Project.objects.filter(team=custom_domain_team, is_public=True):
            if slugify(project.name, allow_unicode=True) == slug:
                return project

        # Fallback: try by ID within the team
        try:
            return Project.objects.get(pk=identifier, team=custom_domain_team)
        except Project.DoesNotExist:
            pass

        return None
    else:
        # On main app: find by ID only
        try:
            return Project.objects.get(pk=identifier)
        except Project.DoesNotExist:
            return None


def resolve_component_identifier(
    request: HttpRequest,
    identifier: str,
) -> "Component | None":
    """
    Resolve a component by identifier (slug on custom domains, ID otherwise).

    On custom domains, the identifier is treated as a slug and looked up
    within the custom domain's team. On the main app domain, the identifier
    is treated as a component ID.

    Args:
        request: The HTTP request
        identifier: The component identifier (slug or ID)

    Returns:
        Component instance or None if not found
    """
    from sbomify.apps.core.models import Component

    is_custom_domain = getattr(request, "is_custom_domain", False)
    custom_domain_team = getattr(request, "custom_domain_team", None)

    if is_custom_domain and custom_domain_team:
        # On custom domain: find by slug within the team
        slug = slugify(identifier, allow_unicode=True)

        # NOTE: O(n) scan - see resolve_product_identifier for rationale
        for component in Component.objects.filter(team=custom_domain_team, is_public=True):
            if slugify(component.name, allow_unicode=True) == slug:
                return component

        # Fallback: try by ID within the team
        try:
            return Component.objects.get(pk=identifier, team=custom_domain_team)
        except Component.DoesNotExist:
            pass

        return None
    else:
        # On main app: find by ID only
        try:
            return Component.objects.get(pk=identifier)
        except Component.DoesNotExist:
            return None


def resolve_release_identifier(
    request: HttpRequest,
    product: "Product",
    identifier: str,
) -> "Release | None":
    """
    Resolve a release by identifier (slug on custom domains, ID otherwise).

    On custom domains, the identifier is treated as a slug and looked up
    within the product's releases. On the main app domain, the identifier
    is treated as a release ID and validated to belong to the given product.

    Args:
        request: The HTTP request
        product: The product the release belongs to
        identifier: The release identifier (slug or ID)

    Returns:
        Release instance or None if not found
    """
    from sbomify.apps.core.models import Release

    is_custom_domain = getattr(request, "is_custom_domain", False)

    if is_custom_domain:
        # On custom domain: find by slug within the product's releases
        slug = slugify(identifier, allow_unicode=True)

        # NOTE: O(n) scan - see resolve_product_identifier for rationale
        for release in Release.objects.filter(product=product):
            if slugify(release.name, allow_unicode=True) == slug:
                return release

        # Fallback: try by ID within the product
        try:
            return Release.objects.get(pk=identifier, product=product)
        except Release.DoesNotExist:
            pass

        return None
    else:
        # On main app: find by ID and validate it belongs to the product
        try:
            return Release.objects.get(pk=identifier, product=product)
        except Release.DoesNotExist:
            return None


def resolve_document_identifier(
    request: HttpRequest,
    identifier: str,
) -> "Model | None":
    """
    Resolve a document by identifier (slug on custom domains, ID otherwise).

    On custom domains, the identifier is treated as a slug and looked up
    within the custom domain's team's components. On the main app domain,
    the identifier is treated as a document ID.

    Args:
        request: The HTTP request
        identifier: The document identifier (slug or ID)

    Returns:
        Document instance or None if not found
    """
    from sbomify.apps.documents.models import Document

    is_custom_domain = getattr(request, "is_custom_domain", False)
    custom_domain_team = getattr(request, "custom_domain_team", None)

    if is_custom_domain and custom_domain_team:
        # On custom domain: find by slug within the team's public components
        slug = slugify(identifier, allow_unicode=True)

        # NOTE: O(n) scan - see resolve_product_identifier for rationale
        for document in Document.objects.filter(component__team=custom_domain_team, component__is_public=True):
            if slugify(document.name, allow_unicode=True) == slug:
                return document

        # Fallback: try by ID within the team
        try:
            return Document.objects.get(pk=identifier, component__team=custom_domain_team)
        except Document.DoesNotExist:
            pass

        return None
    else:
        # On main app: find by ID only
        try:
            return Document.objects.get(pk=identifier)
        except Document.DoesNotExist:
            return None
