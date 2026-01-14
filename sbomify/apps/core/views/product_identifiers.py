"""Product identifiers management views."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import (
    create_product_identifier,
    delete_product_identifier,
    get_product,
    list_product_identifiers,
    update_product_identifier,
)
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.schemas import ProductIdentifierCreateSchema, ProductIdentifierUpdateSchema

# Identifier types mapping
IDENTIFIER_TYPES = {
    "gtin_12": "GTIN-12 (UPC-A)",
    "gtin_13": "GTIN-13 (EAN-13)",
    "gtin_14": "GTIN-14 / ITF-14",
    "gtin_8": "GTIN-8",
    "sku": "SKU",
    "mpn": "MPN",
    "asin": "ASIN",
    "gs1_gpc_brick": "GS1 GPC Brick code",
    "cpe": "CPE",
    "purl": "PURL",
}

# Types that can render barcodes
BARCODE_TYPES = ["gtin_12", "gtin_13", "gtin_14", "gtin_8"]


class ProductIdentifiersView(LoginRequiredMixin, View):
    """View for product identifiers HTMX partial."""

    template_name = "core/components/product_identifiers_card.html.j2"

    def _get_context(self, request: HttpRequest, product_id: str) -> dict | None:
        """Get common context for rendering."""
        status_code, product = get_product(request, product_id)
        if status_code != 200:
            return None

        status_code, identifiers_response = list_product_identifiers(request, product_id, page=1, page_size=100)
        identifiers = []
        if status_code == 200:
            identifiers = identifiers_response.get("items", [])

        current_team = request.session.get("current_team", {})
        billing_plan = current_team.get("billing_plan", "community")
        is_feature_allowed = billing_plan != "community"
        has_crud_permissions = product.get("has_crud_permissions", False)
        can_manage = has_crud_permissions and is_feature_allowed

        return {
            "product": product,
            "identifiers": identifiers,
            "identifier_types": IDENTIFIER_TYPES,
            "barcode_types": BARCODE_TYPES,
            "has_crud_permissions": has_crud_permissions,
            "is_feature_allowed": is_feature_allowed,
            "can_manage_identifiers": can_manage,
        }

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Render product identifiers card."""
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Handle identifier CRUD operations."""
        action = request.POST.get("action")

        if action == "create":
            identifier_type = request.POST.get("identifier_type", "").strip()
            value = request.POST.get("value", "").strip()

            if not identifier_type or not value:
                return htmx_error_response("Both identifier type and value are required")

            payload = ProductIdentifierCreateSchema(identifier_type=identifier_type, value=value)
            status_code, result = create_product_identifier(request, product_id, payload)

            if status_code != 201:
                return htmx_error_response(result.get("detail", "Failed to create identifier"))

        elif action == "update":
            identifier_id = request.POST.get("identifier_id", "").strip()
            identifier_type = request.POST.get("identifier_type", "").strip()
            value = request.POST.get("value", "").strip()

            if not identifier_id or not identifier_type or not value:
                return htmx_error_response("All fields are required")

            payload = ProductIdentifierUpdateSchema(identifier_type=identifier_type, value=value)
            status_code, result = update_product_identifier(request, product_id, identifier_id, payload)

            if status_code != 200:
                return htmx_error_response(result.get("detail", "Failed to update identifier"))

        elif action == "delete":
            identifier_id = request.POST.get("identifier_id", "").strip()
            if not identifier_id:
                return htmx_error_response("Identifier ID is required")

            status_code, result = delete_product_identifier(request, product_id, identifier_id)
            if status_code != 204:
                return htmx_error_response(result.get("detail", "Failed to delete identifier"))

        # Re-render the identifiers card
        context = self._get_context(request, product_id)
        if context is None:
            return htmx_error_response("Product not found")

        response = render(request, self.template_name, context)
        # Add HX-Trigger to close any open modals
        response["HX-Trigger"] = "closeModal"
        return response
