"""Utility code used throughout the app"""

import hashlib
import json
import logging
from collections import defaultdict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone

from sbomify.apps.billing.config import get_unlimited_plan_limits, is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_client import StripeClient
from sbomify.apps.core.utils import number_to_random_token

from .models import Invitation, Member, Team, get_team_name_for_user

# Valid tab names for team settings - used for input validation
ALLOWED_TABS = frozenset({"members", "billing", "branding", "general", "domains", "api"})


def redirect_to_team_settings(team_key: str, active_tab: str | None = None):
    """
    Return a redirect response to team settings, optionally with a validated tab anchor.

    Args:
        team_key: The workspace key to redirect
        active_tab: Optional tab name to append as URL fragment (validated against ALLOWED_TABS)

    Returns:
        HttpResponseRedirect to the team settings page
    """
    from urllib.parse import quote

    from django.shortcuts import redirect
    from django.urls import reverse

    # Validate team_key exists to prevent open redirect vulnerabilities
    if not Team.objects.filter(key=team_key).exists():
        return redirect("teams:teams_dashboard")

    base_url = reverse("teams:team_settings", kwargs={"team_key": team_key})
    if active_tab and active_tab in ALLOWED_TABS:
        safe_tab = quote(active_tab)
        return redirect(f"{base_url}#{safe_tab}")
    return redirect(base_url)


def normalize_host(host: str) -> str:
    """
    Normalize a host header value to extract just the hostname.

    Strips port numbers and converts to lowercase for consistent matching.
    Used by DynamicHostValidationMiddleware and domain verification endpoints.

    This function properly handles IPv6 addresses in brackets (e.g., "[::1]:8000").

    Performance: Uses fast path for common case (non-IPv6), falls back to
    urlparse only for IPv6 addresses in brackets.

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
        >>> normalize_host("[::1]:8000")
        '::1'
        >>> normalize_host("[2001:db8::1]:8000")
        '2001:db8::1'
    """
    # Fast path: Handle common case (non-IPv6) without urlparse overhead
    # IPv6 addresses in Host headers are always in brackets: [::1]:8000
    if not host.startswith("["):
        # Simple split for regular domains/IPv4
        return host.split(":")[0].lower()

    # Slow path: IPv6 address with brackets - use urlparse for correctness
    from urllib.parse import urlparse

    # urlparse requires a scheme, so add one temporarily
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    parsed = urlparse(host)
    hostname = parsed.hostname

    # Return lowercase hostname, or fall back to original
    return hostname.lower() if hostname else host.lower()


logger = logging.getLogger(__name__)
User = get_user_model()
stripe_client = StripeClient()


def compute_user_teams_checksum(user_teams: dict | None) -> str:
    """Deterministic checksum for a user's workspace snapshot."""
    serialized = json.dumps(user_teams or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_user_teams(user) -> dict:
    """Get all teams for a user.

    Returns:
        A dictionary mapping team keys to team data
    """
    teams = defaultdict(dict)
    memberships = Member.objects.filter(user=user).select_related("team").order_by("team__created_at", "team__id").all()

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


def update_user_teams_session(request, user, user_teams: dict | None = None) -> dict:
    """Store user teams and a stable checksum on the session, avoiding redundant writes."""
    teams = user_teams if user_teams is not None else get_user_teams(user)
    checksum = compute_user_teams_checksum(teams)
    existing_checksum = request.session.get("user_teams_version")
    existing_teams = request.session.get("user_teams")

    if existing_checksum == checksum and existing_teams:
        request.session["user_teams_checked_at"] = timezone.now().isoformat()
        request.session.modified = True
        return existing_teams

    request.session["user_teams"] = teams
    request.session["user_teams_version"] = checksum
    request.session["user_teams_checked_at"] = timezone.now().isoformat()
    request.session.modified = True
    return teams


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


def switch_active_workspace(request, team: Team, role: str | None = None) -> None:
    """
    Canonical helper to switch the user's active session context.

    Updates the user_teams cache and sets the current_team payload in a single place to avoid drift.
    """
    user = getattr(request, "user", None)
    is_authenticated = user is not None and getattr(user, "is_authenticated", False)

    if is_authenticated:
        membership = Member.objects.filter(user=user, team=team).first()
        effective_role = role or (membership.role if membership else None)
        is_default_team = membership.is_default_team if membership else None

        user_teams = get_user_teams(user)
        existing_entry = user_teams.get(team.key, {})

        team_entry = {
            "id": team.id,
            "name": team.name,
            "role": effective_role or existing_entry.get("role"),
            "is_default_team": is_default_team or existing_entry.get("is_default_team"),
            "has_completed_wizard": team.has_completed_wizard,
            "billing_plan": team.billing_plan,
            "branding_info": team.branding_info,
            "is_public": team.is_public,
        }

        user_teams[team.key] = {**existing_entry, **team_entry}
        request.session["user_teams"] = user_teams
    else:
        team_entry = {
            "id": team.id,
            "name": team.name,
            "role": role,
            "is_default_team": None,
            "has_completed_wizard": team.has_completed_wizard,
            "billing_plan": team.billing_plan,
            "branding_info": team.branding_info,
            "is_public": team.is_public,
        }

    request.session["current_team"] = {"key": team.key, **team_entry}
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
    If the user already has a pending invitation that can be accepted, we
    skip auto-creating a personal workspace so they land directly in the
    invited workspace.

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

    # Skip auto-creation if the user has an active invitation to another workspace
    if user.email:
        pending_invitations = list(
            Invitation.objects.filter(email__iexact=user.email, expires_at__gt=timezone.now()).select_related("team")
        )
        if pending_invitations:
            joinable_invites = []
            for invitation in pending_invitations:
                can_add, _ = can_add_user_to_team(invitation.team)
                if can_add:
                    joinable_invites.append(invitation)

            if joinable_invites:
                logger.info(
                    "User %s has %s joinable pending invitation(s); skipping auto workspace creation",
                    user.username,
                    len(joinable_invites),
                )
                return None

            logger.info(
                "User %s has pending invitations but none can be accepted due to limits; creating personal workspace",
                user.username,
            )

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


def recover_workspace_session(request):
    """
    Handle case where user's session points to a workspace they're no longer a member of.

    This function:
    1. Refreshes user_teams from database
    2. Switches to another available workspace if exists
    3. Creates a personal workspace if needed
    4. Returns a redirect to the appropriate page
    """
    from django.http import HttpResponseForbidden

    from sbomify.apps.core.errors import error_response

    # Get the name of the old workspace before we update the session
    current_team = request.session.get("current_team", {})
    old_team_name = current_team.get("name", "the workspace")

    # Refresh user teams from database
    user_teams = get_user_teams(request.user)
    request.session["user_teams"] = user_teams

    if user_teams:
        # User has other workspaces, switch to the first one
        next_team_key, next_team = next(iter(user_teams.items()))
        request.session["current_team"] = {"key": next_team_key, **next_team}
        request.session.modified = True
        messages.warning(
            request, f"You have been removed from {old_team_name}. You have been switched to your other workspace."
        )
        return redirect("core:dashboard")

    # User has no workspaces at all - create a personal workspace for them
    new_team = create_user_team_and_subscription(request.user)
    if new_team:
        user_teams = get_user_teams(request.user)
        request.session["user_teams"] = user_teams
        request.session["current_team"] = {"key": new_team.key, **user_teams.get(new_team.key, {})}
        request.session.modified = True
        messages.warning(
            request,
            f"You have been removed from {old_team_name}. You have been switched to your new personal workspace.",
        )
        return redirect("core:dashboard")

    # Fallback if workspace creation failed
    request.session.pop("current_team", None)
    request.session.modified = True
    return error_response(request, HttpResponseForbidden("You are not a member of any team"))


def invalidate_custom_domain_cache(domain: str | None) -> None:
    """
    Invalidate the cache for a custom domain.

    This should be called whenever a domain is added, removed, or validated.
    Clears all caches used by DynamicHostValidationMiddleware and
    CustomDomainContextMiddleware.

    Args:
        domain: The domain to invalidate, or None to skip
    """
    if not domain:
        return

    try:
        from django.core.cache import cache

        # Cache keys used by various middleware components
        cache_keys = [
            f"allowed_host:{domain}",  # DynamicHostValidationMiddleware
            f"is_custom_domain:{domain}",  # CustomDomainContextMiddleware
            f"custom_domain_team:{domain}",  # CustomDomainContextMiddleware
        ]

        for cache_key in cache_keys:
            cache.delete(cache_key)

        logger.debug(f"Invalidated all caches for custom domain: {domain}")
    except Exception as e:
        # Cache invalidation failure shouldn't break the flow
        logger.warning(f"Failed to invalidate cache for domain {domain}: {e}")


def remove_member_safely(request, membership: Member, active_tab: str | None = None):
    """
    Safely remove a member from a team, handling last-workspace edge cases.

    This function:
    1. Checks if it's a self-removal vs admin removal.
    2. Checks if this is the user's last workspace.
    3. Handles creation of a fallback personal workspace if needed.
    4. Updates session data accordingly.
    5. Returns a redirect to the appropriate next page.
    """
    removed_user = membership.user
    removed_team_name = membership.team.display_name
    removed_team_key = membership.team.key
    is_self_removal = membership.user_id == request.user.id

    # Check if this is the user's last workspace BEFORE deleting
    is_last_workspace = not Member.objects.filter(user=removed_user).exclude(pk=membership.pk).exists()

    membership.delete()

    # If this was the user's last workspace, try to create a personal workspace
    if is_last_workspace:
        new_team = create_user_team_and_subscription(removed_user)

        # If new team creation succeeded
        if new_team:
            if is_self_removal:
                messages.warning(
                    request,
                    f"You have been removed from {removed_team_name}.",
                )
                # Update session with the new workspace
                user_teams = get_user_teams(request.user)
                request.session["user_teams"] = user_teams
                request.session["current_team"] = {"key": new_team.key, **user_teams.get(new_team.key, {})}
                request.session.modified = True

                return redirect("core:dashboard")
            else:
                # Owner/admin removed someone else
                messages.info(
                    request,
                    (
                        f"Member {removed_user.username} removed from workspace. "
                        "A new personal workspace has been created for them."
                    ),
                )
                return redirect_to_team_settings(removed_team_key, active_tab)

        # If new team creation FAILED (e.g. pending invites exist), handle gracefully
        else:
            if is_self_removal:
                messages.warning(
                    request,
                    (
                        f"You have been removed from {removed_team_name}. "
                        "Please accept a pending invitation or contact support."
                    ),
                )
                # Clear current team as they have none
                request.session.pop("current_team", None)
                request.session["user_teams"] = {}
                request.session.modified = True
                # Consider redirecting to a dedicated "my invitations" page if/when implemented.
                return redirect("core:dashboard")
            else:
                messages.info(
                    request,
                    f"Member {removed_user.username} removed from workspace.",
                )
                return redirect_to_team_settings(removed_team_key, active_tab)

    # Normal removal (user has other workspaces)
    if is_self_removal:
        messages.info(request, f"You have left {removed_team_name}.")
        user_teams = get_user_teams(request.user)
        request.session["user_teams"] = user_teams

        # Reset current team to another workspace if available, otherwise clear it
        if user_teams:
            next_team_key, next_team = next(iter(user_teams.items()))
            request.session["current_team"] = {"key": next_team_key, **next_team}
        else:
            request.session.pop("current_team", None)

        request.session.modified = True
        return redirect("teams:teams_dashboard")
    else:
        messages.info(request, f"Member {removed_user.username} removed from workspace.")
        return redirect_to_team_settings(removed_team_key, active_tab)
