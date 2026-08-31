from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_product, list_products
from sbomify.apps.core.authz import MANAGE
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ProductCreateSchema
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key


def _get_products_context(request: HttpRequest) -> dict[str, Any] | None:
    """Helper to get common context for products views."""
    status_code, products = list_products(request, page=1, page_size=-1)
    if status_code != 200:
        return None

    current_team = request.session.get("current_team") or {}
    has_crud_permissions = get_member_role_by_key(request.user, current_team.get("key")) in MANAGE

    # Sort products alphabetically by name
    sorted_products = sorted(products.items, key=lambda p: p.name.lower())

    # Compute stats for dashboard
    public_count = sum(1 for p in sorted_products if p.is_public)
    private_count = len(sorted_products) - public_count

    # Serialize products for JSON (Alpine.js table). This is intentionally a
    # narrow projection of ProductResponseSchema — the table at
    # core/templates/core/products_table.html.j2 only reads `id`, `name`,
    # `description`, `is_public`, and `components[].{id,name}` for rendering
    # and the row-expansion sub-list. If the table starts consuming more
    # schema fields, expand this projection accordingly.
    products_json = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "is_public": p.is_public,
            "components": [{"id": comp.id, "name": comp.name} for comp in (p.components or [])],
        }
        for p in sorted_products
    ]

    return {
        "current_team": current_team,
        "has_crud_permissions": has_crud_permissions,
        "products": products_json,
        "products_count": len(sorted_products),
        "public_count": public_count,
        "private_count": private_count,
    }


def _create_product(request: HttpRequest, *, on_error: str) -> HttpResponse:
    """Create a product from a posted form, returning to `on_error` if it fails."""
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()

    payload = ProductCreateSchema(
        name=name,
        description=description,
    )

    status_code, response_data = create_product(request, payload)
    if status_code != 201:
        error_detail = response_data.get("detail", "An error occurred while creating the product")
        messages.error(request, error_detail)
        return redirect(on_error)

    messages.success(request, f'Product "{name}" created successfully!')
    # `create_product` returns the API response dict (see `_build_item_response`),
    # not a model instance, so read the id by key.
    return redirect("core:product_details", product_id=response_data["id"])


class ProductsDashboardView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_products_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load products"))

        return render(request, "core/products_dashboard.html.j2", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        # Kept so anything still posting the create form at the list URL keeps
        # working; the form itself now lives at product_new.
        return _create_product(request, on_error="core:products_dashboard")


class ProductCreateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The New Product form, as a page, matching the New Advisory flow."""

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team") or {}
        if get_member_role_by_key(request.user, current_team.get("key")) not in MANAGE:
            raise Http404("Workspace not found")

        return render(request, "core/product_new.html.j2", {"current_team": current_team})

    def post(self, request: HttpRequest) -> HttpResponse:
        return _create_product(request, on_error="core:product_new")


class ProductsTableView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """View for HTMX table refresh."""

    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_products_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load products"))

        return render(request, "core/products_table.html.j2", context)
