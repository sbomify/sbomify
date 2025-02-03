"""
Module for handling Stripe billing webhook events and related processing
"""

from sbomify.logging import getLogger
from sboms.models import Component, Product, Project
from teams.models import Team

from . import email_notifications
from .models import BillingPlan

logger = getLogger(__name__)


def handle_subscription_updated(subscription):
    """Handle subscription update events"""
    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=subscription.id)

        old_status = team.billing_plan_limits.get("subscription_status")
        new_status = subscription.status

        # Update subscription status
        team.billing_plan_limits["subscription_status"] = new_status

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

        # Revert to community plan
        community_plan = BillingPlan.objects.get(key="community")
        team.billing_plan = "community"
        team.billing_plan_limits = {
            "max_products": community_plan.max_products,
            "max_projects": community_plan.max_projects,
            "max_components": community_plan.max_components,
        }
        team.save()

        # Notify team owners
        team_owners = team.members.filter(member__role="owner")
        for owner in team_owners:
            email_notifications.notify_subscription_cancelled(team, owner)
            logger.info(f"Subscription ended notification sent for team {team.key} to {owner.member.user.email}")

        logger.info(f"Subscription ended for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for subscription {subscription.id}")


def handle_payment_failed(invoice):
    """Handle payment failure events"""
    try:
        team = Team.objects.get(billing_plan_limits__stripe_customer_id=invoice.customer)

        # Get payment failure details
        attempt_count = invoice.attempt_count
        next_payment_attempt = invoice.next_payment_attempt

        # Notify team owners with specific details
        team_owners = team.members.filter(member__role="owner")
        for owner in team_owners:
            email_notifications.notify_payment_failed(team, owner, attempt_count, next_payment_attempt)
            logger.error(
                f"Payment failed notification sent for team {team.key} to {owner.member.user.email}. "
                f"Attempt {attempt_count}, Next attempt: {next_payment_attempt}"
            )

    except Team.DoesNotExist:
        logger.error(f"No team found for customer {invoice.customer}")


def handle_payment_succeeded(invoice):
    """Handle successful payment events"""
    try:
        team = Team.objects.get(billing_plan_limits__stripe_customer_id=invoice.customer)

        # Update any relevant payment status
        if team.billing_plan_limits.get("subscription_status") == "past_due":
            team.billing_plan_limits["subscription_status"] = "active"
            team.save()

            # Notify team owners of restored service
            team_owners = team.members.filter(member__role="owner")
            for owner in team_owners:
                email_notifications.notify_payment_succeeded(team, owner)
                logger.info(f"Payment succeeded notification sent for team {team.key} to {owner.member.user.email}")

        logger.info(f"Payment succeeded for team {team.key}")

    except Team.DoesNotExist:
        logger.error(f"No team found for customer {invoice.customer}")


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
