"""Service for user account deletion."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from sbomify.apps.core.models import User

logger = logging.getLogger(__name__)

SOFT_DELETE_GRACE_DAYS = 14


def validate_account_deletion(user: User) -> tuple[bool, str | None]:
    """
    Validate if user can delete their account.

    Blocks deletion if user is the sole owner of a workspace that has other members.
    Users must transfer ownership or remove members before deleting their account.
    """
    from sbomify.apps.teams.models import Member

    owner_memberships = Member.objects.filter(user=user, role="owner").select_related("team")

    for membership in owner_memberships:
        team = membership.team
        other_owners = Member.objects.filter(team=team, role="owner").exclude(user=user).count()
        other_members = Member.objects.filter(team=team).exclude(user=user).count()

        if other_owners == 0 and other_members > 0:
            return (
                False,
                f"You are the sole owner of workspace '{team.display_name}' which has other members. "
                "Please transfer ownership or remove all members before deleting your account.",
            )

    return True, None


def invalidate_user_sessions(user: User) -> int:
    """Invalidate all active sessions for a user."""
    deleted_count = 0
    active_sessions = Session.objects.filter(expire_date__gte=timezone.now())

    for session in active_sessions:
        try:
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == str(user.id):
                session.delete()
                deleted_count += 1
        except Exception as e:
            logger.debug("Could not process session %s: %s", session.session_key, type(e).__name__)
            continue

    return deleted_count


def _get_orphaned_workspaces(user: User):
    """Find workspaces where user is sole owner AND sole member."""
    from sbomify.apps.teams.models import Member

    orphaned = []
    owner_memberships = Member.objects.filter(user=user, role="owner").select_related("team")

    for membership in owner_memberships:
        team = membership.team
        total_members = Member.objects.filter(team=team).count()
        if total_members == 1:
            orphaned.append(team)

    return orphaned


def _cleanup_stripe_for_workspace(team) -> None:
    """Cancel Stripe subscription and delete customer for a workspace."""
    from sbomify.apps.billing.config import is_billing_enabled
    from sbomify.apps.billing.stripe_client import StripeError, get_stripe_client

    if not is_billing_enabled():
        return

    limits = team.billing_plan_limits or {}
    subscription_id = limits.get("stripe_subscription_id")
    customer_id = limits.get("stripe_customer_id")

    if not subscription_id and not customer_id:
        return

    try:
        client = get_stripe_client()
        if subscription_id:
            client.cancel_subscription(subscription_id, prorate=True)
            logger.info("Cancelled Stripe subscription %s for team %s", subscription_id, team.key)
        if customer_id:
            client.delete_customer(customer_id)
            logger.info("Deleted Stripe customer %s for team %s", customer_id, team.key)
    except StripeError as e:
        logger.error("Stripe cleanup failed for team %s: %s", team.key, e)


def _disable_keycloak_user(user: User) -> bool:
    """Disable (not delete) user in Keycloak. Returns True if successful or not needed."""
    keycloak_user_id = None
    try:
        social_account = SocialAccount.objects.get(user=user, provider="keycloak")
        keycloak_user_id = social_account.uid
    except SocialAccount.DoesNotExist:
        return True

    if not getattr(settings, "USE_KEYCLOAK", True):
        return True

    from sbomify.apps.core.keycloak_utils import KeycloakManager

    try:
        manager = KeycloakManager()
        return manager.disable_user(keycloak_user_id)
    except Exception as e:
        logger.error("Failed to disable Keycloak user %s: %s", user.id, e)
        return False


def _delete_keycloak_user(user: User) -> bool:
    """Delete user from Keycloak. Returns True if successful or not needed."""
    keycloak_user_id = None
    try:
        social_account = SocialAccount.objects.get(user=user, provider="keycloak")
        keycloak_user_id = social_account.uid
    except SocialAccount.DoesNotExist:
        return True

    if not getattr(settings, "USE_KEYCLOAK", True):
        return True

    from sbomify.apps.core.keycloak_utils import KeycloakManager

    try:
        manager = KeycloakManager()
        return manager.delete_user(keycloak_user_id)
    except Exception as e:
        logger.error("Failed to delete Keycloak user %s: %s", user.id, e)
        return False


def soft_delete_user_account(user: User) -> tuple[bool, str]:
    """
    Soft-delete a user account.

    Steps:
    1. Validate deletion is allowed
    2. Disable in Keycloak (if linked)
    3. Cancel Stripe subscriptions for orphaned workspaces
    4. Delete orphaned workspaces
    5. Clean up invitations
    6. Revoke API tokens
    7. Invalidate sessions
    8. Set is_active=False and deleted_at=now
    """
    can_delete, error = validate_account_deletion(user)
    if not can_delete:
        return False, error

    if not _disable_keycloak_user(user):
        return (
            False,
            "Failed to disable account in authentication provider. Please try again later or contact support.",
        )

    orphaned_workspaces = _get_orphaned_workspaces(user)
    for team in orphaned_workspaces:
        _cleanup_stripe_for_workspace(team)

    with transaction.atomic():
        for team in orphaned_workspaces:
            logger.info("Deleting orphaned workspace %s (team_key=%s)", team.name, team.key)
            team.delete()

        from sbomify.apps.teams.models import Invitation

        deleted_invites = Invitation.objects.filter(email=user.email).delete()[0]
        if deleted_invites:
            logger.info("Deleted %d incoming invitations for %s", deleted_invites, user.email)

        from sbomify.apps.access_tokens.models import AccessToken

        deleted_tokens = AccessToken.objects.filter(user=user).delete()[0]
        if deleted_tokens:
            logger.info("Deleted %d access tokens for user %s", deleted_tokens, user.id)

        user.is_active = False
        user.deleted_at = timezone.now()
        user.save(update_fields=["is_active", "deleted_at"])

    sessions_invalidated = invalidate_user_sessions(user)
    logger.info("Invalidated %d sessions for user %s", sessions_invalidated, user.id)

    logger.info(
        "Soft-deleted user account: %s (ID: %s). Hard delete scheduled after %d days.",
        user.username,
        user.id,
        SOFT_DELETE_GRACE_DAYS,
    )

    return True, (
        "Your account has been scheduled for deletion. "
        f"It will be permanently removed after {SOFT_DELETE_GRACE_DAYS} days. "
        "Contact support if you change your mind."
    )


def hard_delete_user(user: User) -> bool:
    """Permanently delete a soft-deleted user. Called by periodic purge task."""
    if user.is_active or user.deleted_at is None:
        logger.warning("Attempted hard delete on active user %s — skipping", user.id)
        return False

    _delete_keycloak_user(user)

    logger.info("Hard-deleting user: %s (ID: %s, Email: %s)", user.username, user.id, user.email)

    with transaction.atomic():
        user.delete()

    return True


def delete_user_account(user: User) -> tuple[bool, str]:
    """Delete a user account (now performs soft-delete)."""
    return soft_delete_user_account(user)
