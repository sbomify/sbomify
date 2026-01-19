from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_product, list_products
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ProductCreateSchema
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ProductsDashboardView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        status_code, products = list_products(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=products.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team")
        has_crud_permissions = current_team.get("role") in ["owner", "admin"]

        return render(
            request,
            "core/products_dashboard.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": has_crud_permissions,
                "products": products.items,
            },
        )

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
