"""Service for user account deletion."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from sbomify.apps.core.services.results import ServiceResult

if TYPE_CHECKING:
    from sbomify.apps.core.models import User

logger = logging.getLogger(__name__)

SOFT_DELETE_GRACE_DAYS = 14


def validate_account_deletion(user: User) -> ServiceResult[None]:
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
            return ServiceResult.failure(
                f"You are the sole owner of workspace '{team.display_name}' which has other members. "
                "Please transfer ownership or remove all members before deleting your account.",
                status_code=403,
            )

    return ServiceResult.success()


def invalidate_user_sessions(user: User) -> int:
    """Invalidate all active sessions for a user."""
    deleted_count = 0
    active_sessions = Session.objects.filter(expire_date__gte=timezone.now()).iterator()

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


def _cleanup_stripe_for_workspace(team) -> bool:
    """Cancel Stripe subscription and delete customer for a workspace.

    Returns True if cleanup succeeded or was not needed, False on error.
    """
    from sbomify.apps.billing.config import is_billing_enabled
    from sbomify.apps.billing.stripe_client import StripeClient, StripeError

    if not is_billing_enabled():
        return True

    limits = team.billing_plan_limits or {}
    subscription_id = limits.get("stripe_subscription_id")
    customer_id = limits.get("stripe_customer_id")

    if not subscription_id and not customer_id:
        return True

    try:
        client = StripeClient()
        if subscription_id:
            client.cancel_subscription(subscription_id, prorate=True)
            logger.info("Cancelled Stripe subscription for team %s", team.key)
        if customer_id:
            client.delete_customer(customer_id)
            logger.info("Deleted Stripe customer for team %s", team.key)
        return True
    except StripeError as e:
        logger.warning("Stripe cleanup failed for team %s: %s", team.key, e)
        return False


def _disable_keycloak_user(user: User) -> bool:
    """Disable (not delete) user in Keycloak. Returns True if successful or not needed."""
    try:
        social_account = SocialAccount.objects.get(user=user, provider="keycloak")
    except SocialAccount.DoesNotExist:
        return True

    if not getattr(settings, "USE_KEYCLOAK", True):
        return True

    from sbomify.apps.core.keycloak_utils import KeycloakManager

    try:
        manager = KeycloakManager()
        return manager.disable_user(social_account.uid)
    except Exception as e:
        logger.error("Failed to disable Keycloak user %s: %s", user.id, e)
        return False


def _delete_keycloak_user(user: User) -> bool:
    """Delete user from Keycloak. Returns True if successful or not needed."""
    try:
        social_account = SocialAccount.objects.get(user=user, provider="keycloak")
    except SocialAccount.DoesNotExist:
        return True

    if not getattr(settings, "USE_KEYCLOAK", True):
        return True

    from sbomify.apps.core.keycloak_utils import KeycloakManager

    try:
        manager = KeycloakManager()
        return manager.delete_user(social_account.uid)
    except Exception as e:
        logger.error("Failed to delete Keycloak user %s: %s", user.id, e)
        return False


def soft_delete_user_account(user: User) -> ServiceResult[str]:
    """
    Soft-delete a user account.

    Steps (within atomic transaction):
    1. Lock user row to prevent concurrent requests
    2. Validate deletion is allowed
    3. Cancel Stripe subscriptions for orphaned workspaces
    4. Delete orphaned workspaces
    5. Clean up invitations
    6. Revoke API tokens
    7. Set is_active=False and deleted_at=now

    After commit:
    8. Disable in Keycloak (if linked)
    9. Invalidate sessions
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()

    # Atomic guard: lock the row to prevent concurrent deletion requests
    with transaction.atomic():
        locked_user = (
            User.objects.select_for_update().filter(pk=user.pk, is_active=True, deleted_at__isnull=True).first()
        )
        if locked_user is None:
            return ServiceResult.failure("Account deletion is already in progress.", status_code=409)

        result = validate_account_deletion(locked_user)
        if not result.ok:
            return ServiceResult.failure(result.error, status_code=result.status_code)

        orphaned_workspaces = _get_orphaned_workspaces(locked_user)

        for team in orphaned_workspaces:
            if not _cleanup_stripe_for_workspace(team):
                logger.critical(
                    "Stripe cleanup failed for team %s during user %s deletion — subscription may be orphaned",
                    team.key,
                    locked_user.id,
                )

        for team in orphaned_workspaces:
            logger.info("Deleting orphaned workspace %s (team_key=%s)", team.name, team.key)
            team.delete()

        from sbomify.apps.teams.models import Invitation

        deleted_invites = Invitation.objects.filter(email=locked_user.email).delete()[0]
        if deleted_invites:
            logger.info("Deleted %d incoming invitations for user %s", deleted_invites, locked_user.id)

        from sbomify.apps.access_tokens.models import AccessToken

        deleted_tokens = AccessToken.objects.filter(user=locked_user).delete()[0]
        if deleted_tokens:
            logger.info("Deleted %d access tokens for user %s", deleted_tokens, locked_user.id)

        locked_user.is_active = False
        locked_user.deleted_at = timezone.now()
        locked_user.save(update_fields=["is_active", "deleted_at"])

    # External service calls after local commit succeeds (Finding #5: correct ordering)
    if not _disable_keycloak_user(locked_user):
        logger.warning(
            "Keycloak disable failed for user %s after soft-delete committed — will retry on hard-delete",
            locked_user.id,
        )

    sessions_invalidated = invalidate_user_sessions(locked_user)
    logger.info("Invalidated %d sessions for user %s", sessions_invalidated, locked_user.id)

    logger.info(
        "Soft-deleted user account (ID: %s). Hard delete scheduled after %d days.",
        locked_user.id,
        SOFT_DELETE_GRACE_DAYS,
    )

    return ServiceResult.success(
        "Your account has been scheduled for deletion. "
        f"It will be permanently removed after {SOFT_DELETE_GRACE_DAYS} days. "
        "Contact support if you change your mind."
    )


def hard_delete_user(user: User) -> bool:
    """Permanently delete a soft-deleted user. Called by periodic purge task."""
    if user.is_active or user.deleted_at is None:
        logger.warning("Attempted hard delete on active user %s — skipping", user.id)
        return False

    if not _delete_keycloak_user(user):
        logger.warning("Keycloak deletion failed for user %s — proceeding with DB deletion", user.id)

    logger.info("Hard-deleting user (ID: %s)", user.id)

    with transaction.atomic():
        user.delete()

    return True


def delete_user_account(user: User) -> ServiceResult[str]:
    """Delete a user account (now performs soft-delete)."""
    return soft_delete_user_account(user)
