from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from sbomify.apps.billing.config import is_billing_enabled


class OnboardingPlanSelectionView(LoginRequiredMixin, View):
    """Redirects to the wizard's plan step. Kept for backward compatibility with bookmarks/links."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")
        return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")

    def post(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")
        return redirect(f"{reverse('teams:onboarding_wizard')}?step=plan")
