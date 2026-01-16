"""Product links management views."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.services.product_links import (
    add_utm_params,
    build_links_context,
    get_public_link_for_redirect,
    handle_links_action,
)


class ProductLinksView(LoginRequiredMixin, View):
    """View for product links HTMX partial."""

    template_name = "core/components/product_links_card.html.j2"

    def _get_context(self, request: HttpRequest, product_id: str) -> dict | None:
        """Get common context for rendering."""
        result = build_links_context(request, product_id)
        if not result.ok:
            return None

        return result.value

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Render product links card."""
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Handle link CRUD operations."""
        result = handle_links_action(request, product_id)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to update link")

        # Re-render the links card
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        response = render(request, self.template_name, context)
        response["HX-Trigger"] = "closeModal"
        return response


class ProductLinkRedirectView(View):
    """Public redirect view for product links.

    This view handles redirects for product links on public pages,
    enabling future click tracking while hiding the actual URL.
    """

    def get(self, request: HttpRequest, link_id: str) -> HttpResponse:
        """Redirect to the external URL with UTM parameters."""
        result = get_public_link_for_redirect(link_id)
        if not result.ok or result.value is None:
            raise Http404("Link not found")

        link = result.value

        # Add UTM parameters and redirect
        redirect_url = add_utm_params(link.url, campaign="product_links")
        return HttpResponseRedirect(redirect_url)
