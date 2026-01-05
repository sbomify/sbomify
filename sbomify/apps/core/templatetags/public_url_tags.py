"""
Template tags for generating public URLs with custom domain support.

These tags check if the current request is on a custom domain and generate
appropriate URLs accordingly. On custom domains, slug-based URLs are used.
"""

import logging

from django import template
from django.urls import NoReverseMatch, reverse

from sbomify.apps.core.url_utils import get_public_path

logger = logging.getLogger(__name__)

register = template.Library()


@register.simple_tag(takes_context=True)
def public_url(context, url_name, *args, **kwargs):
    """
    Generate a public URL with custom domain support.

    Usage in templates:
        {% public_url 'product_details_public' product_id=product.id slug=product.slug %}
        {% public_url 'workspace_public' workspace_key=workspace.key %}

    On custom domains, returns slug-based URLs without /public/ prefix.
    On main app domain, returns standard /public/* URLs with IDs.

    Note: Pass both id and slug when available. On custom domains, slug is used.
    On main app domain, id is used.
    """
    request = context.get("request")
    is_custom_domain = getattr(request, "is_custom_domain", False) if request else False

    # Map URL names to resource types for custom domain URL generation
    url_name_to_resource = {
        "core:workspace_public": "workspace",
        "core_custom_domain:workspace_public": "workspace",
        "core:product_details_public": "product",
        "core_custom_domain:product_details_public": "product",
        "core:project_details_public": "project",
        "core_custom_domain:project_details_public": "project",
        "core:component_details_public": "component",
        "core_custom_domain:component_details_public": "component",
        "core:product_releases_public": "product_releases",
        "core_custom_domain:product_releases_public": "product_releases",
        "core:release_details_public": "release",
        "core_custom_domain:release_details_public": "release",
    }

    # If on custom domain, use custom URL generation with slugs
    if is_custom_domain:
        resource_type = url_name_to_resource.get(url_name)
        # Get slug from kwargs, fall back to id if not provided
        slug = kwargs.get("slug")

        if resource_type == "workspace":
            return "/"
        elif resource_type == "product":
            product_id = kwargs.get("product_id")
            product_slug = kwargs.get("product_slug") or slug
            if product_id or product_slug:
                return get_public_path(
                    "product", product_id or "", is_custom_domain=True, slug=product_slug or product_id
                )
        elif resource_type == "project":
            project_id = kwargs.get("project_id")
            project_slug = kwargs.get("project_slug") or slug
            if project_id or project_slug:
                return get_public_path(
                    "project", project_id or "", is_custom_domain=True, slug=project_slug or project_id
                )
        elif resource_type == "component":
            component_id = kwargs.get("component_id")
            component_slug = kwargs.get("component_slug") or slug
            if component_id or component_slug:
                return get_public_path(
                    "component", component_id or "", is_custom_domain=True, slug=component_slug or component_id
                )
        elif resource_type == "product_releases":
            product_id = kwargs.get("product_id")
            product_slug = kwargs.get("product_slug") or slug
            if product_id or product_slug:
                return get_public_path(
                    "product_releases", product_id or "", is_custom_domain=True, slug=product_slug or product_id
                )
        elif resource_type == "release":
            release_id = kwargs.get("release_id")
            release_slug = kwargs.get("release_slug")
            product_id = kwargs.get("product_id")
            product_slug = kwargs.get("product_slug")
            if (release_id or release_slug) and (product_id or product_slug):
                return get_public_path(
                    "release",
                    release_id or "",
                    is_custom_domain=True,
                    product_id=product_id or "",
                    product_slug=product_slug or product_id,
                    release_slug=release_slug or release_id,
                )
        elif resource_type == "document":
            document_id = kwargs.get("document_id")
            document_slug = kwargs.get("document_slug") or slug
            if document_id or document_slug:
                return get_public_path(
                    "document", document_id or "", is_custom_domain=True, slug=document_slug or document_id
                )

    # Fall back to standard Django URL resolution (uses IDs)
    # Remove slug-related kwargs before passing to reverse
    reverse_kwargs = {k: v for k, v in kwargs.items() if not k.endswith("_slug") and k != "slug"}
    try:
        return reverse(url_name, args=args, kwargs=reverse_kwargs)
    except NoReverseMatch:
        logger.warning("Failed to reverse URL '%s' with args=%s kwargs=%s", url_name, args, reverse_kwargs)
        return ""


@register.simple_tag(takes_context=True)
def is_on_custom_domain(context):
    """
    Check if the current request is on a custom domain.

    Usage in templates:
        {% is_on_custom_domain as on_custom_domain %}
        {% if on_custom_domain %}
            ... custom domain specific content ...
        {% endif %}
    """
    request = context.get("request")
    return getattr(request, "is_custom_domain", False) if request else False


@register.simple_tag(takes_context=True)
def get_custom_domain(context):
    """
    Get the custom domain for the current request.

    Returns the custom domain hostname or None if not on a custom domain.

    Usage in templates:
        {% get_custom_domain as domain %}
        {% if domain %}
            Current domain: {{ domain }}
        {% endif %}
    """
    request = context.get("request")
    if request and getattr(request, "is_custom_domain", False):
        if hasattr(request, "custom_domain_team"):
            team = request.custom_domain_team
            if team:
                return getattr(team, "custom_domain", None)
    return None


@register.simple_tag(takes_context=True)
def workspace_public_url(context):
    """
    Generate the workspace (trust center) root URL.

    On custom domains, returns "/" (the root).
    On main app domain, returns "/public/workspace/{key}/".

    Returns empty string if no valid workspace can be determined.

    Usage in templates:
        {% workspace_public_url as trust_center_url %}
        <a href="{{ trust_center_url }}">Trust Center</a>
    """
    request = context.get("request")
    if not request:
        return ""

    is_custom_domain = getattr(request, "is_custom_domain", False)

    # On custom domains, the root is always the workspace
    if is_custom_domain:
        return "/"

    # On main app domain, we need to find the workspace key
    # First check the brand context (set by build_branding_context)
    brand = context.get("brand")
    if brand and isinstance(brand, dict) and brand.get("workspace_key"):
        try:
            return reverse("core:workspace_public", kwargs={"workspace_key": brand["workspace_key"]})
        except NoReverseMatch:
            pass

    # Check for workspace context variable (used by workspace_public view)
    workspace = context.get("workspace")
    if workspace and isinstance(workspace, dict) and workspace.get("key"):
        try:
            return reverse("core:workspace_public", kwargs={"workspace_key": workspace["key"]})
        except NoReverseMatch:
            pass

    # Fallback: return empty string (logo won't be clickable)
    return ""


@register.simple_tag(takes_context=True)
def trust_center_absolute_url(context, team=None):
    """
    Generate the full absolute URL for a workspace's Trust Center.

    This is used for "Copy Public URL" functionality where we need the complete
    URL including protocol and domain.

    If the team has a validated custom domain, returns https://{custom_domain}/
    Otherwise, returns {APP_BASE_URL}/public/workspace/{key}

    Usage in templates:
        {% trust_center_absolute_url team as public_url %}
        <button data-public-url="{{ public_url }}">Copy URL</button>

    Args:
        team: Team object or dict with custom_domain, custom_domain_validated, and key
    """
    from django.conf import settings

    if not team:
        # Try to get team from context
        team = context.get("team")

    if not team:
        return ""

    # Handle both dict and object access
    if isinstance(team, dict):
        custom_domain = team.get("custom_domain")
        custom_domain_validated = team.get("custom_domain_validated", False)
        team_key = team.get("key")
    else:
        custom_domain = getattr(team, "custom_domain", None)
        custom_domain_validated = getattr(team, "custom_domain_validated", False)
        team_key = getattr(team, "key", None)

    # If custom domain is set and validated, use it
    if custom_domain and custom_domain_validated:
        return f"https://{custom_domain}"

    # Fallback to standard URL
    if team_key:
        base_url = getattr(settings, "APP_BASE_URL", "")
        return f"{base_url}/public/workspace/{team_key}"

    return ""


@register.simple_tag(takes_context=True)
def resource_public_absolute_url(context, resource_type, resource, team=None):
    """
    Generate the full absolute URL for a public resource (product, project, component).

    This is used for "Copy Public URL" functionality on resource detail pages.
    Considers custom domains when available.

    If the team has a validated custom domain, returns https://{custom_domain}/{type}/{slug}/
    Otherwise, returns {APP_BASE_URL}/public/workspace/{key}/{type}/{id}

    Usage in templates:
        {% resource_public_absolute_url 'product' product team as public_url %}
        {% resource_public_absolute_url 'component' component as public_url %}

    Args:
        resource_type: One of 'product', 'project', 'component'
        resource: The resource object with id, slug, and team attributes
        team: Optional team object (will be fetched from resource if not provided)
    """
    from django.conf import settings

    if not resource:
        return ""

    # Get team from resource if not provided
    if not team:
        team = getattr(resource, "team", None)

    if not team:
        return ""

    # Get resource identifiers
    resource_id = getattr(resource, "id", None)
    resource_slug = getattr(resource, "slug", None)

    if not resource_id:
        return ""

    # Get team properties
    custom_domain = getattr(team, "custom_domain", None)
    custom_domain_validated = getattr(team, "custom_domain_validated", False)
    team_key = getattr(team, "key", None)

    # If custom domain is set and validated, use slug-based URL
    if custom_domain and custom_domain_validated:
        # Custom domains require slugs for proper routing
        if resource_slug:
            return f"https://{custom_domain}/{resource_type}/{resource_slug}/"
        # Fall through to standard URL if no slug available

    # Fallback to standard URL with ID
    if team_key:
        base_url = getattr(settings, "APP_BASE_URL", "")
        return f"{base_url}/public/workspace/{team_key}/{resource_type}/{resource_id}"

    return ""
