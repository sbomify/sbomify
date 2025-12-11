"""
Template tags for generating public URLs with custom domain support.

These tags check if the current request is on a custom domain and generate
appropriate URLs accordingly. On custom domains, slug-based URLs are used.
"""

from django import template
from django.urls import reverse

from sbomify.apps.core.url_utils import get_public_path

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
        "core:component_detailed_public": "component_detailed",
        "core_custom_domain:component_detailed_public": "component_detailed",
        "core:product_releases_public": "product_releases",
        "core_custom_domain:product_releases_public": "product_releases",
        "core:release_details_public": "release",
        "core_custom_domain:release_details_public": "release",
        "documents:document_details_public": "document",
        "core_custom_domain:document_details_public": "document",
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
        elif resource_type == "component_detailed":
            component_id = kwargs.get("component_id")
            component_slug = kwargs.get("component_slug") or slug
            if component_id or component_slug:
                return get_public_path(
                    "component",
                    component_id or "",
                    is_custom_domain=True,
                    slug=component_slug or component_id,
                    detailed=True,
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
    except Exception:
        # If reverse fails, return empty string
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
