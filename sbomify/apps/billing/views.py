"""
Views for handling billing-related functionality.
"""

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseServerError,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from sbomify.apps.core.utils import get_client_ip
from sbomify.apps.sboms.models import Product
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from . import billing_processing
from .billing_helpers import (
    RATE_LIMIT,
    RATE_LIMIT_PERIOD,
    acquire_checkout_lock,
    check_rate_limit,
    release_checkout_lock,
    require_team_owner,
)
from .forms import PublicEnterpriseContactForm
from .models import BillingPlan
from .stripe_client import StripeError, get_stripe_client
from .stripe_pricing_service import StripePricingService
from .stripe_sync import sync_subscription_from_stripe
from .tasks import send_enterprise_inquiry_email

logger = getLogger(__name__)

# Initialize shared instances
stripe_client = get_stripe_client()
pricing_service = StripePricingService()

VALID_FLOW_TYPES = {"subscription_update", "subscription_cancel"}


class _BaseEnterpriseContactView(View):
    """Base class for enterprise contact forms with shared form processing."""

    template_name: str = ""
    redirect_target: str = ""

    def _get_initial_data(self, request):
        """Override in subclasses for pre-filled data."""
        return {}

    def _get_send_kwargs(self, request, form_data):
        """Override in subclasses for email metadata."""
        return {}

    def get(self, request: HttpRequest) -> HttpResponse:
        form = PublicEnterpriseContactForm(initial=self._get_initial_data(request))
        return self._render(request, form)

    def _get_rate_limit_key(self, request: HttpRequest) -> str:
        """Return a rate-limit key. Subclasses can override."""
        if request.user.is_authenticated:
            return f"enterprise_contact:{request.user.pk}"
        return f"enterprise_contact_ip:{get_client_ip(request) or 'unknown'}"

    def post(self, request: HttpRequest) -> HttpResponse:
        if check_rate_limit(self._get_rate_limit_key(request), limit=RATE_LIMIT, period=RATE_LIMIT_PERIOD):
            messages.error(request, "Too many requests. Please try again later.")
            return redirect(self.redirect_target)

        form = PublicEnterpriseContactForm(request.POST, remoteip=get_client_ip(request))
        if form.is_valid():
            try:
                form_data = form.cleaned_data.copy()
                form_data["company_size_display"] = dict(form.fields["company_size"].choices).get(
                    form.cleaned_data["company_size"], "N/A"
                )
                form_data["primary_use_case_display"] = dict(form.fields["primary_use_case"].choices).get(
                    form.cleaned_data["primary_use_case"], "N/A"
                )

                send_kwargs = self._get_send_kwargs(request, form_data)
                send_enterprise_inquiry_email.send(form_data=form_data, **send_kwargs)

                messages.success(
                    request,
                    f"Thank you for your inquiry! We'll be in touch with "
                    f"{form.cleaned_data['company_name']} within 1-2 business days.",
                )
                return redirect(self.redirect_target)

            except Exception as e:
                logger.error("Failed to queue enterprise contact email: %s", e)
                messages.error(
                    request,
                    "There was an issue sending your inquiry. Please try again or contact us directly "
                    "at hello@sbomify.com",
                )
        return self._render(request, form)

    def _render(self, request, form):
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
                "debug": settings.DEBUG,
            },
        )


class EnterpriseContactView(LoginRequiredMixin, _BaseEnterpriseContactView):
    """Display enterprise contact form and handle submissions."""

    template_name = "billing/enterprise_contact.html.j2"
    redirect_target = "billing:enterprise_contact"

    def _get_initial_data(self, request):
        user = request.user
        initial_data = {}
        if user.first_name:
            initial_data["first_name"] = user.first_name
        if user.last_name:
            initial_data["last_name"] = user.last_name
        if user.email:
            initial_data["email"] = user.email
        return initial_data

    def _get_send_kwargs(self, request, form_data):
        return {
            "user_email": request.user.email,
            "user_name": request.user.get_full_name() or request.user.username,
            "is_public": False,
        }


class PublicEnterpriseContactView(_BaseEnterpriseContactView):
    """Public enterprise contact form accessible without login."""

    template_name = "billing/public_enterprise_contact.html.j2"

    @property
    def redirect_target(self):
        # Falls back to "/" for self-hosted instances without WEBSITE_BASE_URL
        return settings.WEBSITE_BASE_URL or "/"

    def _get_send_kwargs(self, request, form_data):
        return {
            "source_ip": get_client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT"),
            "is_public": True,
        }


class BillingRedirectView(LoginRequiredMixin, View):
    """Redirect to Stripe checkout based on selected plan in session."""

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = get_object_or_404(Team, key=team_key)

        is_owner, error_msg = require_team_owner(team, request.user)
        if not is_owner:
            messages.error(request, error_msg)
            return redirect("core:dashboard")

        selected_plan = request.session.get("selected_plan")
        if not selected_plan:
            return redirect("billing:select_plan", team_key=team_key)

        plan_key = selected_plan.get("key")
        billing_period = selected_plan.get("billing_period", "monthly")

        if not plan_key:
            messages.error(request, "No plan selected")
            return redirect("billing:select_plan", team_key=team_key)

        try:
            plan = BillingPlan.objects.get(key=plan_key)
        except BillingPlan.DoesNotExist:
            messages.error(request, "Invalid plan selected")
            return redirect("billing:select_plan", team_key=team_key)

        if plan.key == BillingPlan.KEY_ENTERPRISE:
            return redirect("billing:enterprise_contact")

        if billing_period not in ["monthly", "annual"]:
            messages.error(request, "Invalid billing period")
            return redirect("billing:select_plan", team_key=team_key)

        price_id = plan.stripe_price_monthly_id if billing_period == "monthly" else plan.stripe_price_annual_id
        if not price_id:
            messages.error(request, "Selected billing option is not available. Please try a different plan or period.")
            return redirect("billing:select_plan", team_key=team_key)

        billing_limits = team.billing_plan_limits or {}
        customer_id = billing_limits.get("stripe_customer_id")

        if not customer_id:
            try:
                customer = stripe_client.create_customer(
                    id=f"c_{team.key}",
                    email=request.user.email,
                    name=team.name,
                    metadata={"team_key": team.key},
                )
                customer_id = customer.id
            except StripeError as e:
                if "already exists" in str(e).lower():
                    try:
                        customer = stripe_client.get_customer(f"c_{team.key}")
                        customer_id = customer.id
                    except StripeError:
                        customer = stripe_client.create_customer(
                            email=request.user.email,
                            name=team.name,
                            metadata={"team_key": team.key},
                        )
                        customer_id = customer.id
                else:
                    logger.error("Failed to create customer for team %s: %s", team_key, e)
                    messages.error(request, "Failed to create billing account. Please try again.")
                    return redirect("billing:select_plan", team_key=team_key)
        else:
            try:
                stripe_client.get_customer(customer_id)
            except StripeError:
                customer = stripe_client.create_customer(
                    email=request.user.email,
                    name=team.name,
                    metadata={"team_key": team.key},
                )
                customer_id = customer.id

        if not acquire_checkout_lock(team.key):
            messages.info(request, "A checkout is already in progress. Please wait a moment and try again.")
            return redirect("billing:select_plan", team_key=team_key)

        try:
            success_url = (
                request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}"
            )
            cancel_url = request.build_absolute_uri(reverse("billing:select_plan", kwargs={"team_key": team_key}))

            session = stripe_client.create_checkout_session(
                customer_id=customer_id,
                price_id=price_id,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"team_key": team.key, "plan_key": plan.key},
            )

            return redirect(session.url)
        except StripeError as e:
            release_checkout_lock(team.key)
            logger.error("Failed to create checkout session for team %s: %s", team_key, e)
            messages.error(request, "Failed to initiate payment. Please try again.")
            return redirect("billing:select_plan", team_key=team_key)


class CreatePortalSessionView(LoginRequiredMixin, View):
    """Create a Stripe Billing Portal session and redirect to it."""

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = get_object_or_404(Team, key=team_key)

        is_owner, error_msg = require_team_owner(team, request.user)
        if not is_owner:
            messages.error(request, error_msg)
            return redirect("core:dashboard")

        stripe_customer_id = (team.billing_plan_limits or {}).get("stripe_customer_id")
        if not stripe_customer_id:
            messages.error(request, "No billing account found. Please subscribe to a plan first.")
            return redirect("billing:select_plan", team_key=team.key)

        sync_subscription_from_stripe(team, force_refresh=True)
        team.refresh_from_db()

        billing_limits = team.billing_plan_limits or {}
        sub_id = billing_limits.get("stripe_subscription_id")
        sub_status = billing_limits.get("subscription_status")
        cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)

        if sub_status == "canceled" or not sub_id:
            messages.info(request, "Your subscription has ended. Please select a new plan to continue.")
            return redirect("billing:select_plan", team_key=team.key)

        try:
            return_url = request.build_absolute_uri(reverse("core:dashboard"))

            flow_type = request.GET.get("flow_type")
            if flow_type and flow_type not in VALID_FLOW_TYPES:
                flow_type = None
            flow_data = None

            if sub_id and sub_status in ["active", "trialing"]:
                if flow_type == "subscription_update" and not cancel_at_period_end:
                    flow_data = {
                        "type": "subscription_update",
                        "subscription_update": {"subscription": sub_id},
                    }
                elif flow_type == "subscription_cancel" and not cancel_at_period_end:
                    flow_data = {
                        "type": "subscription_cancel",
                        "subscription_cancel": {"subscription": sub_id},
                        "after_completion": {
                            "type": "redirect",
                            "redirect": {"return_url": return_url},
                        },
                    }
                elif flow_type == "subscription_cancel" and cancel_at_period_end:
                    if not billing_limits.get("scheduled_downgrade_plan"):
                        with transaction.atomic():
                            team = Team.objects.select_for_update().get(pk=team.pk)
                            billing_limits = team.billing_plan_limits or {}
                            billing_limits["scheduled_downgrade_plan"] = "community"
                            team.billing_plan_limits = billing_limits
                            team.save()
                    messages.info(
                        request,
                        "Your subscription is already scheduled for cancellation at the end of the billing period.",
                    )
                    return redirect("billing:select_plan", team_key=team.key)
            elif flow_type == "subscription_cancel":
                messages.info(request, "Your subscription has ended. Please select a new plan to continue.")
                return redirect("billing:select_plan", team_key=team.key)

            logger.debug("Creating portal session for team %s", team_key)
            try:
                session = stripe_client.create_billing_portal_session(
                    stripe_customer_id, return_url, flow_data=flow_data
                )
                return redirect(session.url)
            except StripeError as e:
                error_str = str(e).lower()
                if "already set to be canceled" in error_str or "already scheduled for cancellation" in error_str:
                    logger.info("Subscription already cancelled in Stripe for team %s, syncing...", team_key)
                    sync_subscription_from_stripe(team, force_refresh=True)
                    team.refresh_from_db()
                    billing_limits = team.billing_plan_limits or {}

                    if not billing_limits.get("scheduled_downgrade_plan"):
                        with transaction.atomic():
                            team = Team.objects.select_for_update().get(pk=team.pk)
                            billing_limits = team.billing_plan_limits or {}
                            billing_limits["scheduled_downgrade_plan"] = "community"
                            billing_limits["cancel_at_period_end"] = True
                            team.billing_plan_limits = billing_limits
                            team.save()

                    messages.info(
                        request,
                        "Your subscription is already scheduled for cancellation at the end of the billing period. "
                        "Your current plan will remain active until then.",
                    )
                    return redirect("billing:select_plan", team_key=team.key)
                raise
        except StripeError as e:
            logger.error("Failed to create portal session for team %s: %s", team_key, e)
            messages.error(request, "Unable to access billing portal. Please contact support.")
            return redirect("billing:select_plan", team_key=team.key)


class SelectPlanView(LoginRequiredMixin, View):
    """Display plan selection page and handle plan selection."""

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = get_object_or_404(Team, key=team_key)

        is_owner, error_msg = require_team_owner(team, request.user)
        if not is_owner:
            messages.error(request, error_msg)
            return redirect("core:dashboard")

        stripe_pricing_data = pricing_service.get_all_plans_pricing(force_refresh=False)

        sync_subscription_from_stripe(team, force_refresh=False)
        team.refresh_from_db()

        return self._render_plan_page(request, team, team_key, stripe_pricing_data)

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from .billing_helpers import check_rate_limit

        if check_rate_limit(f"select_plan:{request.user.pk}", limit=RATE_LIMIT, period=RATE_LIMIT_PERIOD):
            messages.error(request, "Too many requests. Please try again later.")
            return redirect("billing:select_plan", team_key=team_key)

        team = get_object_or_404(Team, key=team_key)

        is_owner, error_msg = require_team_owner(team, request.user)
        if not is_owner:
            messages.error(request, error_msg)
            return redirect("core:dashboard")

        stripe_pricing_data = pricing_service.get_all_plans_pricing(force_refresh=False)

        plan_key = request.POST.get("plan")
        billing_period = request.POST.get("billing_period")

        if not plan_key:
            messages.error(request, "Please select a plan")
            return redirect("billing:select_plan", team_key=team_key)

        if billing_period and billing_period not in ["monthly", "annual"]:
            messages.error(request, "Invalid billing period selected")
            return redirect("billing:select_plan", team_key=team_key)

        try:
            plan = BillingPlan.objects.get(key=plan_key)
        except BillingPlan.DoesNotExist:
            messages.error(request, "Invalid plan selected")
            return redirect("billing:select_plan", team_key=team_key)

        if plan.key == BillingPlan.KEY_ENTERPRISE:
            return redirect("billing:enterprise_contact")

        sync_subscription_from_stripe(team, force_refresh=True)
        team.refresh_from_db()

        billing_limits = team.billing_plan_limits or {}
        stripe_sub_id = billing_limits.get("stripe_subscription_id")
        current_sub_status = billing_limits.get("subscription_status")
        cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
        scheduled_downgrade_plan = billing_limits.get("scheduled_downgrade_plan")

        if plan.key == BillingPlan.KEY_COMMUNITY and cancel_at_period_end:
            return self._handle_scheduled_downgrade(team, team_key, scheduled_downgrade_plan, request)

        if not stripe_sub_id or current_sub_status == "canceled":
            result = self._handle_subscription_cancel(team, team_key, plan, request)
            if result is not None:
                return result

        if stripe_sub_id and current_sub_status in ["active", "trialing"] and not cancel_at_period_end:
            return self._handle_active_subscription_portal(team_key, plan, request)

        if plan.key == BillingPlan.KEY_COMMUNITY:
            messages.warning(
                request,
                "Unable to process downgrade. Your subscription status may have changed. "
                "Please refresh the page and try again, or contact support if the issue persists.",
            )
            return redirect("billing:select_plan", team_key=team_key)

        if plan.key == BillingPlan.KEY_BUSINESS:
            return self._handle_checkout_creation(team, team_key, plan, billing_period, stripe_pricing_data, request)

        messages.error(request, "Unsupported plan selected")
        return redirect("billing:select_plan", team_key=team_key)

    def _handle_scheduled_downgrade(self, team, team_key, scheduled_downgrade_plan, request):
        """Handle case where subscription already has cancel_at_period_end set."""
        if scheduled_downgrade_plan:
            messages.info(
                request,
                "Your downgrade to Community is already scheduled. "
                "Your current plan will remain active until the end of your billing period.",
            )
        else:
            with transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = team.billing_plan_limits or {}
                billing_limits["scheduled_downgrade_plan"] = "community"
                team.billing_plan_limits = billing_limits
                team.save()
            messages.info(
                request,
                "Your subscription is already scheduled for cancellation at the end of the billing period. "
                "Your current plan will remain active until then.",
            )
        return redirect("billing:select_plan", team_key=team_key)

    def _handle_subscription_cancel(self, team, team_key, plan, request):
        """Handle plan selection when no active subscription exists."""
        if plan.key == BillingPlan.KEY_COMMUNITY:
            with transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                team.billing_plan = plan.key
                existing_limits = (team.billing_plan_limits or {}).copy()
                existing_limits.update(
                    {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                    }
                )
                team.billing_plan_limits = existing_limits
                team.save()
            messages.success(request, f"Successfully switched to {plan.name} plan")
            return redirect("core:dashboard")
        return None

    def _handle_active_subscription_portal(self, team_key, plan, request):
        """Redirect to Stripe portal for active subscription changes."""
        flow_type = "subscription_update"
        if plan.key == BillingPlan.KEY_COMMUNITY:
            flow_type = "subscription_cancel"

        return redirect(
            reverse("billing:create_portal_session", kwargs={"team_key": team_key}) + f"?flow_type={flow_type}"
        )

    def _handle_checkout_creation(self, team, team_key, plan, billing_period, stripe_pricing_data, request):
        """Create a Stripe checkout session for a new subscription."""
        if not billing_period:
            messages.error(request, "Please select a billing period")
            return redirect("billing:select_plan", team_key=team_key)

        if not acquire_checkout_lock(team_key):
            messages.info(request, "A checkout is already in progress. Please wait a moment and try again.")
            return redirect("billing:select_plan", team_key=team_key)

        plan_pricing = stripe_pricing_data.get(plan.key, {})

        coupon_id = None
        if billing_period == "monthly":
            coupon_id = plan_pricing.get("monthly_coupon_id")
        else:
            coupon_id = plan_pricing.get("annual_coupon_id")

        try:
            success_url = (
                request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}"
            )
            cancel_url = request.build_absolute_uri(reverse("core:dashboard"))
            session = pricing_service.create_checkout_session(
                team=team,
                user_email=request.user.email,
                plan=plan,
                billing_period=billing_period,
                success_url=success_url,
                cancel_url=cancel_url,
                coupon_id=coupon_id,
            )
            return redirect(session.url)
        except StripeError as e:
            release_checkout_lock(team_key)
            logger.error("Failed to create checkout session for team %s: %s", team_key, e)
            messages.error(request, "Failed to initiate payment. Please try again.")
            return redirect("billing:select_plan", team_key=team_key)

    def _render_plan_page(self, request, team, team_key, stripe_pricing_data):
        plans_list = list(BillingPlan.objects.all())
        order = {
            BillingPlan.KEY_COMMUNITY: 0,
            BillingPlan.KEY_BUSINESS: 1,
            BillingPlan.KEY_ENTERPRISE: 2,
        }
        plans = sorted(plans_list, key=lambda p: order.get(p.key, 99))

        stats = Product.objects.filter(team=team).aggregate(
            product_count=Count("id"),
            project_count=Count("project", distinct=True),
            component_count=Count("project__component", distinct=True),
        )
        product_count = stats["product_count"]
        project_count = stats["project_count"]
        component_count = stats["component_count"]

        billing_limits = team.billing_plan_limits or {}
        current_plan_key = team.billing_plan or BillingPlan.KEY_COMMUNITY
        is_subscribed = billing_limits.get("subscription_status") in ["active", "trialing"]

        for plan in plans:
            plan.stripe_pricing = stripe_pricing_data.get(plan.key, {})
            if plan.promo_message and "promo_message" not in plan.stripe_pricing:
                plan.stripe_pricing["promo_message"] = plan.promo_message

            plan_order = order.get(plan.key, 99)
            current_plan_order = order.get(current_plan_key, 99)
            plan.exceeds_downgrade_limits = False
            plan.downgrade_exceeded_resources = []

            if is_subscribed and plan_order < current_plan_order:
                if plan.max_products is not None and product_count > plan.max_products:
                    plan.exceeds_downgrade_limits = True
                    plan.downgrade_exceeded_resources.append(f"{product_count} products (limit: {plan.max_products})")

                if plan.max_projects is not None and project_count > plan.max_projects:
                    plan.exceeds_downgrade_limits = True
                    plan.downgrade_exceeded_resources.append(f"{project_count} projects (limit: {plan.max_projects})")

                if plan.max_components is not None and component_count > plan.max_components:
                    plan.exceeds_downgrade_limits = True
                    plan.downgrade_exceeded_resources.append(
                        f"{component_count} components (limit: {plan.max_components})"
                    )

        return render(
            request,
            "billing/select_plan.html.j2",
            {
                "plans": plans,
                "team_key": team_key,
                "team": team,
                "product_count": product_count,
                "project_count": project_count,
                "component_count": component_count,
            },
        )


class BillingReturnView(LoginRequiredMixin, View):
    """Handle return from Stripe checkout with proper error handling and idempotency."""

    def get(self, request: HttpRequest) -> HttpResponse:
        session_id = request.GET.get("session_id")
        if not session_id:
            messages.error(request, "Invalid checkout session")
            return redirect("core:dashboard")

        logger.info("Processing billing return with session_id: %s...%s", session_id[:8], session_id[-4:])

        team_key = None
        try:
            session = stripe_client.get_checkout_session(session_id)

            # Verify ownership BEFORE processing payment status
            team_key = session.metadata.get("team_key")
            if not team_key:
                logger.error("No team key found in session metadata")
                messages.error(request, "Invalid checkout session. Please contact support.")
                return redirect("core:dashboard")

            try:
                team_check = Team.objects.get(key=team_key)
                is_owner, _ = require_team_owner(team_check, request.user)
                if not is_owner:
                    logger.warning(
                        "User %s attempted billing_return for team %s without owner access",
                        request.user.pk,
                        team_key,
                    )
                    messages.error(request, "You do not have permission to manage billing for this workspace.")
                    return redirect("core:dashboard")
            except Team.DoesNotExist:
                logger.error("Team %s not found for checkout session %s", team_key, session_id)
                messages.error(request, "Workspace not found. Please contact support.")
                return redirect("core:dashboard")

            if session.payment_status != "paid":
                logger.error("Payment status was not 'paid': %s", session.payment_status)
                messages.error(request, "Payment was not completed. Please try again.")
                return redirect("billing:select_plan", team_key=team_key)

            subscription = stripe_client.get_subscription(session.subscription)
            customer = stripe_client.get_customer(session.customer)

            plan_key = session.metadata.get("plan_key", BillingPlan.KEY_BUSINESS)

            try:
                with transaction.atomic():
                    team = Team.objects.select_for_update().get(key=team_key)

                    # Re-verify ownership under lock to prevent TOCTOU race
                    is_owner, _ = require_team_owner(team, request.user)
                    if not is_owner:
                        messages.error(request, "You do not have permission to manage billing for this workspace.")
                        return redirect("core:dashboard")

                    existing_subscription_id = (team.billing_plan_limits or {}).get("stripe_subscription_id")
                    if existing_subscription_id == subscription.id:
                        logger.info("Subscription %s already processed for team %s", subscription.id, team_key)
                        messages.success(request, "Your subscription is already active.")
                        return redirect("core:dashboard")

                    try:
                        plan = BillingPlan.objects.get(key=plan_key)
                    except BillingPlan.DoesNotExist:
                        logger.error("Plan %s not found for team %s", plan_key, team_key)
                        messages.error(
                            request,
                            "Billing plan configuration error. Please contact support.",
                        )
                        return redirect("core:dashboard")

                    billing_period = "monthly"
                    items_data = getattr(subscription, "items", None)
                    if items_data and hasattr(items_data, "data") and items_data.data:
                        first_item = items_data.data[0]
                        if (
                            first_item.plan
                            and hasattr(first_item.plan, "interval")
                            and first_item.plan.interval == "year"
                        ):
                            billing_period = "annual"

                    billing_limits = {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                        "stripe_customer_id": customer.id,
                        "stripe_subscription_id": subscription.id,
                        "billing_period": billing_period,
                        "subscription_status": subscription.status,
                        "last_updated": timezone.now().isoformat(),
                    }

                    from .stripe_sync import get_period_end_from_subscription

                    next_billing_date = get_period_end_from_subscription(subscription, subscription.id)
                    if next_billing_date:
                        billing_limits["next_billing_date"] = next_billing_date

                    cancel_at = getattr(subscription, "cancel_at", None)
                    if hasattr(subscription, "cancel_at_period_end"):
                        billing_limits["cancel_at_period_end"] = subscription.cancel_at_period_end
                    elif cancel_at and cancel_at > 0:
                        billing_limits["cancel_at_period_end"] = True

                    team.billing_plan = plan.key
                    team.billing_plan_limits = billing_limits
                    team.save()

                    sync_subscription_from_stripe(team, force_refresh=True)

                    logger.info(
                        "Successfully updated billing information for team %s",
                        team_key,
                    )
                    messages.success(request, f"Successfully activated {plan.name} plan")
                    return redirect("core:dashboard")

            except Team.DoesNotExist:
                logger.error("Team %s not found for checkout session %s", team_key, session_id)
                messages.error(request, "Workspace not found. Please contact support.")
                return redirect("core:dashboard")

        except StripeError as e:
            logger.exception("Stripe error processing checkout return: %s", e)
            messages.error(
                request,
                "Payment processing error. Please contact support if the issue persists.",
            )
            return redirect("core:dashboard")
        except Exception as e:
            logger.exception("Unexpected error processing checkout return: %s", e)
            messages.error(request, "An unexpected error occurred. Please contact support.")
            return redirect("core:dashboard")
        finally:
            if team_key:
                release_checkout_lock(team_key)


class CheckoutSuccessView(TemplateView):
    """Handle successful checkout completion."""

    template_name = "billing/checkout_success.html.j2"


class CheckoutCancelView(TemplateView):
    """Handle cancelled checkout."""

    template_name = "billing/checkout_cancel.html.j2"


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    """Handle Stripe webhook events."""

    def post(self, request: HttpRequest) -> HttpResponse:
        content_type = request.content_type or ""
        if not content_type.startswith("application/json"):
            return HttpResponseBadRequest("Invalid content type")

        webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        if not webhook_secret:
            logger.error("STRIPE_WEBHOOK_SECRET is not configured — rejecting webhook")
            return HttpResponseServerError("Webhook endpoint not configured")

        signature = request.headers.get("Stripe-Signature")
        if not signature:
            logger.error("No Stripe signature found in request headers")
            return HttpResponseForbidden("No Stripe signature found")

        # Phase 1: Verify signature — 403 on failure (Stripe won't retry 4xx)
        try:
            event = stripe_client.construct_webhook_event(request.body, signature, webhook_secret)
        except (StripeError, stripe.error.SignatureVerificationError):
            logger.error("Webhook signature verification failed")
            return HttpResponseForbidden("Invalid signature")

        # Phase 2: Process event — 200 on business errors (acknowledged), 500 on unexpected (Stripe retries)
        try:
            if event.type == "checkout.session.completed":
                session = event.data.object
                billing_processing.handle_checkout_completed(session)
            elif event.type == "customer.subscription.updated":
                subscription = event.data.object
                billing_processing.handle_subscription_updated(subscription, event=event)
            elif event.type == "customer.subscription.deleted":
                subscription = event.data.object
                billing_processing.handle_subscription_deleted(subscription, event=event)
            elif event.type == "invoice.payment_succeeded":
                invoice = event.data.object
                billing_processing.handle_payment_succeeded(invoice, event=event)
            elif event.type == "invoice.payment_failed":
                invoice = event.data.object
                billing_processing.handle_payment_failed(invoice, event=event)
            else:
                logger.info("Unhandled event type: %s", event.type)

            return HttpResponse(status=200)

        except StripeError as e:
            logger.error("Stripe business logic error (acknowledged): %s", e)
            return HttpResponse(status=200)
        except Exception as e:
            logger.exception("Unexpected webhook error: %s", e)
            return HttpResponse(status=500)
