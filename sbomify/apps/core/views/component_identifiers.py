"""Component identifiers management views."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import (
    create_component_identifier,
    delete_component_identifier,
    get_component,
    list_component_identifiers,
    update_component_identifier,
)
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.schemas import ComponentIdentifierCreateSchema, ComponentIdentifierUpdateSchema
from sbomify.apps.sboms.models import Component

# Identifier types mapping - same as product identifiers
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

# Allowed actions for POST operations
ALLOWED_ACTIONS = {"create", "update", "delete"}


class ComponentIdentifiersView(View):
    """View for component identifiers HTMX partial.

    Supports both authenticated and public access. Public components can be viewed
    by unauthenticated users, but only authenticated users with proper permissions
    can manage identifiers.
    """

    template_name = "core/components/component_identifiers_card.html.j2"

    def _get_context(self, request: HttpRequest, component_id: str, is_public_view: bool = False) -> dict | None:
        """Get common context for rendering.

        Args:
            request: The HTTP request
            component_id: The component ID
            is_public_view: Whether this is a public (unauthenticated) view

        Returns:
            Context dict or None if component not found
        """
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return None

        status_code, identifiers_response = list_component_identifiers(request, component_id, page=1, page_size=100)
        identifiers = []
        if status_code == 200:
            identifiers = identifiers_response.get("items", [])

        # For public views, no management capabilities
        if is_public_view:
            return {
                "component": component,
                "identifiers": identifiers,
                "identifier_types": IDENTIFIER_TYPES,
                "barcode_types": BARCODE_TYPES,
                "has_crud_permissions": False,
                "is_feature_allowed": False,
                "can_manage_identifiers": False,
            }

        current_team = request.session.get("current_team", {})
        billing_plan = current_team.get("billing_plan", "community")
        is_feature_allowed = billing_plan != "community"
        has_crud_permissions = component.get("has_crud_permissions", False)
        can_manage = has_crud_permissions and is_feature_allowed

        return {
            "component": component,
            "identifiers": identifiers,
            "identifier_types": IDENTIFIER_TYPES,
            "barcode_types": BARCODE_TYPES,
            "has_crud_permissions": has_crud_permissions,
            "is_feature_allowed": is_feature_allowed,
            "can_manage_identifiers": can_manage,
        }

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        """Render component identifiers card.

        Supports public access for public components.
        """
        # Check if component is public for unauthenticated users
        is_public_view = False
        if not request.user or not request.user.is_authenticated:
            try:
                component = Component.objects.get(pk=component_id)
                if not component.public_access_allowed:
                    return htmx_error_response("Authentication required")
                is_public_view = True
            except Component.DoesNotExist:
                return htmx_error_response("Component not found")

        context = self._get_context(request, component_id, is_public_view=is_public_view)
        if context is None:
            return htmx_error_response("Component not found")

        return render(request, self.template_name, context)

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        """Handle identifier CRUD operations.

        Requires authentication - POST operations modify data.
        """
        # POST operations require authentication
        if not request.user or not request.user.is_authenticated:
            return htmx_error_response("Authentication required")

        action = request.POST.get("action")

        # Validate action against allowed values
        if action not in ALLOWED_ACTIONS:
            return htmx_error_response("Invalid action")

        if action == "create":
            identifier_type = request.POST.get("identifier_type", "").strip()
            value = request.POST.get("value", "").strip()

            if not identifier_type or not value:
                return htmx_error_response("Both identifier type and value are required")

            payload = ComponentIdentifierCreateSchema(identifier_type=identifier_type, value=value)
            status_code, result = create_component_identifier(request, component_id, payload)

            if status_code != 201:
                return htmx_error_response(result.get("detail", "Failed to create identifier"))

        elif action == "update":
            identifier_id = request.POST.get("identifier_id", "").strip()
            identifier_type = request.POST.get("identifier_type", "").strip()
            value = request.POST.get("value", "").strip()

            if not identifier_id or not identifier_type or not value:
                return htmx_error_response("All fields are required")

            payload = ComponentIdentifierUpdateSchema(identifier_type=identifier_type, value=value)
            status_code, result = update_component_identifier(request, component_id, identifier_id, payload)

            if status_code != 200:
                return htmx_error_response(result.get("detail", "Failed to update identifier"))

        elif action == "delete":
            identifier_id = request.POST.get("identifier_id", "").strip()
            if not identifier_id:
                return htmx_error_response("Identifier ID is required")

            status_code, result = delete_component_identifier(request, component_id, identifier_id)
            if status_code != 204:
                return htmx_error_response(result.get("detail", "Failed to delete identifier"))

        # Re-render the identifiers card
        context = self._get_context(request, component_id)
        if context is None:
            return htmx_error_response("Component not found")

        response = render(request, self.template_name, context)
        # Add HX-Trigger to close any open modals
        response["HX-Trigger"] = "closeModal"
        return response
