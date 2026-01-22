"""Product identifiers management views."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.services.product_identifiers import build_identifiers_context, handle_identifiers_action
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ProductIdentifiersView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """View for product identifiers HTMX partial."""

    template_name = "core/components/product_identifiers_card.html.j2"

    def _get_context(self, request: HttpRequest, product_id: str) -> dict | None:
        """Get common context for rendering."""
        result = build_identifiers_context(request, product_id)
        if not result.ok:
            return None

        return result.value

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Render product identifiers card."""
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Handle identifier CRUD operations."""
        result = handle_identifiers_action(request, product_id)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to update identifiers")

        # Re-render the identifiers card
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        response = render(request, self.template_name, context)
        # Add HX-Trigger to close any open modals
        response["HX-Trigger"] = "closeModal"
        return response
