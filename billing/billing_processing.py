"""
Module for handling Stripe billing webhook events and related processing
"""

import datetime
from functools import wraps

from django.http import HttpResponseForbidden
from django.utils import timezone

from core.errors import error_response
from sbomify.logging import getLogger
from sboms.models import Component, Product, Project
from teams.models import Team

from . import email_notifications
from .models import BillingPlan

logger = getLogger(__name__)


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


def handle_subscription_updated(subscription):
    """Handle subscription update events"""
    try:
        # First try to find by subscription ID
        team = Team.objects.filter(billing_plan_limits__stripe_subscription_id=subscription.id).first()

        # If not found, try to find by customer ID
        if not team and hasattr(subscription, "customer"):
            team = Team.objects.filter(billing_plan_limits__stripe_customer_id=subscription.customer).first()

        if not team:
            logger.error(f"No team found for subscription {subscription.id}")
            return

        # Check if billing was recently updated (within the last minute)
        # This helps prevent duplicate processing between webhook and billing_return
        last_updated_str = team.billing_plan_limits.get("last_updated")
        if last_updated_str:
            try:
                last_updated = datetime.datetime.fromisoformat(last_updated_str)
                # Add timezone information if it's naive
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=timezone.utc)

                # If the billing was updated less than 60 seconds ago, skip this update
                time_diff = timezone.now() - last_updated
                if time_diff.total_seconds() < 60:
                    logger.info(
                        f"Skipping subscription update for team {team.key} - "
                        f"recently updated ({time_diff.total_seconds()} seconds ago)"
                    )
                    return
            except (ValueError, TypeError):
                logger.warning(f"Invalid last_updated format in team {team.key} billing_plan_limits")
                # Continue processing if date parsing fails

        old_status = team.billing_plan_limits.get("subscription_status")
        new_status = subscription.status

        # Update subscription status
        team.billing_plan_limits["subscription_status"] = new_status
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

        # Handle specific status transitions
        if new_status == "past_due" and old_status == "active":
            # Send notification to team owners about payment being past due
            team_owners = team.members.filter(member__role="owner")
            for owner in team_owners:
                email_notifications.notify_payment_past_due(team, owner)
                logger.warning(f"Payment past due notification sent for team {team.key} to {owner.member.user.email}")

        elif new_status == "active" and old_status == "past_due":
            # Payment has been resolved
            team_owners = team.members.filter(member__role="owner")
            for owner in team_owners:
                email_notifications.notify_payment_succeeded(team, owner)
                logger.info(f"Payment restored notification sent for team {team.key} to {owner.member.user.email}")

        elif new_status == "canceled":
            # Subscription has been canceled but not yet ended
            team_owners = team.members.filter(member__role="owner")
            for owner in team_owners:
                email_notifications.notify_subscription_cancelled(team, owner)
                logger.info(
                    f"Subscription cancelled notification sent for team {team.key} to {owner.member.user.email}"
                )

        team.save()
        logger.info(f"Updated subscription status to {new_status} for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {subscription.id}")


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
        team_owners = team.members.filter(member__role="owner")
        for owner in team_owners:
            email_notifications.notify_subscription_ended(team, owner)
            logger.info(f"Subscription ended notification sent for team {team.key} to {owner.member.user.email}")

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
        team_owners = team.members.filter(member__role="owner")
        for owner in team_owners:
            email_notifications.notify_payment_failed(team, owner, invoice.hosted_invoice_url)
            logger.warning(f"Payment failed notification sent for team {team.key} to {owner.member.user.email}")

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

    product_count = Product.objects.filter(team=team).count()
    if plan.max_products and product_count > plan.max_products:
        return (
            False,
            f"Cannot downgrade: You have {product_count} products, "
            f"but the {plan.name} plan only allows {plan.max_products}",
        )

    project_count = Project.objects.filter(team=team).count()
    if plan.max_projects and project_count > plan.max_projects:
        return (
            False,
            f"Cannot downgrade: You have {project_count} projects, "
            f"but the {plan.name} plan only allows {plan.max_projects}",
        )

    component_count = Component.objects.filter(team=team).count()
    if plan.max_components and component_count > plan.max_components:
        return (
            False,
            f"Cannot downgrade: You have {component_count} components, "
            f"but the {plan.name} plan only allows {plan.max_components}",
        )

    return True, ""


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

        # Update team billing information
        team.billing_plan = plan.key

        # Add last updated timestamp to track when billing was processed
        billing_limits = {
            "max_products": plan.max_products,
            "max_projects": plan.max_projects,
            "max_components": plan.max_components,
            "stripe_customer_id": session.customer,
            "stripe_subscription_id": session.subscription,
            "subscription_status": "active",
            "last_updated": timezone.now().isoformat(),
        }

        team.billing_plan_limits = billing_limits
        team.save()
        logger.info("Successfully processed checkout session for team %s", team_key)
    except Team.DoesNotExist:
        logger.error(f"Team with key {team_key} not found")
    except BillingPlan.DoesNotExist:
        logger.error("Business billing plan not found")
