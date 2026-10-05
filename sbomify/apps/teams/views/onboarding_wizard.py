from __future__ import annotations

import typing
from typing import Any, cast

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.models import User
from sbomify.apps.teams.forms import OnboardingCompanyForm
from sbomify.apps.teams.models import (
    Member,
    Team,
    default_patch_sla_days,
)
from sbomify.apps.teams.utils import (
    refresh_current_team_session,
    update_user_teams_session,
)
from sbomify.logging import getLogger

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

log = getLogger(__name__)

VALID_PLANS = {"community", "business", "enterprise"}


class OnboardingWizardView(LoginRequiredMixin, View):
    """Onboarding wizard: Welcome -> Setup -> Complete -> Plan (when billing enabled)."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[return-value]

        team = self._get_current_team(request)
        if team and team.has_completed_wizard:
            pending_plan = is_billing_enabled() and not team.has_selected_billing_plan
            showing_completion = request.GET.get("step") == "complete" and request.session.get("wizard_company_name")
            if not pending_plan and not showing_completion:
                messages.info(request, "Onboarding is already complete.")
                return redirect("core:dashboard")

        return super().dispatch(request, *args, **kwargs)  # type: ignore[return-value]

    def get(self, request: HttpRequest) -> HttpResponse:
        step = request.GET.get("step")
        if step == "setup":
            return self._render_setup(request)
        if step == "complete":
            return self._render_complete(request)
        if step == "plan":
            return self._render_plan(request)
        return self._render_welcome(request)

    def post(self, request: HttpRequest) -> HttpResponse:
        if "plan" in request.POST:
            return self._process_plan(request)
        return self._process_setup(request)

    def _render_welcome(self, request: HttpRequest) -> HttpResponse:
        user: Any = request.user
        first_name = user.first_name or (user.email or "").split("@")[0]
        context = {
            "current_step": "welcome",
            "first_name": first_name,
            "billing_enabled": is_billing_enabled(),
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_setup(self, request: HttpRequest, form: OnboardingCompanyForm | None = None) -> HttpResponse:
        user = cast(User, request.user)
        initial: dict[str, Any] = {"email": getattr(request.user, "email", "")}
        full_name = user.get_full_name()
        if full_name:
            initial["contact_name"] = full_name

        if form is None:
            team = self._get_current_team(request)
            initial.update(default_patch_sla_days())
            if team:
                initial.update(team.patch_sla_days)
                initial["mode"] = "recommended" if team.patch_sla_days == default_patch_sla_days() else "custom"
                if team.default_support_period_years is not None:
                    initial["default_support_period_years"] = team.default_support_period_years
            form = OnboardingCompanyForm(initial=initial)
        security_fields = {
            "security_email",
            "publish_security_txt",
            "mode",
            "critical",
            "high",
            "medium",
            "low",
            "default_support_period_years",
        }
        setup_step = "security" if form.errors and not (set(form.errors) - security_fields) else "organisation"
        context = {
            "form": form,
            "wizard_config": {"step": setup_step, "addressExpanded": bool(form["address"].value())},
            "current_step": "setup",
            "billing_enabled": is_billing_enabled(),
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_complete(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.teams.services.contacts import get_security_contact

        # Keyed on the company name rather than a component id: the wizard no
        # longer creates a component, and gating on one meant this step could
        # only be reached by having an entity the user never asked for.
        company_name = request.session.get("wizard_company_name")
        if not company_name:
            return redirect(reverse("teams:onboarding_wizard"))

        billing_enabled = is_billing_enabled()
        if billing_enabled:
            next_url = f"{reverse('teams:onboarding_wizard')}?step=plan"
        else:
            # The dashboard, where the onboarding checklist asks for a product
            # and a component. Those steps used to be pre-ticked by the wizard
            # creating both, so the checklist was complete before the person
            # had done either.
            next_url = reverse("core:dashboard")

        team = self._get_current_team(request)
        context = {
            "current_step": "complete",
            "company_name": company_name,
            "setup_saved": True,
            "security_contact_saved": bool(team and get_security_contact(team)),
            "support_default_saved": bool(team and team.default_support_period_years),
            "next_url": next_url,
            "billing_enabled": billing_enabled,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_plan(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")

        team = self._get_current_team(request)
        if not team or not self._can_administer_team(request.user, team):
            return redirect("core:dashboard")

        if team.has_selected_billing_plan:
            return redirect("core:dashboard")

        # Release checkout lock only when positively identified as a cancelled checkout
        if request.GET.get("checkout_cancelled") == "1" and team.key:
            from sbomify.apps.billing.billing_helpers import release_checkout_lock

            release_checkout_lock(team.key)

        plan_hint = request.GET.get("plan", "") or request.session.get("onboarding_plan_hint", "")
        if plan_hint not in VALID_PLANS:
            plan_hint = ""

        from sbomify.apps.teams.services.onboarding import build_onboarding_plan_context

        context = build_onboarding_plan_context(request, team, plan_hint)
        context["current_step"] = "plan"
        context["billing_enabled"] = True
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _process_plan(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.billing.billing_helpers import RATE_LIMIT, RATE_LIMIT_PERIOD, check_rate_limit

        if not is_billing_enabled():
            return redirect("core:dashboard")

        plan_url = f"{reverse('teams:onboarding_wizard')}?step=plan"

        if check_rate_limit(f"onboarding_plan:{request.user.pk}", limit=RATE_LIMIT, period=RATE_LIMIT_PERIOD):
            messages.error(request, "Too many requests. Please try again later.")
            return redirect(plan_url)

        team = self._get_current_team(request)
        if not team or not self._can_administer_team(request.user, team):
            return redirect("core:dashboard")

        if team.has_selected_billing_plan:
            return redirect("core:dashboard")

        plan_key = request.POST.get("plan", "")
        if plan_key not in VALID_PLANS:
            messages.error(request, "Please select a valid plan.")
            return redirect(plan_url)

        if plan_key == "enterprise":
            team.has_selected_billing_plan = True
            team.save(update_fields=["has_selected_billing_plan"])
            self._pop_wizard_session(request)
            return redirect("billing:enterprise_contact")

        if plan_key == "business":
            existing_limits = team.billing_plan_limits or {}
            if existing_limits.get("stripe_subscription_id"):
                messages.info(request, "Your trial subscription is already active.")
                team.has_selected_billing_plan = True
                team.save(update_fields=["has_selected_billing_plan"])
                self._pop_wizard_session(request)
                return redirect("core:dashboard")

            # Redirect to Stripe Checkout with trial period to collect card details
            from sbomify.apps.billing.billing_helpers import acquire_checkout_lock, release_checkout_lock
            from sbomify.apps.billing.models import BillingPlan
            from sbomify.apps.billing.stripe_pricing_service import StripePricingService

            try:
                business_plan = BillingPlan.objects.get(key=BillingPlan.KEY_BUSINESS)
            except BillingPlan.DoesNotExist:
                messages.error(request, "Business plan not configured. Please contact support.")
                return redirect(plan_url)

            team_key: str | None = team.key
            if not team_key:
                log.error("Team %s has no key set — cannot start billing checkout", getattr(team, "pk", "unknown"))
                messages.error(request, "We couldn't start the checkout for your workspace. Please contact support.")
                return redirect(plan_url)

            if not acquire_checkout_lock(team_key):
                messages.info(request, "A checkout is already in progress. Please wait.")
                return redirect(plan_url)

            from sbomify.apps.billing.stripe_client import StripeError

            try:
                pricing_service = StripePricingService()
                success_url = (
                    request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}"
                )
                cancel_url = request.build_absolute_uri(plan_url + "&checkout_cancelled=1")
                user_email: str = getattr(request.user, "email", "") or ""
                billing_period = request.POST.get("billing_period", "monthly")
                if billing_period not in {"monthly", "annual"}:
                    billing_period = "monthly"
                session = pricing_service.create_checkout_session(
                    team=team,
                    user_email=user_email,
                    plan=business_plan,
                    billing_period=billing_period,
                    success_url=success_url,
                    cancel_url=cancel_url,
                    trial_period_days=settings.TRIAL_PERIOD_DAYS,
                )
                self._pop_wizard_session(request)
                return redirect(session.url)
            except StripeError:
                release_checkout_lock(team_key)
                log.exception("Stripe error creating checkout session for team %s", team_key)
                messages.warning(
                    request,
                    "We couldn't start the checkout right now. You're on the Community plan — you can upgrade anytime.",
                )
                return redirect(plan_url)
            except Exception:
                release_checkout_lock(team_key)
                raise

        team.has_selected_billing_plan = True
        team.save(update_fields=["has_selected_billing_plan"])
        self._pop_wizard_session(request)
        return redirect("core:dashboard")

    @staticmethod
    def _get_current_team(request: HttpRequest) -> Team | None:
        team_key = request.session.get("current_team", {}).get("key")
        if team_key:
            team = Team.objects.filter(key=team_key).first()
            if team:
                return team
        user = cast(User, request.user)
        member = Member.objects.filter(user=user, is_default_team=True).select_related("team").first()
        return member.team if member else None

    @staticmethod
    def _can_administer_team(user: Any, team: Team) -> bool:
        """The wizard configures the workspace, so it's the ADMINISTER tier."""
        return Member.objects.filter(user=user, team=team, role__in=ADMINISTER).exists()

    @staticmethod
    def _pop_wizard_session(request: HttpRequest) -> None:
        request.session.pop("wizard_company_name", None)
        request.session.pop("onboarding_plan_hint", None)

    def _process_setup(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.teams.services.onboarding import complete_workspace_setup

        team = self._get_current_team(request)
        if not team or not self._can_administer_team(request.user, team):
            return redirect("core:dashboard")
        if team.is_payment_restricted:
            messages.error(request, "Your account is suspended. Please update your payment method.")
            return redirect("teams:onboarding_wizard")

        form = OnboardingCompanyForm(request.POST)
        if form.is_valid():
            result = complete_workspace_setup(team, cast(User, request.user), form.cleaned_data)
            if result.ok and result.value:
                if result.value.warning:
                    messages.warning(request, result.value.warning)
                update_user_teams_session(request, cast(User, request.user))
                refresh_current_team_session(request, result.value.workspace)
                request.session["wizard_company_name"] = form.cleaned_data["company_name"]
                messages.success(request, "Your workspace settings are saved.")
                return redirect(f"{reverse('teams:onboarding_wizard')}?step=complete")
            form.add_error(None, result.error or "Unable to complete setup. Please try again.")

        return self._render_setup(request, form=form)
