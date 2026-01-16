"""Service helpers for product links HTMX views and redirects."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.http import HttpRequest

from sbomify.apps.core.apis import (
    create_product_link,
    delete_product_link,
    get_product,
    list_product_links,
    update_product_link,
)
from sbomify.apps.core.schemas import ProductLinkCreateSchema, ProductLinkUpdateSchema
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import ProductLink

# Link types mapping
LINK_TYPES = {
    "website": "Website",
    "support": "Support",
    "documentation": "Documentation",
    "repository": "Repository",
    "changelog": "Changelog",
    "release_notes": "Release Notes",
    "security": "Security",
    "issue_tracker": "Issue Tracker",
    "download": "Download",
    "chat": "Chat/Community",
    "social": "Social Media",
    "other": "Other",
}


def build_links_context(request: HttpRequest, product_id: str) -> ServiceResult[dict]:
    status_code, product = get_product(request, product_id)
    if status_code != 200:
        return ServiceResult.failure("Product not found", status_code=status_code)

    status_code, links_response = list_product_links(request, product_id, page=1, page_size=100)
    links = []
    if status_code == 200:
        links = links_response.get("items", [])

    has_crud_permissions = product.get("has_crud_permissions", False)

    return ServiceResult.success(
        {
            "product": product,
            "links": links,
            "link_types": LINK_TYPES,
            "has_crud_permissions": has_crud_permissions,
            "can_manage_links": has_crud_permissions,
        }
    )


def handle_links_action(request: HttpRequest, product_id: str) -> ServiceResult[None]:
    action = request.POST.get("action")

    if action == "create":
        link_type = request.POST.get("link_type", "").strip()
        title = request.POST.get("title", "").strip()
        url = request.POST.get("url", "").strip()
        description = request.POST.get("description", "").strip()

        if not link_type or not title or not url:
            return ServiceResult.failure("Link type, title, and URL are required")

        payload = ProductLinkCreateSchema(
            link_type=link_type,
            title=title,
            url=url,
            description=description,
        )
        status_code, result = create_product_link(request, product_id, payload)
        if status_code != 201:
            return ServiceResult.failure(result.get("detail", "Failed to create link"), status_code=status_code)

    elif action == "update":
        link_id = request.POST.get("link_id", "").strip()
        link_type = request.POST.get("link_type", "").strip()
        title = request.POST.get("title", "").strip()
        url = request.POST.get("url", "").strip()
        description = request.POST.get("description", "").strip()

        if not link_id or not link_type or not title or not url:
            return ServiceResult.failure("All required fields must be provided")

        payload = ProductLinkUpdateSchema(
            link_type=link_type,
            title=title,
            url=url,
            description=description,
        )
        status_code, result = update_product_link(request, product_id, link_id, payload)
        if status_code != 200:
            return ServiceResult.failure(result.get("detail", "Failed to update link"), status_code=status_code)

    elif action == "delete":
        link_id = request.POST.get("link_id", "").strip()
        if not link_id:
            return ServiceResult.failure("Link ID is required")

        status_code, result = delete_product_link(request, product_id, link_id)
        if status_code != 204:
            return ServiceResult.failure(result.get("detail", "Failed to delete link"), status_code=status_code)

    return ServiceResult.success()


def add_utm_params(url: str, campaign: str = "product_links") -> str:
    """Add UTM tracking parameters to an external URL.

    Internal or relative URLs (without a domain/netloc) are returned unchanged.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return url

        existing_params = parse_qs(parsed.query, keep_blank_values=True)
        utm_params = {
            "utm_source": "sbomify",
            "utm_medium": "trust_center",
            "utm_campaign": campaign,
        }

        for key, value in utm_params.items():
            if key not in existing_params:
                existing_params[key] = [value]

        new_query = urlencode(existing_params, doseq=True)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )
    except Exception:
        return url


def get_public_link_for_redirect(link_id: str) -> ServiceResult[ProductLink]:
    try:
        link = ProductLink.objects.select_related("product").get(id=link_id)
    except ProductLink.DoesNotExist:
        return ServiceResult.failure("Link not found", status_code=404)

    if not link.product.is_public:
        return ServiceResult.failure("Link not found", status_code=404)

    return ServiceResult.success(link)
