from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_product, list_products
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ProductCreateSchema
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


def _get_products_context(request: HttpRequest) -> dict | None:
    """Helper to get common context for products views."""
    status_code, products = list_products(request, page=1, page_size=-1)
    if status_code != 200:
        return None

    current_team = request.session.get("current_team")
    has_crud_permissions = current_team.get("role") in ["owner", "admin"]

    # Sort products alphabetically by name
    sorted_products = sorted(products.items, key=lambda p: p.name.lower())

    return {
        "current_team": current_team,
        "has_crud_permissions": has_crud_permissions,
        "products": sorted_products,
    }


class ProductsDashboardView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_products_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load products"))

        return render(request, "core/products_dashboard.html.j2", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        payload = ProductCreateSchema(
            name=name,
            description=description,
        )

        status_code, response_data = create_product(request, payload)
        if status_code == 201:
            messages.success(request, f'Product "{name}" created successfully!')
        else:
            error_detail = response_data.get("detail", "An error occurred while creating the product")
            messages.error(request, error_detail)

        return redirect("core:products_dashboard")


class ProductsTableView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """View for HTMX table refresh."""

    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_products_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load products"))

        return render(request, "core/products_table.html.j2", context)
