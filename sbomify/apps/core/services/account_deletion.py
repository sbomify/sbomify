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


def validate_account_deletion(user: User) -> tuple[bool, str | None]:
    """
    Validate if user can delete their account.

    Blocks deletion if user is the sole owner of a workspace that has other members.
    Users must transfer ownership or remove members before deleting their account.

    Args:
        user: The Django user to validate

    Returns:
        (can_delete, error_message) - True with None if deletion allowed,
        False with error message if blocked
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
    """
    Invalidate all active sessions for a user.

    Args:
        user: The Django user whose sessions should be invalidated

    Returns:
        Number of sessions invalidated
    """
    deleted_count = 0
    active_sessions = Session.objects.filter(expire_date__gte=timezone.now())

    for session in active_sessions:
        try:
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == str(user.id):
                session.delete()
                deleted_count += 1
        except Exception as e:
            # Session may be corrupted or expired; log and continue with others
            logger.debug("Could not process session %s: %s", session.session_key, type(e).__name__)
            continue

    return deleted_count


def delete_user_account(user: User) -> tuple[bool, str]:
    """
    Delete a user account completely.

    Steps:
    1. Validate deletion is allowed
    2. Delete from Keycloak (if linked)
    3. Invalidate all sessions
    4. Delete Django user (cascades to related records)

    Args:
        user: The Django user to delete

    Returns:
        (success, message)
    """
    can_delete, error = validate_account_deletion(user)
    if not can_delete:
        return False, error

    keycloak_user_id = None
    try:
        social_account = SocialAccount.objects.get(user=user, provider="keycloak")
        keycloak_user_id = social_account.uid
    except SocialAccount.DoesNotExist:
        logger.info(f"No Keycloak account linked for user {user.id}")

    if keycloak_user_id and getattr(settings, "USE_KEYCLOAK", True):
        from sbomify.apps.core.keycloak_utils import KeycloakManager

        try:
            keycloak_manager = KeycloakManager()
            if not keycloak_manager.delete_user(keycloak_user_id):
                return (
                    False,
                    "Failed to delete account from authentication provider. Please try again later or contact support.",
                )
        except Exception as e:
            logger.error(f"Keycloak deletion failed for user {user.id}: {e}")
            return (
                False,
                "Failed to delete account from authentication provider. Please try again later or contact support.",
            )

    sessions_invalidated = invalidate_user_sessions(user)
    logger.info(f"Invalidated {sessions_invalidated} sessions for user {user.id}")

    logger.info(f"Deleting user account: {user.username} (ID: {user.id}, Email: {user.email})")

    with transaction.atomic():
        user.delete()

    return True, "Your account has been successfully deleted."
