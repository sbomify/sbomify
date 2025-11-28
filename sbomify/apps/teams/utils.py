"""Utility code used throughout the app"""

import logging
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from sbomify.apps.billing.config import get_unlimited_plan_limits, is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_client import StripeClient
from sbomify.apps.core.utils import number_to_random_token

from .models import Member, Team, get_team_name_for_user


def normalize_host(host: str) -> str:
    """
    Normalize a host header value to extract just the hostname.

    Strips port numbers and converts to lowercase for consistent matching.
    Used by both DynamicAllowedHosts and domain verification endpoints.

    Args:
        host: Host header value (may include port, e.g., "example.com:8000")

    Returns:
        Normalized hostname in lowercase without port

    Examples:
        >>> normalize_host("example.com")
        'example.com'
        >>> normalize_host("Example.Com:8000")
        'example.com'
        >>> normalize_host("APP.EXAMPLE.COM:443")
        'app.example.com'
    """
    return host.split(":")[0].lower()


logger = logging.getLogger(__name__)
User = get_user_model()
stripe_client = StripeClient()


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
            "billing_plan": membership.team.billing_plan,
            "branding_info": membership.team.branding_info,
            "is_public": membership.team.is_public,
        }

    return dict(teams)


def refresh_current_team_session(request, team: Team) -> None:
    """
    Update the current_team session entry to reflect the latest team state.

    Centralizes session mutation so callers don't manually patch keys.
    """
    current_team = request.session.get("current_team") or {}
    if current_team.get("key") != team.key:
        return

    request.session["current_team"] = {
        **current_team,
        "id": team.id,
        "key": team.key,
        "name": team.name,
        "role": current_team.get("role"),
        "is_default_team": current_team.get("is_default_team"),
        "has_completed_wizard": team.has_completed_wizard,
        "billing_plan": team.billing_plan,
        "branding_info": team.branding_info,
        "is_public": team.is_public,
    }
    request.session.modified = True


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


def create_user_team_and_subscription(user) -> Team | None:
    """
    Create a team and set up billing subscription for a new user.

    This is the canonical function for setting up a new user's workspace.
    Used by both SSO and username/password signup flows to ensure consistency.

    Args:
        user: The newly created user instance (must have email set)

    Returns:
        The created Team instance, or None if creation failed

    Raises:
        Does not raise exceptions - logs errors and falls back to community plan
    """
    # Check if user already has a team (idempotency check)
    # Only do this if user has been saved to DB (has a PK)
    if user.pk and Team.objects.filter(members=user).exists():
        logger.debug(f"User {user.username} already has a team, skipping creation")
        return Team.objects.filter(members=user).first()

    # Validate user has email
    if not user.email:
        logger.error(f"User {user.username} has no email address, cannot create team with subscription")
        # Still create team, but without billing
        team_name = get_team_name_for_user(user)
        with transaction.atomic():
            team = Team.objects.create(name=team_name)
            team.key = number_to_random_token(team.pk)
            team.save()
            Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        logger.warning(f"Created team {team.key} for user {user.username} without billing setup (no email)")
        return team

    # Create team
    team_name = get_team_name_for_user(user)
    with transaction.atomic():
        team = Team.objects.create(name=team_name)
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

    logger.info(f"Created team {team.key} ({team.name}) for user {user.username}")

    # Set up billing plan
    if is_billing_enabled():
        _setup_trial_subscription(user, team)
    else:
        _setup_community_plan(team)

    return team


def _setup_trial_subscription(user, team: Team) -> bool:
    """
    Set up a trial subscription for a team.

    Args:
        user: The team owner
        team: The team to set up subscription for

    Returns:
        True if successful, False otherwise
    """
    try:
        business_plan = BillingPlan.objects.get(key="business")
        customer = stripe_client.create_customer(email=user.email, name=team.name, metadata={"team_key": team.key})
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
        logger.info(f"Created trial subscription for team {team.key} ({team.name})")

        # Send welcome email
        _send_welcome_email(user, team, business_plan)
        return True

    except Exception as e:
        logger.error(f"Failed to create trial subscription for team {team.key}: {str(e)}")
        # Fallback to community plan
        _setup_community_plan(team)
        return False


def _setup_community_plan(team: Team) -> None:
    """
    Set up community plan for a team (fallback when billing is disabled or trial fails).

    Args:
        team: The team to set up community plan for
    """
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
        logger.info(f"Set up community plan for team {team.key} ({team.name})")
    except BillingPlan.DoesNotExist:
        # Fallback to unlimited limits if community plan doesn't exist
        team.billing_plan = "community"
        team.billing_plan_limits = get_unlimited_plan_limits()
        team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
        team.save()
        logger.info(
            f"Set up unlimited community plan for team {team.key} ({team.name}) - no community plan found in DB"
        )


def _send_welcome_email(user, team: Team, business_plan: BillingPlan) -> None:
    """
    Send welcome email to new user with trial information.

    Args:
        user: The user to send email to
        team: The user's team
        business_plan: The business plan they're trialing
    """
    try:
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
            message=render_to_string("teams/emails/new_user_email.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=render_to_string("teams/emails/new_user_email.html.j2", context),
        )
        logger.info(f"Sent welcome email to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")


def invalidate_custom_domain_cache(domain: str | None) -> None:
    """
    Invalidate the cache for a custom domain.

    This should be called whenever a domain is added, removed, or validated.

    Args:
        domain: The domain to invalidate, or None to skip
    """
    if not domain:
        return

    try:
        from django.core.cache import cache

        cache_key = f"custom_domain:{domain}"
        cache.delete(cache_key)
        logger.debug(f"Invalidated cache for custom domain: {domain}")
    except Exception as e:
        # Cache invalidation failure shouldn't break the flow
        logger.warning(f"Failed to invalidate cache for domain {domain}: {e}")
