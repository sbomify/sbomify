from __future__ import annotations

import typing

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.forms import OnboardingCompanyForm
from sbomify.apps.teams.models import (
    ContactEntity,
    ContactProfile,
    ContactProfileContact,
    Member,
    Team,
    format_workspace_name,
)
from sbomify.apps.teams.utils import (
    refresh_current_team_session,
    update_user_teams_session,
)
from sbomify.logging import getLogger

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

log = getLogger(__name__)

DEFAULT_SBOM_AUGMENTATION_URL = "https://sbomify.com/features/generate-collaborate-analyze/"
VALID_PLANS = {"community", "business", "enterprise"}


class OnboardingWizardView(LoginRequiredMixin, View):
    """Onboarding wizard: Welcome -> Setup -> Complete -> Plan (when billing enabled)."""

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
        user = request.user
        first_name = user.first_name or (user.email or "").split("@")[0]
        context = {
            "current_step": "welcome",
            "first_name": first_name,
            "billing_enabled": is_billing_enabled(),
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_setup(self, request: HttpRequest) -> HttpResponse:
        initial = {"email": request.user.email}
        full_name = request.user.get_full_name()
        if full_name:
            initial["contact_name"] = full_name

        form = OnboardingCompanyForm(initial=initial)
        sbom_augmentation_url = getattr(settings, "SBOM_AUGMENTATION_URL", DEFAULT_SBOM_AUGMENTATION_URL)

        context = {
            "form": form,
            "current_step": "setup",
            "sbom_augmentation_url": sbom_augmentation_url,
            "billing_enabled": is_billing_enabled(),
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_complete(self, request: HttpRequest) -> HttpResponse:
        component_id = request.session.get("wizard_component_id")
        if not component_id:
            return redirect(reverse("teams:onboarding_wizard"))

        billing_enabled = is_billing_enabled()
        if billing_enabled:
            next_url = f"{reverse('teams:onboarding_wizard')}?step=plan"
        else:
            # Pop session data — no plan step follows
            request.session.pop("wizard_component_id", None)
            next_url = reverse("core:component_details", kwargs={"component_id": component_id})

        company_name = request.session.get("wizard_company_name", "")

        context = {
            "current_step": "complete",
            "component_id": component_id,
            "company_name": company_name,
            "next_url": next_url,
            "billing_enabled": billing_enabled,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    def _render_plan(self, request: HttpRequest) -> HttpResponse:
        if not is_billing_enabled():
            return redirect("core:dashboard")

        team = self._get_current_team(request)
        if not team or not self._is_team_owner(request.user, team):
            return redirect("core:dashboard")

        if team.has_selected_billing_plan:
            return redirect("core:dashboard")

        plan_hint = request.GET.get("plan", "") or request.session.get("onboarding_plan_hint", "")
        if plan_hint not in VALID_PLANS:
            plan_hint = ""

        context = self._build_plan_context(plan_hint)
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
        if not team or not self._is_team_owner(request.user, team):
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
            from sbomify.apps.teams.utils import setup_trial_subscription

            existing_limits = team.billing_plan_limits or {}
            if existing_limits.get("stripe_subscription_id"):
                messages.info(request, "Your trial subscription is already active.")
                team.has_selected_billing_plan = True
                team.save(update_fields=["has_selected_billing_plan"])
                self._pop_wizard_session(request)
                return redirect("core:dashboard")
            success = setup_trial_subscription(request.user, team)
            if success:
                messages.success(
                    request,
                    f"Your {settings.TRIAL_PERIOD_DAYS}-day Business trial has started!",
                )
            else:
                messages.warning(
                    request,
                    "We couldn't start the trial right now. You're on the Community plan — you can upgrade anytime.",
                )
                return redirect(plan_url)

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
        member = Member.objects.filter(user=request.user, is_default_team=True).select_related("team").first()
        return member.team if member else None

    @staticmethod
    def _is_team_owner(user, team: Team) -> bool:
        return Member.objects.filter(user=user, team=team, role="owner").exists()

    @staticmethod
    def _pop_wizard_session(request: HttpRequest) -> None:
        request.session.pop("wizard_component_id", None)
        request.session.pop("wizard_company_name", None)
        request.session.pop("onboarding_plan_hint", None)

    @staticmethod
    def _build_plan_context(plan_hint: str) -> dict:
        from sbomify.apps.billing.models import BillingPlan
        from sbomify.apps.billing.stripe_pricing_service import StripePricingService

        plan_order = {"community": 0, "business": 1, "enterprise": 2}
        plans = sorted(BillingPlan.objects.filter(key__in=VALID_PLANS), key=lambda p: plan_order.get(p.key, 99))
        from sbomify.apps.billing.config import is_billing_enabled

        stripe_pricing = {}
        if is_billing_enabled():
            pricing_service = StripePricingService()
            try:
                stripe_pricing = pricing_service.get_all_plans_pricing()
            except Exception:
                log.exception("Failed to fetch Stripe pricing for onboarding plan selection")

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

    def _process_setup(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.sboms.utils import (
            create_default_component_metadata,
            populate_component_metadata_native_fields,
        )

        team = self._get_current_team(request)
        if not team or not self._is_team_owner(request.user, team):
            return redirect("core:dashboard")

        if team.is_payment_restricted:
            messages.error(request, "Your account is suspended. Please update your payment method.")
            return redirect("teams:onboarding_wizard")

        sbom_augmentation_url = getattr(settings, "SBOM_AUGMENTATION_URL", DEFAULT_SBOM_AUGMENTATION_URL)

        form = OnboardingCompanyForm(request.POST)
        if form.is_valid():
            company_name = form.cleaned_data["company_name"]

            # Skip billing limit checks during onboarding. The wizard creates at
            # most one product/project/component via get_or_create and should never
            # be blocked — otherwise teams with pre-existing assets at the limit
            # get stuck in an infinite onboarding loop.

            try:
                with transaction.atomic():
                    website_url = form.cleaned_data.get("website")
                    contact_name = form.cleaned_data["contact_name"]
                    contact_email = (form.cleaned_data.get("email") or "").strip() or request.user.email

                    contact_profile, created = ContactProfile.objects.get_or_create(
                        team=team, is_default=True, defaults={"name": "Default"}
                    )

                    # A profile can only have one manufacturer entity. If one
                    # already exists (e.g. from a previous onboarding attempt
                    # with a different company name), update it in place.
                    entity = ContactEntity.objects.filter(profile=contact_profile, is_manufacturer=True).first()
                    if entity:
                        entity.name = company_name
                        entity.email = contact_email
                        entity.website_urls = [website_url] if website_url else []
                        entity.is_supplier = True
                        entity.save(update_fields=["name", "email", "website_urls", "is_supplier", "updated_at"])
                    else:
                        entity = ContactEntity.objects.create(
                            profile=contact_profile,
                            name=company_name,
                            email=contact_email,
                            website_urls=[website_url] if website_url else [],
                            is_manufacturer=True,
                            is_supplier=True,
                        )

                    contact, created = ContactProfileContact.objects.get_or_create(
                        entity=entity,
                        name=contact_name,
                        email=contact_email,
                        defaults={"is_author": True},
                    )
                    if not created and not contact.is_author:
                        contact.is_author = True
                        contact.save(update_fields=["is_author"])

                    is_public = not team.can_be_private()

                    # Re-running onboarding with a different company name
                    # should update the existing product, not create a second one.
                    # Only rename if the team has exactly one product (wizard-created);
                    # if multiple exist (user created more via UI/API), fall back to get_or_create.
                    products = Product.objects.filter(team=team)
                    if products.count() == 1:
                        product = products.first()
                        product.name = company_name
                        product.save(update_fields=["name"])
                    else:
                        product, _ = Product.objects.get_or_create(
                            name=company_name, team=team, defaults={"is_public": is_public}
                        )
                    project, _ = Project.objects.get_or_create(
                        name="Main Project", team=team, defaults={"is_public": is_public}
                    )

                    component_metadata = create_default_component_metadata(
                        user=request.user, team_id=team.id, custom_metadata=None
                    )

                    component, component_created = Component.objects.get_or_create(
                        name="Main Component",
                        team=team,
                        defaults={
                            "component_type": Component.ComponentType.SBOM,
                            "metadata": component_metadata,
                            "visibility": Component.Visibility.PUBLIC if is_public else Component.Visibility.PRIVATE,
                        },
                    )

                    if component_created:
                        populate_component_metadata_native_fields(component, request.user, custom_metadata=None)
                        component.save()

                    product.projects.add(project)
                    project.components.add(component)

                    team.name = format_workspace_name(company_name)
                    team.has_completed_wizard = True
                    team.onboarding_goal = form.cleaned_data.get("goal", "")
                    team.save()

                    update_user_teams_session(request, request.user)
                    refresh_current_team_session(request, team)

                    request.session["wizard_component_id"] = component.id
                    request.session["wizard_company_name"] = company_name
                    request.session.modified = True
                    request.session.save()

                messages.success(request, "Your SBOM identity has been set up!")
                return redirect(f"{reverse('teams:onboarding_wizard')}?step=complete")
            except IntegrityError as e:
                log.warning(f"IntegrityError during onboarding for team {team.key}, company_name='{company_name}': {e}")
                messages.warning(
                    request,
                    "Setup could not be completed due to a conflict. Please try again or contact support.",
                )

        context = {
            "form": form,
            "current_step": "setup",
            "sbom_augmentation_url": sbom_augmentation_url,
            "billing_enabled": is_billing_enabled(),
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)
