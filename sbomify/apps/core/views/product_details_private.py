from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_dashboard_summary
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Product
from sbomify.apps.core.utils import verify_item_access


class ProductDetailsPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        try:
            product: Product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Product not found"))

        if not verify_item_access(request, product, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

        has_crud_permissions = verify_item_access(request, product, ["owner", "admin"])

        status_code, dashboard_data = get_dashboard_summary(request, product_id=product_id)
        dashboard_stats = dashboard_data if status_code == 200 else {}

        return render(
            request,
            "core/product_details_private.html.j2",
            {
                "product": product,
                "has_crud_permissions": has_crud_permissions,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": request.session.get("current_team", {}),
                "team_billing_plan": getattr(product.team, "billing_plan", "community"),
                "dashboard_stats": dashboard_stats,
            },
        )
