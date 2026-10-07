from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from sbomify.apps.core.authz import MANAGE
from sbomify.apps.core.forms import ReleaseCreateForm
from sbomify.apps.core.services.release_creation import create_workspace_release, release_product_choices
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin, TeamRoleRequiredMixin


class ReleaseCreateView(GuestAccessBlockedMixin, TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = list(MANAGE)

    def get(self, request: HttpRequest) -> HttpResponse:
        return self.form_response(request)

    def post(self, request: HttpRequest) -> HttpResponse:
        return self.form_response(request)

    def form_response(self, request: HttpRequest) -> HttpResponse:
        choices = release_product_choices(request)
        if not choices.ok:
            return HttpResponse(choices.error, status=choices.status_code or 403)
        products = choices.value or []
        product_id = request.POST.get("product_id", "") if request.method == "POST" else request.GET.get("product", "")
        if request.method == "GET" and product_id and product_id not in dict(products):
            return HttpResponse("Product not found", status=404)
        form = ReleaseCreateForm(
            request.POST if request.method == "POST" else None,
            products=products,
            initial={"product_id": product_id},
        )
        if request.method == "POST" and form.is_valid():
            result = create_workspace_release(request, form.cleaned_data)
            if result.ok and result.value:
                messages.success(request, "Release created. Add its artifacts below.")
                destination = reverse("core:release_details", args=[result.value["product_id"], result.value["id"]])
                if request.headers.get("HX-Request"):
                    return HttpResponse(headers={"HX-Redirect": destination})
                return redirect(destination)
            form.add_error(None, result.error or "Unable to create the release.")

        back_url = (
            reverse("core:product_releases", args=[product_id])
            if product_id in dict(products)
            else reverse("core:releases_dashboard")
        )
        context: dict[str, Any] = {
            "form": form,
            "products": products,
            "back_url": back_url,
            "timezone_name": timezone.get_current_timezone_name(),
        }
        return render(request, "core/release_new.html.j2", context)
