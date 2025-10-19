from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View


class ProductsDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.core.apis import list_products

        current_team = request.session.get("current_team")
        has_crud_permissions = current_team and current_team.get("role") in ("owner", "admin")

        status_code, response_data = list_products(request, page=1, page_size=-1)

        products = []
        if status_code == 200:
            products = response_data.items

        return render(
            request,
            "core/products_dashboard.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": has_crud_permissions,
                "products": products,
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.core.apis import create_product
        from sbomify.apps.core.schemas import ProductCreateSchema

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
