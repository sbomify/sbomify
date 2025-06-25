"""
Module for handling Stripe billing webhook events and related processing
"""

import datetime
from functools import wraps

import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone

from sbomify.logging import getLogger
from sboms.models import Component, Product, Project
from teams.models import Member, Team

from . import email_notifications
from .config import is_billing_enabled
from .models import BillingPlan
from .stripe_client import StripeClient, StripeError

logger = getLogger(__name__)

# Initialize Stripe client
stripe_client = StripeClient()


def check_billing_limits(resource_type: str):
    """
    Decorator to check if a team has reached their billing plan limits.

    Args:
        resource_type: Type of resource being created ('product', 'project', or 'component')
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Only check limits for POST requests
            if request.method != "POST":
                return view_func(request, *args, **kwargs)

            # If billing is disabled, bypass all checks
            if not is_billing_enabled():
                return view_func(request, *args, **kwargs)

            # Get current team
            team_key = request.session.get("current_team", {}).get("key")
            if not team_key:
                return HttpResponseForbidden("No team selected")

            try:
                team = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                return HttpResponseForbidden("Team not found")

            # Check if team has a billing plan
            if not team.billing_plan:
                return HttpResponseForbidden("No active billing plan")

            try:
                plan = BillingPlan.objects.get(key=team.billing_plan)
            except BillingPlan.DoesNotExist:
                return HttpResponseForbidden("Invalid billing plan")

            # Check limits based on resource type
            if resource_type == "product":
                current_count = Product.objects.filter(team=team).count()
                max_allowed = plan.max_products
            elif resource_type == "project":
                current_count = Project.objects.filter(team=team).count()
                max_allowed = plan.max_projects
            elif resource_type == "component":
                current_count = Component.objects.filter(team=team).count()
                max_allowed = plan.max_components
            else:
                return HttpResponseForbidden("Invalid resource type")

            # Enterprise plan or None (unlimited) values have no limits
            if plan.key == "enterprise" or max_allowed is None:
                return view_func(request, *args, **kwargs)

            # Check if limit is reached
            if current_count >= max_allowed:
                error_message = f"You have reached the maximum {max_allowed} {resource_type}s allowed by your plan"

                # Return JSON response for AJAX requests
                is_ajax = (
                    request.headers.get("Accept") == "application/json"
                    or request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
                )

                if is_ajax:
                    return JsonResponse({"error": error_message, "limit_reached": True}, status=403)

                # Traditional response for non-AJAX requests
                return HttpResponseForbidden(error_message)

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


def _handle_stripe_error(func):
    """Decorator to handle Stripe errors consistently."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except stripe.error.CardError as e:
            logger.error(f"Card error: {str(e)}")
            raise StripeError(f"Card error: {e.user_message}")
        except stripe.error.RateLimitError as e:
            logger.error(f"Rate limit error: {str(e)}")
            raise StripeError("Too many requests made to Stripe API")
        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid request error: {str(e)}")
            raise StripeError(f"Invalid request: {str(e)}")
        except stripe.error.AuthenticationError as e:
            logger.error(f"Authentication error: {str(e)}")
            raise StripeError("Authentication with Stripe failed")
        except stripe.error.APIConnectionError as e:
            logger.error(f"API connection error: {str(e)}")
            raise StripeError("Could not connect to Stripe API")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {str(e)}")
            raise StripeError(f"Stripe error: {str(e)}")
        except Exception as e:
            logger.exception(f"Unexpected error: {str(e)}")
            raise StripeError(f"Unexpected error: {str(e)}")

    return wrapper


def verify_stripe_webhook(request):
    """Verify that the webhook request is from Stripe."""
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        logger.error("No Stripe signature found in request headers")
        return False

    try:
        event = stripe.Webhook.construct_event(request.body, signature, settings.STRIPE_WEBHOOK_SECRET)
        return event
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid Stripe signature")
        return False
    except Exception as e:
        logger.error(f"Error verifying Stripe webhook: {str(e)}")
        return False


@_handle_stripe_error
def handle_trial_period(subscription, team):
    """Handle trial period status and notifications."""
    if subscription.status == "trialing" and subscription.trial_end:
        trial_end = datetime.datetime.fromtimestamp(subscription.trial_end, tz=datetime.timezone.utc)
        days_remaining = (trial_end - timezone.now()).days

        # Update trial status
        team.billing_plan_limits.update(
            {"is_trial": True, "trial_end": subscription.trial_end, "trial_days_remaining": days_remaining}
        )

        # Handle trial ending soon
        if days_remaining <= settings.TRIAL_ENDING_NOTIFICATION_DAYS:
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_trial_ending(team, member, days_remaining)
                logger.info(f"Trial ending notification sent for team {team.key} to {member.user.email}")

        # Handle trial expired
        if days_remaining <= 0:
            team.billing_plan_limits.update({"is_trial": False, "subscription_status": "canceled"})
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_trial_expired(team, member)
                logger.info(f"Trial expired notification sent for team {team.key} to {member.user.email}")

        team.save()
        return True
    return False


@_handle_stripe_error
def handle_subscription_updated(subscription):
    """Handle subscription updated events."""
    try:
        # First try to find by subscription ID
        try:
            team = Team.objects.get(billing_plan_limits__stripe_subscription_id=subscription.id)
        except Team.DoesNotExist:
            # Recovery: Try to find team by customer ID
            try:
                team = Team.objects.get(billing_plan_limits__stripe_customer_id=subscription.customer)
                logger.warning(
                    "Found team by customer ID instead of subscription ID for subscription %s",
                    subscription.id,
                )
            except Team.DoesNotExist:
                # Recovery: Try to find team by metadata in customer
                try:
                    customer = stripe_client.get_customer(subscription.customer)
                    if customer.metadata and "team_key" in customer.metadata:
                        team = Team.objects.get(key=customer.metadata["team_key"])
                        logger.warning(f"Found team by customer metadata for subscription {subscription.id}")
                    else:
                        raise Team.DoesNotExist("No team key in customer metadata")
                except Exception as e:
                    logger.error(f"Failed to recover team for subscription {subscription.id}: {str(e)}")
                    raise StripeError(f"No team found for subscription {subscription.id}")

        # Validate subscription status
        valid_statuses = ["trialing", "active", "past_due", "canceled", "incomplete", "incomplete_expired"]
        if subscription.status not in valid_statuses:
            raise StripeError(f"Invalid subscription status: {subscription.status}")

        # Update subscription status and ensure subscription ID is set
        team.billing_plan_limits["subscription_status"] = subscription.status
        team.billing_plan_limits["stripe_subscription_id"] = subscription.id  # Ensure this is set
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()

        # Handle trial period
        if subscription.status == "trialing" and subscription.trial_end:
            handle_trial_period(subscription, team)

        # Update billing plan based on subscription's product
        if subscription.items.data:
            try:
                # Get plan from metadata
                plan_key = subscription.metadata.get("plan_key", "business")
                plan = BillingPlan.objects.get(key=plan_key)
                team.billing_plan = plan.key
                team.billing_plan_limits.update(
                    {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                    }
                )
            except BillingPlan.DoesNotExist:
                logger.error(f"Billing plan {plan_key} not found")
                raise StripeError(f"Billing plan {plan_key} not found")

        # Handle specific status transitions
        if subscription.status == "past_due":
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_payment_past_due(team, member)
                logger.warning(f"Payment past due notification sent for team {team.key} to {member.user.email}")

        elif subscription.status == "active":
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_payment_succeeded(team, member)
                logger.info(f"Payment restored notification sent for team {team.key} to {member.user.email}")

        elif subscription.status == "canceled":
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_subscription_cancelled(team, member)
                logger.info(f"Subscription cancelled notification sent for team {team.key} to {member.user.email}")

        elif subscription.status in ["incomplete", "incomplete_expired"]:
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_payment_failed(team, member, None)
                logger.warning(
                    f"Initial payment failed notification sent for team {team.key} " f"to {member.user.email}"
                )

        team.save()
        logger.info(f"Updated subscription status for team {team.key} to {subscription.status}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {subscription.id}")
        raise StripeError(f"No team found for subscription {subscription.id}")
    except Exception as e:
        logger.exception(f"Error processing subscription update: {str(e)}")
        raise StripeError(f"Error processing subscription update: {str(e)}")


@_handle_stripe_error
def handle_subscription_deleted(subscription):
    """Handle subscription deletion events"""
    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=subscription.id)

        # Update subscription status
        team.billing_plan_limits["subscription_status"] = "canceled"
        # Add/update the last_updated timestamp
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()

        # Save the changes
        team.save()

        # Notify team owners
        team_owners = Member.objects.filter(team=team, role="owner")
        for member in team_owners:
            email_notifications.notify_subscription_ended(team, member)
            logger.info(f"Subscription ended notification sent for team {team.key} to {member.user.email}")

        logger.info(f"Subscription canceled for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {subscription.id}")
        raise StripeError(f"No team found for subscription {subscription.id}")


@_handle_stripe_error
def handle_payment_failed(invoice):
    """Handle payment failure events"""
    if not hasattr(invoice, "subscription") or not invoice.subscription:
        logger.error("No subscription found in invoice")
        return

    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=invoice.subscription)

        # Update status and timestamp
        team.billing_plan_limits["subscription_status"] = "past_due"
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
        team.save()

        # Notify team owners
        team_owners = Member.objects.filter(team=team, role="owner")
        for member in team_owners:
            email_notifications.notify_payment_failed(team, member, invoice.id)
            logger.warning(f"Payment failed notification sent for team {team.key} to {member.user.email}")

        logger.warning(f"Payment failed for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {invoice.subscription}")
        raise StripeError(f"No team found for subscription {invoice.subscription}")


@_handle_stripe_error
def handle_payment_succeeded(invoice):
    """Handle payment success events"""
    if not hasattr(invoice, "subscription") or not invoice.subscription:
        logger.error("No subscription found in invoice")
        return

    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=invoice.subscription)

        # Update status and timestamp
        team.billing_plan_limits["subscription_status"] = "active"
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
        team.save()

        # Notify team owners
        team_owners = Member.objects.filter(team=team, role="owner")
        for member in team_owners:
            email_notifications.notify_payment_succeeded(team, member)
            logger.info(f"Payment successful notification sent for team {team.key} to {member.user.email}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {invoice.subscription}")
        raise StripeError(f"No team found for subscription {invoice.subscription}")


def can_downgrade_to_plan(team, plan):
    """Check if team can downgrade to specified plan."""
    # If the plan has no limits, always allow downgrade
    if plan.max_products is None and plan.max_projects is None and plan.max_components is None:
        return True, ""

    current_usage = {
        "products": Product.objects.filter(team=team).count(),
        "projects": Project.objects.filter(team=team).count(),
        "components": Component.objects.filter(team=team).count(),
    }

    exceeded_limits = []
    if plan.max_products is not None and current_usage["products"] > plan.max_products:
        exceeded_limits.append(f"products ({current_usage['products']} > {plan.max_products})")
    if plan.max_projects is not None and current_usage["projects"] > plan.max_projects:
        exceeded_limits.append(f"projects ({current_usage['projects']} > {plan.max_projects})")
    if plan.max_components is not None and current_usage["components"] > plan.max_components:
        exceeded_limits.append(f"components ({current_usage['components']} > {plan.max_components})")

    if exceeded_limits:
        message = f"Current usage exceeds plan limits: {', '.join(exceeded_limits)}"
        return False, message

    return True, ""


@_handle_stripe_error
def handle_checkout_completed(session):
    """Handle checkout session completed events."""
    if session.payment_status != "paid":
        logger.error("Payment status was not 'paid': %s", session.payment_status)
        return

    team_key = session.metadata.get("team_key")
    if not team_key:
        logger.error("No team key found in session metadata")
        return

    try:
        team = Team.objects.get(key=team_key)

        # Get plan from metadata
        plan_key = session.metadata.get("plan_key", "business")
        plan = BillingPlan.objects.get(key=plan_key)

        # Get the subscription
        subscription = stripe_client.get_subscription(session.subscription)

        # Update team billing information
        team.billing_plan = plan.key
        billing_limits = {
            "max_products": plan.max_products,
            "max_projects": plan.max_projects,
            "max_components": plan.max_components,
            "stripe_customer_id": session.customer,
            "stripe_subscription_id": session.subscription,
            "subscription_status": subscription.status,
            "last_updated": timezone.now().isoformat(),
        }

        # Handle trial period
        if subscription.status == "trialing":
            billing_limits.update({"is_trial": True, "trial_end": subscription.trial_end})

        team.billing_plan_limits = billing_limits
        team.save()

        # Handle trial period notifications
        if subscription.status == "trialing":
            handle_trial_period(subscription, team)

        logger.info("Successfully processed checkout session for team %s", team_key)

    except Team.DoesNotExist:
        logger.error(f"Team with key {team_key} not found")
        raise StripeError(f"Team with key {team_key} not found")
    except BillingPlan.DoesNotExist:
        logger.error(f"Billing plan {plan_key} not found")
        raise StripeError(f"Billing plan {plan_key} not found")
    except Exception as e:
        logger.error(f"Error processing checkout: {str(e)}")
        raise StripeError(f"Error processing checkout: {str(e)}")


@_handle_stripe_error
def stripe_webhook(request):
    """Handle Stripe webhook events."""
    event = verify_stripe_webhook(request)
    if not event:
        return HttpResponseForbidden("Invalid signature")

    try:
        if event.type == "checkout.session.completed":
            handle_checkout_completed(event.data.object)
        elif event.type == "customer.subscription.updated":
            handle_subscription_updated(event.data.object)
        elif event.type == "customer.subscription.deleted":
            handle_subscription_deleted(event.data.object)
        elif event.type == "invoice.payment_failed":
            handle_payment_failed(event.data.object)
        elif event.type == "invoice.payment_succeeded":
            handle_payment_succeeded(event.data.object)
        else:
            logger.info(f"Unhandled event type: {event.type}")

        return HttpResponse(status=200)
    except Exception as e:
        logger.exception(f"Error processing webhook: {str(e)}")
        return HttpResponse(status=500)
