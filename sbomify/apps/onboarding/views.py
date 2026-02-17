from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.billing.billing_helpers import RATE_LIMIT, RATE_LIMIT_PERIOD, check_rate_limit
from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_pricing_service import StripePricingService
from sbomify.logging import getLogger

from .models import OnboardingStatus

logger = getLogger(__name__)

VALID_PLANS = {"community", "business", "enterprise"}


class OnboardingPlanSelectionView(LoginRequiredMixin, View):
    """Post-wizard plan selection page for new users."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")

        onboarding_status = OnboardingStatus.objects.filter(user=request.user).first()
        if not onboarding_status:
            return redirect("core:dashboard")

        # Already selected a plan — skip
        if onboarding_status.has_selected_plan:
            return redirect("core:dashboard")

        # Wizard not completed yet — stash plan hint and redirect to wizard
        current_team = request.session.get("current_team", {})
        if not current_team.get("has_completed_wizard", True):
            plan_hint = request.GET.get("plan", "")
            if plan_hint in VALID_PLANS:
                request.session["onboarding_plan_hint"] = plan_hint
            return redirect("teams:onboarding_wizard")

        # Resolve plan hint: GET param > session fallback
        plan_hint = request.GET.get("plan", "") or request.session.get("onboarding_plan_hint", "")
        if plan_hint not in VALID_PLANS:
            plan_hint = ""

        context = self._build_context(plan_hint)
        return render(request, "onboarding/select_plan.html.j2", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")

        if check_rate_limit(f"onboarding_plan:{request.user.pk}", limit=RATE_LIMIT, period=RATE_LIMIT_PERIOD):
            messages.error(request, "Too many requests. Please try again later.")
            return redirect("onboarding:select_plan")

        onboarding_status = OnboardingStatus.objects.filter(user=request.user).first()
        if not onboarding_status:
            return redirect("core:dashboard")

        if onboarding_status.has_selected_plan:
            return redirect("core:dashboard")

        plan_key = request.POST.get("plan", "")
        if plan_key not in VALID_PLANS:
            messages.error(request, "Please select a valid plan.")
            return redirect("onboarding:select_plan")

        # Enterprise → mark selected, redirect to enterprise contact form
        if plan_key == "enterprise":
            onboarding_status.mark_plan_selected()
            request.session.pop("onboarding_plan_hint", None)
            return redirect("billing:enterprise_contact")

        # Business → set up trial subscription via Stripe
        if plan_key == "business":
            from sbomify.apps.teams.models import Member
            from sbomify.apps.teams.utils import setup_trial_subscription

            member = Member.objects.filter(user=request.user, is_default_team=True).first()
            if member and member.role == "owner":
                # Idempotency: skip if trial already set up
                existing_limits = member.team.billing_plan_limits or {}
                if existing_limits.get("stripe_subscription_id"):
                    messages.info(request, "Your trial subscription is already active.")
                    onboarding_status.mark_plan_selected()
                    request.session.pop("onboarding_plan_hint", None)
                    return redirect("core:dashboard")
                success = setup_trial_subscription(request.user, member.team)
                if success:
                    messages.success(
                        request,
                        f"Your {settings.TRIAL_PERIOD_DAYS}-day Business trial has started!",
                    )
                else:
                    messages.warning(
                        request,
                        "We couldn't start the trial right now. "
                        "You're on the Community plan — you can upgrade anytime.",
                    )
            elif member:
                messages.warning(request, "Only workspace owners can start a trial.")
            else:
                messages.warning(request, "No workspace found. You can upgrade from workspace settings later.")

        # Community → no-op (already on community from signup)
        onboarding_status.mark_plan_selected()
        request.session.pop("onboarding_plan_hint", None)
        return redirect("core:dashboard")

    def _build_context(self, plan_hint: str) -> dict:
        plans = list(BillingPlan.objects.all().order_by("name"))
        pricing_service = StripePricingService()
        try:
            stripe_pricing = pricing_service.get_all_plans_pricing()
        except Exception:
            logger.exception("Failed to fetch Stripe pricing for onboarding plan selection")
            stripe_pricing = {}

        plan_data = []
        for plan in plans:
            pricing = stripe_pricing.get(plan.key, {})
            plan_data.append(
                {
                    "key": plan.key,
                    "name": plan.name,
                    "description": plan.description or "",
                    "max_products": plan.max_products,
                    "max_projects": plan.max_projects,
                    "max_components": plan.max_components,
                    "monthly_price": float(pricing.get("monthly_price") or 0),
                    "annual_price": float(pricing.get("annual_price") or 0),
                    "monthly_price_discounted": float(pricing.get("monthly_price_discounted") or 0),
                    "annual_price_discounted": float(pricing.get("annual_price_discounted") or 0),
                    "discount_percent_monthly": pricing.get("discount_percent_monthly", 0),
                    "discount_percent_annual": pricing.get("discount_percent_annual", 0),
                    "annual_savings_percent": pricing.get("annual_savings_percent", 0),
                }
            )

        return {
            "plans": plan_data,
            "plan_hint": plan_hint,
            "trial_days": settings.TRIAL_PERIOD_DAYS,
        }
