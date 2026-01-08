"""Product links management views."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import (
    create_product_link,
    delete_product_link,
    get_product,
    list_product_links,
    update_product_link,
)
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.schemas import ProductLinkCreateSchema, ProductLinkUpdateSchema

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


class ProductLinksView(LoginRequiredMixin, View):
    """View for product links HTMX partial."""

    template_name = "core/components/product_links_card.html.j2"

    def _get_context(self, request: HttpRequest, product_id: str) -> dict | None:
        """Get common context for rendering."""
        status_code, product = get_product(request, product_id)
        if status_code != 200:
            return None

        status_code, links_response = list_product_links(request, product_id, page=1, page_size=100)
        links = []
        if status_code == 200:
            links = links_response.get("items", [])

        has_crud_permissions = product.get("has_crud_permissions", False)

        return {
            "product": product,
            "links": links,
            "link_types": LINK_TYPES,
            "has_crud_permissions": has_crud_permissions,
            "can_manage_links": has_crud_permissions,
        }

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Render product links card."""
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Handle link CRUD operations."""
        action = request.POST.get("action")

        if action == "create":
            link_type = request.POST.get("link_type", "").strip()
            title = request.POST.get("title", "").strip()
            url = request.POST.get("url", "").strip()
            description = request.POST.get("description", "").strip()

            if not link_type or not title or not url:
                return htmx_error_response("Link type, title, and URL are required")

            payload = ProductLinkCreateSchema(
                link_type=link_type,
                title=title,
                url=url,
                description=description,
            )
            status_code, result = create_product_link(request, product_id, payload)

            if status_code != 201:
                return htmx_error_response(result.get("detail", "Failed to create link"))

        elif action == "update":
            link_id = request.POST.get("link_id", "").strip()
            link_type = request.POST.get("link_type", "").strip()
            title = request.POST.get("title", "").strip()
            url = request.POST.get("url", "").strip()
            description = request.POST.get("description", "").strip()

            if not link_id or not link_type or not title or not url:
                return htmx_error_response("All required fields must be provided")

            payload = ProductLinkUpdateSchema(
                link_type=link_type,
                title=title,
                url=url,
                description=description,
            )
            status_code, result = update_product_link(request, product_id, link_id, payload)

            if status_code != 200:
                return htmx_error_response(result.get("detail", "Failed to update link"))

        elif action == "delete":
            link_id = request.POST.get("link_id", "").strip()
            if not link_id:
                return htmx_error_response("Link ID is required")

            status_code, result = delete_product_link(request, product_id, link_id)
            if status_code != 204:
                return htmx_error_response(result.get("detail", "Failed to delete link"))

        # Re-render the links card
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        response = render(request, self.template_name, context)
        response["HX-Trigger"] = "closeModal"
        return response
