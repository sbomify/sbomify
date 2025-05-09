"""
Module for handling Stripe billing webhook events and related processing
"""

import datetime
from functools import wraps

import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone

from core.errors import error_response
from sbomify.logging import getLogger
from sboms.models import Component, Product, Project
from teams.models import Member, Team

from . import email_notifications
from .models import BillingPlan

logger = getLogger(__name__)

# Stripe webhook signature verification
def verify_stripe_webhook(request):
    """Verify that the webhook request is from Stripe."""
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        logger.error("No Stripe signature found in request headers")
        return False

    try:
        event = stripe.Webhook.construct_event(
            request.body,
            signature,
            settings.STRIPE_WEBHOOK_SECRET
        )
        return event
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid Stripe signature")
        return False
    except Exception as e:
        logger.error(f"Error verifying Stripe webhook: {str(e)}")
        return False

# Stripe error handling
class StripeError(Exception):
    """Base class for Stripe-related errors."""
    pass

class StripeWebhookError(StripeError):
    """Error processing Stripe webhook."""
    pass

class StripeSubscriptionError(StripeError):
    """Error processing Stripe subscription."""
    pass

def handle_stripe_error(func):
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


def check_billing_limits(model_type: str):
    """Decorator to check billing plan limits before creating new items."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Only check limits for POST requests
            if request.method != "POST":
                return view_func(request, *args, **kwargs)

            # Get current team
            team_key = request.session.get("current_team", {}).get("key")
            if not team_key:
                return error_response(request, HttpResponseForbidden("No team selected"))

            try:
                team = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                return error_response(request, HttpResponseForbidden("Invalid team"))

            # Get billing plan
            if not team.billing_plan:
                return error_response(request, HttpResponseForbidden("No active billing plan"))

            try:
                plan = BillingPlan.objects.get(key=team.billing_plan)
            except BillingPlan.DoesNotExist:
                return error_response(request, HttpResponseForbidden("Invalid billing plan configuration"))

            # Get current counts
            model_map = {
                "product": (Product, plan.max_products),
                "project": (Project, plan.max_projects),
                "component": (Component, plan.max_components),
            }

            if model_type not in model_map:
                return error_response(request, HttpResponseForbidden("Invalid resource type"))

            model_class, max_allowed = model_map[model_type]
            current_count = model_class.objects.filter(team=team).count()

            if max_allowed is not None and current_count >= max_allowed:
                error_message = (
                    f"Your {plan.name} plan allows maximum {max_allowed} {model_type}s. "
                    f"Current usage: {current_count}/{max_allowed}."
                )
                return error_response(request, HttpResponseForbidden(error_message))

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


@handle_stripe_error
def handle_subscription_updated(subscription):
    """Handle subscription updated events."""
    try:
        # First try to find by subscription ID
        team = Team.objects.filter(billing_plan_limits__stripe_subscription_id=subscription.id).first()

        # If not found, try to find by customer ID
        if not team and hasattr(subscription, "customer"):
            team = Team.objects.filter(billing_plan_limits__stripe_customer_id=subscription.customer).first()

        if not team:
            logger.error(f"No team found for subscription {subscription.id}")
            return

        old_status = team.billing_plan_limits.get("subscription_status")
        new_status = subscription.status

        # Validate subscription status
        valid_statuses = ["trialing", "active", "past_due", "canceled", "incomplete", "incomplete_expired"]
        if new_status not in valid_statuses:
            raise StripeSubscriptionError(f"Invalid subscription status: {new_status}")

        # Update subscription status and trial information
        team.billing_plan_limits["subscription_status"] = new_status
        team.billing_plan_limits["trial_end"] = subscription.trial_end
        team.billing_plan_limits["is_trial"] = subscription.status == "trialing"

        # Add/update the last_updated timestamp
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()

        # Update billing plan based on subscription's product
        if subscription.items.data:
            try:
                # Use business plan for now, as specified
                plan = BillingPlan.objects.get(key="business")
                team.billing_plan = plan.key
                team.billing_plan_limits.update(
                    {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                    }
                )
            except BillingPlan.DoesNotExist:
                logger.error("Business billing plan not found")
                raise StripeSubscriptionError("Business billing plan not found")

        # Handle specific status transitions
        if new_status == "past_due" and old_status == "active":
            # Send notification to team owners about payment being past due
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_payment_past_due(team, member)
                logger.warning(f"Payment past due notification sent for team {team.key} to {member.user.email}")

        elif new_status == "active" and old_status == "past_due":
            # Payment has been resolved
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_payment_succeeded(team, member)
                logger.info(f"Payment restored notification sent for team {team.key} to {member.user.email}")

        elif new_status == "canceled":
            # Subscription has been canceled but not yet ended
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_subscription_cancelled(team, member)
                logger.info(
                    f"Subscription cancelled notification sent for team {team.key} "
                    f"to {member.user.email}"
                )
        elif new_status in ["incomplete", "incomplete_expired"]:
            # Handle failed initial payment
            team_owners = Member.objects.filter(team=team, role="owner")
            for member in team_owners:
                email_notifications.notify_payment_failed(team, member, None)
                logger.warning(
                    f"Initial payment failed notification sent for team {team.key} "
                    f"to {member.user.email}"
                )

        team.save()

        # If trial is ending soon, notify team owners
        if subscription.status == "trialing" and subscription.trial_end:
            trial_end = datetime.datetime.fromtimestamp(subscription.trial_end, tz=datetime.timezone.utc)
            days_remaining = (trial_end - timezone.now()).days
            if days_remaining <= settings.TRIAL_ENDING_NOTIFICATION_DAYS:
                team_owners = Member.objects.filter(team=team, role="owner")
                for member in team_owners:
                    email_notifications.notify_trial_ending(team, member, days_remaining)
                    logger.info(f"Trial ending notification sent for team {team.key} to {member.user.email}")

        logger.info(f"Updated subscription status for team {team.key} to {new_status}")

    except Exception as e:
        logger.exception(f"Error processing subscription update: {str(e)}")
        raise StripeSubscriptionError(f"Error processing subscription update: {str(e)}")


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


def handle_payment_failed(invoice):
    """Handle payment failure events"""
    if not hasattr(invoice, "subscription") or not invoice.subscription:
        logger.error("No subscription found in invoice")
        return

    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=invoice.subscription)

        # No need to change subscription status as Stripe will do that
        # But still record the timestamp of this event
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
        team.save()

        # Notify team owners
        for member in team.members.all():
            if member.role == "owner":
                email_notifications.notify_payment_failed(team, member, invoice.hosted_invoice_url)
                logger.warning(f"Payment failed notification sent for team {team.key} to {member.user.email}")

        logger.warning(f"Payment failed for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {invoice.subscription}")


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

        logger.info(f"Payment successful for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {invoice.subscription}")


def can_downgrade_to_plan(team: Team, plan: BillingPlan) -> tuple[bool, str]:
    """Check if a team can downgrade to a specific plan based on usage limits"""
    if not plan.max_products and not plan.max_projects and not plan.max_components:
        # Enterprise plan has no limits
        return True, ""

    error_messages = []

    product_count = Product.objects.filter(team=team).count()
    if plan.max_products and product_count > plan.max_products:
        error_messages.append(
            f"You have {product_count} products, but the {plan.name} plan only allows {plan.max_products}"
        )

    project_count = Project.objects.filter(team=team).count()
    if plan.max_projects and project_count > plan.max_projects:
        error_messages.append(
            f"You have {project_count} projects, but the {plan.name} plan only allows {plan.max_projects}"
        )

    component_count = Component.objects.filter(team=team).count()
    if plan.max_components and component_count > plan.max_components:
        error_messages.append(
            f"You have {component_count} components, but the {plan.name} plan only allows {plan.max_components}"
        )

    if error_messages:
        return False, "Cannot downgrade: " + "; ".join(error_messages)

    return True, ""


@handle_stripe_error
def handle_checkout_completed(session):
    """Handle checkout session completed events"""
    # Only proceed if payment was successful
    if session.payment_status != "paid":
        logger.error("Payment status was not 'paid': %s", session.payment_status)
        return

    # Get the team from metadata
    team_key = session.metadata.get("team_key")
    if not team_key:
        logger.error("No team key found in session metadata")
        return

    try:
        team = Team.objects.get(key=team_key)
        plan = BillingPlan.objects.get(key="business")  # Hardcoded to business plan

        # Get the subscription to check trial status
        subscription = stripe.Subscription.retrieve(
            session.subscription,
            expand=["latest_invoice.payment_intent"]  # Expand payment intent for better error handling
        )

        # Update team billing information
        team.billing_plan = plan.key

        # Add last updated timestamp to track when billing was processed
        billing_limits = {
            "max_products": plan.max_products,
            "max_projects": plan.max_projects,
            "max_components": plan.max_components,
            "stripe_customer_id": session.customer,
            "stripe_subscription_id": session.subscription,
            "subscription_status": subscription.status,
            "trial_end": subscription.trial_end,
            "is_trial": subscription.status == "trialing",
            "last_updated": timezone.now().isoformat(),
        }

        team.billing_plan_limits = billing_limits
        team.save()
        logger.info("Successfully processed checkout session for team %s", team_key)
    except Team.DoesNotExist:
        logger.error(f"Team with key {team_key} not found")
        raise StripeError(f"Team with key {team_key} not found")
    except BillingPlan.DoesNotExist:
        logger.error("Business billing plan not found")
        raise StripeError("Business billing plan not found")
    except stripe.error.StripeError as e:
        logger.error(f"Error retrieving subscription: {str(e)}")
        raise StripeError(f"Error retrieving subscription: {str(e)}")


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
