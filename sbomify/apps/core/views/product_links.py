"""Product links management views."""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
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


def add_utm_params(url: str, campaign: str = "product_links") -> str:
    """Add UTM tracking parameters to a URL."""
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Only add UTM params to external URLs (those with a netloc/domain)
        if not parsed.netloc:
            return url

        # Parse existing query parameters
        existing_params = parse_qs(parsed.query, keep_blank_values=True)

        # Add UTM parameters (don't overwrite if they exist)
        utm_params = {
            "utm_source": "sbomify",
            "utm_medium": "trust_center",
            "utm_campaign": campaign,
        }

        for key, value in utm_params.items():
            if key not in existing_params:
                existing_params[key] = [value]

        # Encode parameters, preserving multi-valued query parameters.
        # parse_qs returns all values as lists, and doseq=True handles this correctly.
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


class ProductLinkRedirectView(View):
    """Public redirect view for product links.

    This view handles redirects for product links on public pages,
    enabling future click tracking while hiding the actual URL.
    """

    def get(self, request: HttpRequest, link_id: str) -> HttpResponse:
        """Redirect to the external URL with UTM parameters."""
        try:
            link = ProductLink.objects.select_related("product").get(id=link_id)
        except ProductLink.DoesNotExist:
            raise Http404("Link not found")

        # Only allow redirects for public products
        if not link.product.is_public:
            raise Http404("Link not found")

        # Add UTM parameters and redirect
        redirect_url = add_utm_params(link.url, campaign="product_links")
        return HttpResponseRedirect(redirect_url)
