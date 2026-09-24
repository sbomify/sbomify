from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.vary import vary_on_headers

from sbomify.apps.core.apis import create_product
from sbomify.apps.core.authz import MANAGE
from sbomify.apps.core.forms import ProductCreateForm
from sbomify.apps.core.schemas import ProductCreateSchema
from sbomify.apps.core.services.inventory_page import build_inventory_context
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key


def _create_product(request: HttpRequest) -> HttpResponse:
    """Validate before calling the API and retain the form on any error."""
    form = ProductCreateForm(request.POST)
    if form.is_valid():
        status_code, response_data = create_product(request, ProductCreateSchema(**form.cleaned_data))
        if status_code == 201:
            messages.success(request, "Product created")
            return redirect("core:product_details", product_id=response_data["id"])
        form.add_error(None, response_data.get("detail", "Unable to create the product."))
    return render(request, "core/product_new.html.j2", {"form": form})


class InventoryView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    inventory_kind: str | None = None

    @method_decorator(vary_on_headers("HX-Target", "HX-Request"))
    def get(self, request: HttpRequest) -> HttpResponse:
        if "view" in request.GET:
            params = request.GET.copy()
            legacy_kind = params.pop("view")[-1]
            kind = self.inventory_kind or (legacy_kind if legacy_kind in ("releases", "components") else "products")
            query = params.urlencode()
            destination = reverse(f"core:{kind}_dashboard") + (f"?{query}" if query else "")
            if request.headers.get("HX-Request") == "true":
                return HttpResponse(headers={"HX-Redirect": destination})
            return redirect(destination)
        result = build_inventory_context(request, kind=self.inventory_kind)
        if not result.ok:
            return HttpResponse(result.error, status=result.status_code or 400)
        partial = request.headers.get("HX-Target") == "inventory-content"
        template = "core/products_inventory.html.j2" if partial else "core/products_dashboard.html.j2"
        return render(request, template, {**(result.value or {}), "inventory_navigation_oob": partial})


class ProductsDashboardView(InventoryView):
    def post(self, request: HttpRequest) -> HttpResponse:
        # Kept so anything still posting the create form at the list URL keeps
        # working; the form itself now lives at product_new.
        return _create_product(request)


class ProductCreateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The New Product form, as a page, matching the New Advisory flow."""

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team") or {}
        if get_member_role_by_key(request.user, current_team.get("key")) not in MANAGE:
            raise Http404("Workspace not found")

        return render(request, "core/product_new.html.j2", {"form": ProductCreateForm()})

    def post(self, request: HttpRequest) -> HttpResponse:
        return _create_product(request)


class ProductsTableView(InventoryView):
    """Keep the existing table refresh URL available."""

    def get(self, request: HttpRequest) -> HttpResponse:
        result = build_inventory_context(request, kind=self.inventory_kind)
        if not result.ok:
            return HttpResponse(result.error, status=result.status_code or 400)
        return render(
            request, "core/products_inventory.html.j2", {**(result.value or {}), "inventory_navigation_oob": True}
        )
