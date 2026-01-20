"""Product lifecycle management views."""

from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.models import Product
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

    def _get_context(self, request: HttpRequest, product: Product) -> dict:
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
        def parse_date(value: str):
            """Parse date string to date object or None."""
            if not value or value.strip() == "":
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return None

        release_date = parse_date(request.POST.get("release_date", ""))
        end_of_support = parse_date(request.POST.get("end_of_support", ""))
        end_of_life = parse_date(request.POST.get("end_of_life", ""))

        # Update product
        product.release_date = release_date
        product.end_of_support = end_of_support
        product.end_of_life = end_of_life
        product.save(update_fields=["release_date", "end_of_support", "end_of_life"])

        # Re-render the card
        context = self._get_context(request, product)
        return render(request, self.template_name, context)
