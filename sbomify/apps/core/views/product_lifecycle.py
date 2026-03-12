"""Product lifecycle management views."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.models import Product
from sbomify.apps.core.services.cle import create_cle_event
from sbomify.apps.core.utils import verify_item_access


class ProductLifecycleView(LoginRequiredMixin, View):
    """View for product lifecycle HTMX partial."""

    template_name = "core/components/product_lifecycle_card.html.j2"

    def _get_product(self, request: HttpRequest, product_id: str) -> Product | None:
        """Get product if user has access."""
        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return None

        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return None

        return product

    def _get_context(self, request: HttpRequest, product: Product) -> dict[str, Any]:
        """Get context for rendering."""
        can_edit = verify_item_access(request, product, ["owner", "admin"])
        return {
            "product": product,
            "can_edit": can_edit,
        }

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Render product lifecycle card."""
        product = self._get_product(request, product_id)
        if product is None:
            return htmx_error_response("Product not found")

        context = self._get_context(request, product)
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Handle lifecycle update."""
        product = self._get_product(request, product_id)
        if product is None:
            return htmx_error_response("Product not found")

        # Check edit permissions
        if not verify_item_access(request, product, ["owner", "admin"]):
            return htmx_error_response("Permission denied")

        # Parse dates from form
        def parse_datetime(value: str, field_name: str) -> datetime | None | str:
            """Parse date string to timezone-aware datetime, None for empty, or error string."""
            if not value or value.strip() == "":
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return f"Invalid date format for {field_name}"

        release_date = parse_datetime(request.POST.get("release_date", ""), "release date")
        if isinstance(release_date, str):
            return htmx_error_response(release_date)
        end_of_support = parse_datetime(request.POST.get("end_of_support", ""), "end of support")
        if isinstance(end_of_support, str):
            return htmx_error_response(end_of_support)
        end_of_life = parse_datetime(request.POST.get("end_of_life", ""), "end of life")
        if isinstance(end_of_life, str):
            return htmx_error_response(end_of_life)

        # Create CLE events for changed dates (events recompute cached fields)
        if release_date and (product.release_date is None or release_date.date() != product.release_date):
            result = create_cle_event(product=product, event_type="released", effective=release_date, version="")
            if not result.ok:
                return htmx_error_response(result.error or "Failed to update release date")

        if end_of_support and (product.end_of_support is None or end_of_support.date() != product.end_of_support):
            result = create_cle_event(
                product=product,
                event_type="endOfSupport",
                effective=end_of_support,
                versions=[{"range": "vers:generic/*"}],
            )
            if not result.ok:
                return htmx_error_response(result.error or "Failed to update end of support")

        if end_of_life and (product.end_of_life is None or end_of_life.date() != product.end_of_life):
            result = create_cle_event(
                product=product,
                event_type="endOfLife",
                effective=end_of_life,
                versions=[{"range": "vers:generic/*"}],
            )
            if not result.ok:
                return htmx_error_response(result.error or "Failed to update end of life")

        product.refresh_from_db()

        # Re-render the card
        context = self._get_context(request, product)
        return render(request, self.template_name, context)
