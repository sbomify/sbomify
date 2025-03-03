import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from sbomify.logging import getLogger
from sboms.models import Component, Product, Project
from teams.models import Team

from . import billing_processing
from .models import BillingPlan

logger = getLogger(__name__)


# Create your views here.
@login_required
def select_plan(request: HttpRequest, team_key: str):
    "Display plan selection page"
    team = get_object_or_404(Team, key=team_key)

    # Check if user is team owner
    if not team.members.filter(member__user=request.user, member__role="owner").exists():
        return redirect("core:dashboard")

    if request.method == "POST":
        plan_key = request.POST.get("plan")
        billing_period = request.POST.get("billing_period")

        plan = BillingPlan.objects.get(key=plan_key)

        # Check if downgrading is possible
        current_plan = BillingPlan.objects.get(key=team.billing_plan) if team.billing_plan else None
        if (
            current_plan
            and current_plan.max_products
            and (not plan.max_products or plan.max_products < current_plan.max_products)
        ):
            can_downgrade, message = billing_processing.can_downgrade_to_plan(team, plan)
            if not can_downgrade:
                messages.error(request, message)
                return redirect("billing:select_plan", team_key=team_key)

        if plan.key == "community":
            # Update team with community plan
            team.billing_plan = plan.key
            team.billing_plan_limits = {
                "max_products": plan.max_products,
                "max_projects": plan.max_projects,
                "max_components": plan.max_components,
            }
            team.save()
            messages.success(request, f"Successfully switched to {plan.name} plan")
            return redirect("core:dashboard")

        elif plan.key == "enterprise":
            # Just show the contact information page
            return render(request, "billing/enterprise_contact.html", {"team_key": team_key})

        elif plan.key == "business":
            # Store the selection in session for use in billing_redirect
            request.session["selected_plan"] = {
                "key": plan.key,
                "billing_period": billing_period,
                "limits": {
                    "max_products": plan.max_products,
                    "max_projects": plan.max_projects,
                    "max_components": plan.max_components,
                },
            }
            return redirect("billing:billing_redirect", team_key=team_key)

    plans = BillingPlan.objects.all()

    # Get current usage counts
    product_count = Product.objects.filter(team=team).count()
    project_count = Project.objects.filter(product__team=team).count()
    component_count = Component.objects.filter(project__product__team=team).count()

    return render(
        request,
        "billing/select_plan.html",
        {
            "plans": plans,
            "team_key": team_key,
            "team": team,
            "product_count": product_count,
            "project_count": project_count,
            "component_count": component_count,
        },
    )


@login_required
def billing_redirect(request: HttpRequest, team_key: str) -> HttpResponse:
    """Redirect to Stripe checkout."""
    team = get_object_or_404(Team, key=team_key)
    if not team.members.filter(member__user=request.user, member__role="owner").exists():
        messages.error(request, "Only team owners can change billing plans")
        return redirect("core:dashboard")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    selected_plan = request.session.get("selected_plan")
    if not selected_plan:
        return redirect("billing:select_plan", team_key=team_key)

    customer_id = f"c_{team_key}"  # Use team key instead of user id

    # First try to fetch the customer, create if doesn't exist
    try:
        customer = stripe.Customer.retrieve(customer_id)
    except stripe.error.InvalidRequestError as e:
        if "No such customer" in str(e):
            # Create a new customer
            customer = stripe.Customer.create(
                id=customer_id,
                email=request.user.email,  # Use team owner's email
                name=team.name,  # Use team name
                metadata={"team_key": team_key},
            )
        else:
            raise

    # Get the price ID based on billing period
    plan = BillingPlan.objects.get(key=selected_plan["key"])
    if selected_plan["billing_period"] == "monthly":
        selected_price_id = plan.stripe_price_monthly_id
    else:
        selected_price_id = plan.stripe_price_annual_id

    if not selected_price_id:
        raise ValueError(
            f"No price ID found for plan {selected_plan['key']} with billing period {selected_plan['billing_period']}"
        )

    # Create a checkout session for initial subscription
    session = stripe.checkout.Session.create(
        customer=customer.id,
        success_url=request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=request.build_absolute_uri(reverse("core:dashboard")),
        mode="subscription",
        line_items=[{"price": selected_price_id, "quantity": 1}],
        metadata={"team_key": team_key},
    )

    # Clear the session data
    del request.session["selected_plan"]

    return redirect(session.url)


@login_required
def billing_return(request: HttpRequest):
    "Handle return from Stripe checkout"
    session_id = request.GET.get("session_id")
    logger.info("Processing billing return with session_id: %s", session_id)

    if session_id:
        try:
            # Retrieve the checkout session
            session = stripe.checkout.Session.retrieve(session_id)

            # Only proceed if payment was successful
            if session.payment_status == "paid":
                # Get the subscription from the session
                subscription = stripe.Subscription.retrieve(session.subscription)
                customer = stripe.Customer.retrieve(session.customer)

                # Update team billing information
                team_key = session.metadata.get("team_key")
                if team_key:
                    team = Team.objects.get(key=team_key)
                    plan = BillingPlan.objects.get(key="business")

                    # Get billing period from subscription items
                    items_data = subscription.get("items", {}).get("data", [])

                    # Get the billing period from the subscription
                    billing_period = "monthly"  # default
                    if items_data:
                        first_item = items_data[0]
                        if first_item.get("plan", {}).get("interval") == "year":
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

                    team.billing_plan = plan.key
                    team.billing_plan_limits = billing_limits
                    team.save()
                    logger.info("Successfully updated billing information for team %s", team_key)
                    return redirect("core:dashboard")
                else:
                    logger.error("No team key found in session metadata")
            else:
                logger.error("Payment status was not 'paid': %s", session.payment_status)

        except (stripe.error.StripeError, Team.DoesNotExist) as e:
            logger.exception("Error processing subscription: %s", str(e))

    # If anything fails, redirect to dashboard with an error message
    return redirect("core:dashboard")


@csrf_exempt
def stripe_webhook(request: HttpRequest):
    """Handle Stripe webhook events"""
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)

        logger.info(f"Processing Stripe webhook event: {event.type}")

        # Handle specific event types
        if event.type == "checkout.session.completed":
            billing_processing.handle_checkout_completed(event.data.object)

        elif event.type == "customer.subscription.updated":
            billing_processing.handle_subscription_updated(event.data.object)

        elif event.type == "customer.subscription.deleted":
            billing_processing.handle_subscription_deleted(event.data.object)

        elif event.type == "invoice.payment_failed":
            billing_processing.handle_payment_failed(event.data.object)

        elif event.type == "invoice.paid":
            billing_processing.handle_payment_succeeded(event.data.object)

        return HttpResponse(status=200)

    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error(f"Invalid webhook signature: {str(e)}")
        return HttpResponse(status=400)
    except Exception as e:
        logger.exception(f"Error processing webhook: {str(e)}")
        return HttpResponse(status=400)
