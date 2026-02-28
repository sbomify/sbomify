from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import get_dashboard_summary, get_product, patch_product
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ProductPatchSchema
from sbomify.apps.tea.mappers import get_product_tei_urn
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class ProductDetailsPrivateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.product_details_public import ProductDetailsPublicView

            return ProductDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

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

        # Build TEI URN if TEA is enabled with a validated custom domain
        product_tei = get_product_tei_urn(product["id"], product["team_id"])

        return render(
            request,
            "core/product_details_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "dashboard_summary": dashboard_summary,
                "is_owner": is_owner,
                "product": product,
                "product_tei": product_tei,
                "team_billing_plan": team_billing_plan,
            },
        )

    def post(self, request: HttpRequest, product_id: str) -> HttpResponse:
        """Handle product description updates."""
        action = request.POST.get("action")

        if action == "update_description":
            description = request.POST.get("description", "").strip()
            payload = ProductPatchSchema(description=description if description else None)
            status_code, result = patch_product(request, product_id, payload)

            if status_code != 200:
                # TODO: Add proper error handling/flash message
                pass

        return redirect("core:product_details", product_id=product_id)
