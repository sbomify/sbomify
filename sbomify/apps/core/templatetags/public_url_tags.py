"""
Template tags for generating public URLs with custom domain support.

These tags check if the current request is on a custom domain and generate
appropriate URLs accordingly.
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
        {% public_url 'product_details_public' product_id=product.id %}
        {% public_url 'workspace_public' workspace_key=workspace.key %}

    On custom domains, returns clean URLs without /public/ prefix.
    On main app domain, returns standard /public/* URLs.
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

    # If on custom domain, use custom URL generation
    if is_custom_domain:
        resource_type = url_name_to_resource.get(url_name)

        if resource_type == "workspace":
            return "/"
        elif resource_type == "product":
            product_id = kwargs.get("product_id")
            if product_id:
                return get_public_path("product", product_id, is_custom_domain=True)
        elif resource_type == "project":
            project_id = kwargs.get("project_id")
            if project_id:
                return get_public_path("project", project_id, is_custom_domain=True)
        elif resource_type == "component":
            component_id = kwargs.get("component_id")
            if component_id:
                return get_public_path("component", component_id, is_custom_domain=True)
        elif resource_type == "component_detailed":
            component_id = kwargs.get("component_id")
            if component_id:
                return get_public_path("component", component_id, is_custom_domain=True, detailed=True)
        elif resource_type == "product_releases":
            product_id = kwargs.get("product_id")
            if product_id:
                return get_public_path("product_releases", product_id, is_custom_domain=True)
        elif resource_type == "release":
            release_id = kwargs.get("release_id")
            product_id = kwargs.get("product_id")
            if release_id and product_id:
                return get_public_path("release", release_id, is_custom_domain=True, product_id=product_id)
        elif resource_type == "document":
            document_id = kwargs.get("document_id")
            if document_id:
                return get_public_path("document", document_id, is_custom_domain=True)

    # Fall back to standard Django URL resolution
    try:
        return reverse(url_name, args=args, kwargs=kwargs)
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
