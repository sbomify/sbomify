from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_dashboard_summary, get_product
from sbomify.apps.core.errors import error_response


class ProductDetailsPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        status_code, product = get_product(request, product_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=product.get("detail", "Unknown error"))
            )

        status_code, dashboard_summary = get_dashboard_summary(request, product_id=product_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=dashboard_summary.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})
        is_owner = current_team.get("role") == "owner"
        team_billing_plan = current_team.get("billing_plan")

        return render(
            request,
            "core/product_details_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "dashboard_summary": dashboard_summary,
                "is_owner": is_owner,
                "product": product,
                "team_billing_plan": team_billing_plan,
            },
        )
