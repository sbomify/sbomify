"""Utility code used throughout the app"""

import logging
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from billing.config import get_unlimited_plan_limits, is_billing_enabled
from billing.models import BillingPlan
from billing.stripe_client import StripeClient

from .models import Member, Team

User = get_user_model()


def get_user_teams(user) -> dict:
    """Get all teams for a user.

    Returns:
        A dictionary mapping team keys to team data
    """
    teams = defaultdict(dict)
    memberships = Member.objects.filter(user=user).select_related("team").all()

    for membership in memberships:
        teams[membership.team.key] = {
            "id": membership.team.id,
            "name": membership.team.name,
            "role": membership.role,
            "is_default_team": membership.is_default_team,
            "has_completed_wizard": membership.team.has_completed_wizard,
        }

    return dict(teams)


def get_user_default_team(user) -> int:
    """Get the user's default team ID. Returns the first team they're a member of."""
    try:
        default_team = Member.objects.get(user=user, is_default_team=True)
        return default_team.team_id
    except Member.DoesNotExist:
        return None


def can_add_user_to_team(team: Team) -> tuple[bool, str]:
    """
    Check if a team can add more users based on their billing plan limits.

    Args:
        team: The team to check

    Returns:
        Tuple of (can_add, error_message). If can_add is False, error_message contains the reason.
    """
    # If no billing plan, default to community limits (1 user = owner only)
    if not team.billing_plan:
        current_members = Member.objects.filter(team=team).count()
        if current_members >= 1:
            return (False, "Community plan allows only 1 user (owner). Please upgrade your plan to add more members.")
        return True, ""

    try:
        plan = BillingPlan.objects.get(key=team.billing_plan)

        # Enterprise plans have unlimited users
        if plan.allows_unlimited_users:
            return True, ""

        current_members = Member.objects.filter(team=team).count()

        if current_members >= plan.max_users:
            return (
                False,
                f"Your {plan.name} plan allows only {plan.max_users} users. "
                f"Please upgrade your plan to add more members.",
            )

        return True, ""

    except BillingPlan.DoesNotExist:
        # If plan doesn't exist, treat as community
        current_members = Member.objects.filter(team=team).count()
        if current_members >= 1:
            return (False, "Community plan allows only 1 user (owner). Please upgrade your plan to add more members.")
        return True, ""


def setup_team_billing_plan(team: Team, user=None, send_welcome_email: bool = False) -> None:
    """Set up billing plan for a team based on current billing configuration.

    Args:
        team: The team to set up billing for
        user: Optional user for trial subscription setup and welcome email
        send_welcome_email: Whether to send welcome email for trial subscriptions
    """
    log = logging.getLogger(__name__)
    stripe_client = StripeClient()

    if is_billing_enabled():
        # Billing is enabled - set up appropriate plan based on user context
        if user:
            # Create trial subscription for new users (signup flow)
            try:
                business_plan = BillingPlan.objects.get(key="business")
                customer = stripe_client.create_customer(
                    email=user.email, name=team.name, metadata={"team_key": team.key}
                )
                subscription = stripe_client.create_subscription(
                    customer_id=customer.id,
                    price_id=business_plan.stripe_price_monthly_id,
                    trial_days=settings.TRIAL_PERIOD_DAYS,
                    metadata={"team_key": team.key, "plan_key": "business"},
                )
                team.billing_plan = "business"
                team.billing_plan_limits = {
                    "max_products": business_plan.max_products,
                    "max_projects": business_plan.max_projects,
                    "max_components": business_plan.max_components,
                    "stripe_customer_id": customer.id,
                    "stripe_subscription_id": subscription.id,
                    "subscription_status": "trialing",
                    "is_trial": True,
                    "trial_end": subscription.trial_end,
                    "last_updated": timezone.now().isoformat(),
                }
                team.save()
                log.info(f"Created trial subscription for team {team.key} ({team.name})")

                # Send welcome email if requested
                if send_welcome_email:
                    context = {
                        "user": user,
                        "team": team,
                        "base_url": settings.APP_BASE_URL,
                        "TRIAL_PERIOD_DAYS": settings.TRIAL_PERIOD_DAYS,
                        "trial_end_date": timezone.now() + timezone.timedelta(days=settings.TRIAL_PERIOD_DAYS),
                        "plan_limits": {
                            "max_products": business_plan.max_products,
                            "max_projects": business_plan.max_projects,
                            "max_components": business_plan.max_components,
                        },
                    }
                    send_mail(
                        subject="Welcome to sbomify - Your Business Plan Trial",
                        message=render_to_string("teams/new_user_email.txt", context),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        html_message=render_to_string("teams/new_user_email.html.j2", context),
                    )
            except Exception as e:
                log.error(f"Failed to create trial subscription for team {team.key}: {str(e)}")
        else:
            # Set up community plan for manually created teams (no trial)
            try:
                community_plan = BillingPlan.objects.get(key="community")
                team.billing_plan = "community"
                team.billing_plan_limits = {
                    "max_products": community_plan.max_products,
                    "max_projects": community_plan.max_projects,
                    "max_components": community_plan.max_components,
                    "subscription_status": "active",
                    "last_updated": timezone.now().isoformat(),
                }
                team.save()
                log.info(f"Set up community plan for team {team.key} ({team.name})")
            except BillingPlan.DoesNotExist:
                # Fallback to unlimited limits if community plan doesn't exist
                team.billing_plan = "community"
                team.billing_plan_limits = get_unlimited_plan_limits()
                team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
                team.save()
                log.info(f"Set up unlimited community plan for team {team.key} ({team.name}) - no community plan found")
    else:
        # Billing is disabled - always set up enterprise plan with unlimited limits
        try:
            enterprise_plan = BillingPlan.objects.get(key="enterprise")
            team.billing_plan = "enterprise"
            team.billing_plan_limits = {
                "max_products": enterprise_plan.max_products,
                "max_projects": enterprise_plan.max_projects,
                "max_components": enterprise_plan.max_components,
                "subscription_status": "active",
                "last_updated": timezone.now().isoformat(),
            }
            team.save()
            log.info(f"Set up enterprise plan for team {team.key} ({team.name}) - billing disabled")
        except BillingPlan.DoesNotExist:
            # Fallback to unlimited limits if enterprise plan doesn't exist
            team.billing_plan = "enterprise"
            team.billing_plan_limits = get_unlimited_plan_limits()
            team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
            team.save()
            log.info(
                f"Set up unlimited enterprise plan for team {team.key} ({team.name}) - "
                f"billing disabled, no enterprise plan found"
            )
