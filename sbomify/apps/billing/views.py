"""
Views for handling billing-related functionality
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sbomify.apps.sboms.models import Product
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from . import billing_processing
from .forms import PublicEnterpriseContactForm
from .models import BillingPlan
from .stripe_client import StripeClient, StripeError
from .stripe_pricing_service import StripePricingService
from .stripe_sync import sync_subscription_from_stripe
from .tasks import send_enterprise_inquiry_email

logger = getLogger(__name__)

# Initialize shared instances
stripe_client = StripeClient()
pricing_service = StripePricingService()


@login_required
def enterprise_contact(request: HttpRequest) -> HttpResponse:
    """Display enterprise contact form and handle submissions."""
    if request.method == "POST":
        form = PublicEnterpriseContactForm(request.POST)
        if form.is_valid():
            try:
                form_data = form.cleaned_data.copy()
                form_data["company_size_display"] = dict(form.fields["company_size"].choices).get(
                    form.cleaned_data["company_size"], "N/A"
                )
                form_data["primary_use_case_display"] = dict(form.fields["primary_use_case"].choices).get(
                    form.cleaned_data["primary_use_case"], "N/A"
                )

                send_enterprise_inquiry_email.send(
                    form_data=form_data,
                    user_email=request.user.email,
                    user_name=request.user.get_full_name() or request.user.username,
                    is_public=False,
                )

                messages.success(
                    request,
                    f"Thank you for your inquiry! We'll be in touch with "
                    f"{form.cleaned_data['company_name']} within 1-2 business days.",
                )
                return redirect("billing:enterprise_contact")

            except Exception as e:
                logger.error(f"Failed to queue enterprise contact email: {e}")
                messages.error(
                    request,
                    "There was an issue sending your inquiry. Please try again or contact us directly "
                    "at hello@sbomify.com",
                )
    else:
        user = request.user
        initial_data = {}
        if user.first_name:
            initial_data["first_name"] = user.first_name
        if user.last_name:
            initial_data["last_name"] = user.last_name
        if user.email:
            initial_data["email"] = user.email

        form = PublicEnterpriseContactForm(initial=initial_data)

    return render(
        request,
        "billing/enterprise_contact.html.j2",
        {
            "form": form,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
            "debug": settings.DEBUG,
        },
    )


def public_enterprise_contact(request: HttpRequest) -> HttpResponse:
    """Public enterprise contact form accessible without login."""
    if request.method == "POST":
        form = PublicEnterpriseContactForm(request.POST)
        if form.is_valid():
            try:
                form_data = form.cleaned_data.copy()
                form_data["company_size_display"] = dict(form.fields["company_size"].choices).get(
                    form.cleaned_data["company_size"], "N/A"
                )
                form_data["primary_use_case_display"] = dict(form.fields["primary_use_case"].choices).get(
                    form.cleaned_data["primary_use_case"], "N/A"
                )

                send_enterprise_inquiry_email.send(
                    form_data=form_data,
                    source_ip=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT"),
                    is_public=True,
                )

                messages.success(
                    request,
                    f"Thank you for your inquiry! We'll be in touch with "
                    f"{form.cleaned_data['company_name']} within 1-2 business days.",
                )
                return redirect("https://sbomify.com")

            except Exception as e:
                logger.error(f"Failed to queue public enterprise contact email: {e}")
                messages.error(
                    request,
                    "There was an issue sending your inquiry. Please try again or contact us directly "
                    "at hello@sbomify.com",
                )
    else:
        form = PublicEnterpriseContactForm()

    return render(
        request,
        "billing/public_enterprise_contact.html.j2",
        {
            "form": form,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
            "debug": settings.DEBUG,
        },
    )


@login_required
def billing_redirect(request: HttpRequest, team_key: str) -> HttpResponse:
    """Redirect to Stripe checkout based on selected plan in session."""
    team = get_object_or_404(Team, key=team_key)

    if not team.members.filter(member__user=request.user, member__role="owner").exists():
        messages.error(request, "Only team owners can change billing plans")
        return redirect("core:dashboard")

    # Get selected plan from session
    selected_plan = request.session.get("selected_plan")
    if not selected_plan:
        return redirect("billing:select_plan", team_key=team_key)

    plan_key = selected_plan.get("key")
    billing_period = selected_plan.get("billing_period", "monthly")

    if not plan_key:
        messages.error(request, "No plan selected")
        return redirect("billing:select_plan", team_key=team_key)

    # Get plan
    try:
        plan = BillingPlan.objects.get(key=plan_key)
    except BillingPlan.DoesNotExist:
        messages.error(request, "Invalid plan selected")
        return redirect("billing:select_plan", team_key=team_key)

    # Handle enterprise plan
    if plan.key == BillingPlan.KEY_ENTERPRISE:
        return redirect("billing:enterprise_contact")

    # Validate billing_period
    if billing_period not in ["monthly", "annual"]:
        messages.error(request, "Invalid billing period")
        return redirect("billing:select_plan", team_key=team_key)

    # Get price ID
    price_id = plan.stripe_price_monthly_id if billing_period == "monthly" else plan.stripe_price_annual_id
    if not price_id:
        raise ValueError(f"No price ID found for plan {plan_key} with billing period {billing_period}")

    # Get or create Stripe customer
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
            # If customer already exists with that ID, retrieve it
            if "already exists" in str(e).lower():
                try:
                    customer = stripe_client.get_customer(f"c_{team.key}")
                    customer_id = customer.id
                except StripeError:
                    # Create without ID
                    customer = stripe_client.create_customer(
                        email=request.user.email,
                        name=team.name,
                        metadata={"team_key": team.key},
                    )
                    customer_id = customer.id
            else:
                logger.error(f"Failed to create customer for team {team_key}: {e}")
                messages.error(request, "Failed to create billing account. Please try again.")
                return redirect("billing:select_plan", team_key=team_key)
    else:
        try:
            stripe_client.get_customer(customer_id)
        except StripeError:
            # Customer doesn't exist, create new one
            customer = stripe_client.create_customer(
                email=request.user.email,
                name=team.name,
                metadata={"team_key": team.key},
            )
            customer_id = customer.id

    # Create checkout session
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
        logger.error(f"Failed to create checkout session for team {team_key}: {e}")
        messages.error(request, "Failed to initiate payment. Please try again.")
        return redirect("billing:select_plan", team_key=team_key)


@login_required
def create_portal_session(request: HttpRequest, team_key: str) -> HttpResponse:
    """Create a Stripe Billing Portal session and redirect to it."""
    team = get_object_or_404(Team, key=team_key)

    if not team.members.filter(member__user=request.user, member__role="owner").exists():
        messages.error(request, "Only team owners can manage billing.")
        return redirect("core:dashboard")

    stripe_customer_id = (team.billing_plan_limits or {}).get("stripe_customer_id")
    if not stripe_customer_id:
        messages.error(request, "No billing account found. Please subscribe to a plan first.")
        return redirect("billing:select_plan", team_key=team.key)

    # Sync subscription data from Stripe to ensure we have latest status
    sync_subscription_from_stripe(team, force_refresh=True)
    team.refresh_from_db()

    # Get subscription info from synced data
    billing_limits = team.billing_plan_limits or {}
    sub_id = billing_limits.get("stripe_subscription_id")
    sub_status = billing_limits.get("subscription_status")
    cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)

    # If subscription is already fully canceled, redirect to select_plan to start fresh
    if sub_status == "canceled" or not sub_id:
        messages.info(request, "Your subscription has ended. Please select a new plan to continue.")
        return redirect("billing:select_plan", team_key=team.key)

    try:
        # Redirect back to dashboard after portal session
        return_url = request.build_absolute_uri(reverse("core:dashboard"))

        # Check for deep link flow type
        flow_type = request.GET.get("flow_type")
        flow_data = None

        # Only create flow_data if subscription is active/trialing and not already cancelling
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
                # Subscription is already scheduled for cancellation
                # Set scheduled_downgrade_plan if not already set (for consistency)
                if not billing_limits.get("scheduled_downgrade_plan"):
                    with transaction.atomic():
                        team = Team.objects.select_for_update().get(pk=team.pk)
                        billing_limits = team.billing_plan_limits or {}
                        billing_limits["scheduled_downgrade_plan"] = "community"
                        team.billing_plan_limits = billing_limits
                        team.save()
                messages.info(
                    request, "Your subscription is already scheduled for cancellation at the end of the billing period."
                )
                return redirect("billing:select_plan", team_key=team.key)
        elif flow_type == "subscription_cancel":
            # Subscription doesn't exist or is not active - can't cancel
            messages.info(request, "Your subscription has ended. Please select a new plan to continue.")
            return redirect("billing:select_plan", team_key=team.key)

        logger.debug(f"Creating portal session for team {team_key}")
        try:
            session = stripe_client.create_billing_portal_session(stripe_customer_id, return_url, flow_data=flow_data)
            return redirect(session.url)
        except StripeError as e:
            error_str = str(e).lower()
            # Handle case where subscription is already scheduled for cancellation
            if "already set to be canceled" in error_str or "already scheduled for cancellation" in error_str:
                logger.info(f"Subscription already cancelled in Stripe for team {team_key}, syncing...")
                # Force sync to update database
                sync_subscription_from_stripe(team, force_refresh=True)
                team.refresh_from_db()
                billing_limits = team.billing_plan_limits or {}

                # Update scheduled_downgrade_plan if not set
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
            # Re-raise other errors
            raise
    except StripeError as e:
        logger.error(f"Failed to create portal session for team {team_key}: {e}")
        messages.error(request, "Unable to access billing portal. Please contact support.")
        return redirect("billing:select_plan", team_key=team.key)


@login_required
def select_plan(request: HttpRequest, team_key: str) -> HttpResponse:
    """Display plan selection page and handle plan selection."""
    team = get_object_or_404(Team, key=team_key)

    if not team.members.filter(member__user=request.user, member__role="owner").exists():
        messages.error(request, "Only team owners can change billing plans")
        return redirect("core:dashboard")

    # Fetch pricing data once for both GET and POST
    stripe_pricing_data = pricing_service.get_all_plans_pricing(force_refresh=(request.method == "GET"))

    if request.method == "POST":
        plan_key = request.POST.get("plan")
        billing_period = request.POST.get("billing_period")

        # Validate plan_key
        if not plan_key:
            messages.error(request, "Please select a plan")
            return redirect("billing:select_plan", team_key=team_key)

        # Validate billing_period for paid plans
        if billing_period and billing_period not in ["monthly", "annual"]:
            messages.error(request, "Invalid billing period selected")
            return redirect("billing:select_plan", team_key=team_key)

        # Get plan with error handling
        try:
            plan = BillingPlan.objects.get(key=plan_key)
        except BillingPlan.DoesNotExist:
            messages.error(request, "Invalid plan selected")
            return redirect("billing:select_plan", team_key=team_key)

        # Handle enterprise plan (contact sales)
        if plan.key == BillingPlan.KEY_ENTERPRISE:
            return redirect("billing:enterprise_contact")

        # Sync subscription data from Stripe to ensure we have latest status
        sync_subscription_from_stripe(team, force_refresh=True)
        team.refresh_from_db()

        # Get subscription info from synced data
        billing_limits = team.billing_plan_limits or {}
        stripe_sub_id = billing_limits.get("stripe_subscription_id")
        current_sub_status = billing_limits.get("subscription_status")
        cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
        scheduled_downgrade_plan = billing_limits.get("scheduled_downgrade_plan")

        # Handle repeated downgrade attempts - check if cancellation is already scheduled
        # This handles both cases: scheduled via our system (has scheduled_downgrade_plan)
        # and scheduled via Stripe portal directly (only has cancel_at_period_end)
        if plan.key == BillingPlan.KEY_COMMUNITY and cancel_at_period_end:
            if scheduled_downgrade_plan:
                messages.info(
                    request,
                    "Your downgrade to Community is already scheduled. "
                    "Your current plan will remain active until the end of your billing period.",
                )
            else:
                # Cancelled via Stripe portal - set scheduled_downgrade_plan for consistency
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

        # Check if subscription is already cancelled or doesn't exist
        if not stripe_sub_id or current_sub_status == "canceled":
            # No active subscription, downgrade immediately
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

        # Only redirect to portal if subscription is active/trialing AND not scheduled for cancellation
        if stripe_sub_id and current_sub_status in ["active", "trialing"] and not cancel_at_period_end:
            flow_type = "subscription_update"
            if plan.key == BillingPlan.KEY_COMMUNITY:
                flow_type = "subscription_cancel"

            return redirect(
                reverse("billing:create_portal_session", kwargs={"team_key": team_key}) + f"?flow_type={flow_type}"
            )

        # If we get here and trying to downgrade, subscription might be in an invalid state
        if plan.key == BillingPlan.KEY_COMMUNITY:
            messages.warning(
                request,
                "Unable to process downgrade. Your subscription status may have changed. "
                "Please refresh the page and try again, or contact support if the issue persists.",
            )
            return redirect("billing:select_plan", team_key=team_key)

        # Handle community plan (no active subscription)
        if plan.key == BillingPlan.KEY_COMMUNITY:
            # No active subscription, switch immediately
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

        # Handle business plan (paid, requires Stripe checkout or update)
        elif plan.key == BillingPlan.KEY_BUSINESS:
            # Validate billing_period is required for business plan
            if not billing_period:
                messages.error(request, "Please select a billing period")
                return redirect("billing:select_plan", team_key=team_key)

            plan_pricing = stripe_pricing_data.get(plan.key, {})

            # Create checkout session
            coupon_id = None
            if billing_period == "monthly":
                coupon_id = plan_pricing.get("monthly_coupon_id")
            else:
                coupon_id = plan_pricing.get("annual_coupon_id")

            # Create checkout session
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
                logger.error(f"Failed to create checkout session for team {team_key}: {e}")
                messages.error(request, f"Failed to initiate payment: {str(e)}")
                return redirect("billing:select_plan", team_key=team_key)
        else:
            messages.error(request, "Unsupported plan selected")
            return redirect("billing:select_plan", team_key=team_key)

    # GET request - display plans
    # Sync subscription data from Stripe (will update next_billing_date if missing)
    sync_subscription_from_stripe(team, force_refresh=False)
    team.refresh_from_db()

    plans_list = list(BillingPlan.objects.all())
    # Use model constants for ordering
    order = {
        BillingPlan.KEY_COMMUNITY: 0,
        BillingPlan.KEY_BUSINESS: 1,
        BillingPlan.KEY_ENTERPRISE: 2,
    }
    plans = sorted(plans_list, key=lambda p: order.get(p.key, 99))

    # Optimize N+1 queries with aggregations
    stats = Product.objects.filter(team=team).aggregate(
        product_count=Count("id"),
        project_count=Count("project", distinct=True),
        component_count=Count("project__component", distinct=True),
    )
    product_count = stats["product_count"]
    project_count = stats["project_count"]
    component_count = stats["component_count"]

    # Check if downgrade would exceed limits for each plan
    billing_limits = team.billing_plan_limits or {}
    current_plan_key = team.billing_plan or BillingPlan.KEY_COMMUNITY
    is_subscribed = billing_limits.get("subscription_status") in ["active", "trialing"]

    for plan in plans:
        plan.stripe_pricing = stripe_pricing_data.get(plan.key, {})
        if plan.promo_message and "promo_message" not in plan.stripe_pricing:
            plan.stripe_pricing["promo_message"] = plan.promo_message

        # Check if downgrade to this plan would exceed limits
        # Only check if user is subscribed and trying to downgrade (lower plan key order)
        plan_order = order.get(plan.key, 99)
        current_plan_order = order.get(current_plan_key, 99)
        plan.exceeds_downgrade_limits = False
        plan.downgrade_exceeded_resources = []

        if is_subscribed and plan_order < current_plan_order:
            # This is a downgrade - check if current usage exceeds target plan limits
            if plan.max_products is not None and product_count > plan.max_products:
                plan.exceeds_downgrade_limits = True
                plan.downgrade_exceeded_resources.append(f"{product_count} products (limit: {plan.max_products})")

            if plan.max_projects is not None and project_count > plan.max_projects:
                plan.exceeds_downgrade_limits = True
                plan.downgrade_exceeded_resources.append(f"{project_count} projects (limit: {plan.max_projects})")

            if plan.max_components is not None and component_count > plan.max_components:
                plan.exceeds_downgrade_limits = True
                plan.downgrade_exceeded_resources.append(f"{component_count} components (limit: {plan.max_components})")

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
            "csrf_token": get_token(request),
        },
    )


@login_required
def billing_return(request: HttpRequest) -> HttpResponse:
    """Handle return from Stripe checkout with proper error handling and idempotency."""
    session_id = request.GET.get("session_id")
    if not session_id:
        messages.error(request, "Invalid checkout session")
        return redirect("core:dashboard")

    logger.info("Processing billing return with session_id: %s", session_id)

    try:
        # Use stripe_client instead of direct stripe import
        session = stripe_client.get_checkout_session(session_id)

        if session.payment_status != "paid":
            logger.error("Payment status was not 'paid': %s", session.payment_status)
            messages.error(request, "Payment was not completed. Please try again.")
            team_key_redirect = session.metadata.get("team_key", "")
            return redirect("billing:select_plan", team_key=team_key_redirect)

        # Get subscription and customer using stripe_client
        subscription = stripe_client.get_subscription(session.subscription)
        customer = stripe_client.get_customer(session.customer)

        team_key = session.metadata.get("team_key")
        if not team_key:
            logger.error("No team key found in session metadata")
            messages.error(request, "Invalid checkout session. Please contact support.")
            return redirect("core:dashboard")

        # Get plan key from metadata, fallback to business for compatibility
        plan_key = session.metadata.get("plan_key", BillingPlan.KEY_BUSINESS)

        # Use transaction with select_for_update to prevent race conditions
        try:
            with transaction.atomic():
                team = Team.objects.select_for_update().get(key=team_key)

                # Idempotency check: if subscription already processed, skip update
                existing_subscription_id = (team.billing_plan_limits or {}).get("stripe_subscription_id")
                if existing_subscription_id == subscription.id:
                    logger.info(f"Subscription {subscription.id} already processed for team {team_key}")
                    messages.success(request, "Your subscription is already active.")
                    return redirect("core:dashboard")

                # Get plan with error handling
                try:
                    plan = BillingPlan.objects.get(key=plan_key)
                except BillingPlan.DoesNotExist:
                    logger.error(f"Plan {plan_key} not found for team {team_key}")
                    messages.error(
                        request,
                        "Billing plan configuration error. Please contact support.",
                    )
                    return redirect("core:dashboard")

                # Determine billing period from subscription
                billing_period = "monthly"
                items_data = getattr(subscription, "items", None)
                if items_data and hasattr(items_data, "data") and items_data.data:
                    first_item = items_data.data[0]
                    if first_item.plan and hasattr(first_item.plan, "interval") and first_item.plan.interval == "year":
                        billing_period = "annual"

                # Update team billing information
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

                # Add next billing date using centralized utility
                # This will use cancel_at if subscription is scheduled to cancel, otherwise period_end
                from .stripe_sync import get_period_end_from_subscription

                next_billing_date = get_period_end_from_subscription(subscription, subscription.id)
                if next_billing_date:
                    billing_limits["next_billing_date"] = next_billing_date

                # Sync cancel_at_period_end from subscription
                # Also check cancel_at to handle cases where cancel_at_period_end is False but cancel_at is set
                cancel_at = getattr(subscription, "cancel_at", None)
                if hasattr(subscription, "cancel_at_period_end"):
                    billing_limits["cancel_at_period_end"] = subscription.cancel_at_period_end
                elif cancel_at and cancel_at > 0:
                    # If cancel_at is set, subscription is scheduled to cancel
                    billing_limits["cancel_at_period_end"] = True

                team.billing_plan = plan.key
                team.billing_plan_limits = billing_limits
                team.save()

                # Sync subscription data to ensure everything is up-to-date
                from sbomify.apps.billing.stripe_sync import sync_subscription_from_stripe

                sync_subscription_from_stripe(team, force_refresh=True)

                logger.info(
                    "Successfully updated billing information for team %s",
                    team_key,
                )
                messages.success(request, f"Successfully activated {plan.name} plan")
                return redirect("core:dashboard")

        except Team.DoesNotExist:
            logger.error(f"Team {team_key} not found for checkout session {session_id}")
            messages.error(request, "Team not found. Please contact support.")
            return redirect("core:dashboard")

    except StripeError as e:
        logger.exception(f"Stripe error processing checkout return: {str(e)}")
        messages.error(
            request,
            "Payment processing error. Please contact support if the issue persists.",
        )
        return redirect("core:dashboard")
    except Exception as e:
        logger.exception(f"Unexpected error processing checkout return: {str(e)}")
        messages.error(request, "An unexpected error occurred. Please contact support.")
        return redirect("core:dashboard")


@require_http_methods(["GET"])
def checkout_success(request: HttpRequest) -> HttpResponse:
    """Handle successful checkout completion."""
    return render(request, "billing/checkout_success.html.j2")


@require_http_methods(["GET"])
def checkout_cancel(request: HttpRequest) -> HttpResponse:
    """Handle cancelled checkout."""
    return render(request, "billing/checkout_cancel.html.j2")


# nosemgrep: python.django.security.audit.csrf-exempt.no-csrf-exempt
# CSRF exempt required for Stripe webhooks - webhook signature verification provides security
@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """Handle Stripe webhook events."""
    try:
        signature = request.headers.get("Stripe-Signature")
        if not signature:
            logger.error("No Stripe signature found in request headers")
            return HttpResponseForbidden("No Stripe signature found")

        event = stripe_client.construct_webhook_event(request.body, signature, settings.STRIPE_WEBHOOK_SECRET)

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
            logger.info(f"Unhandled event type: {event.type}")

        return HttpResponse(status=200)

    except StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        return HttpResponseForbidden("Payment processing error")
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        return HttpResponseForbidden("An unexpected error occurred")
