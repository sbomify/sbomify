from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import Model
    from django.http import HttpRequest

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone

from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.utils import can_add_user_to_team, get_user_teams

logger = logging.getLogger(__name__)


def _accept_pending_invitations(user, request: HttpRequest | None = None) -> list[dict]:
    """
    Accept any pending invitations for the user automatically on login.

    Returns a list of dicts with accepted invitation metadata (team_key, invitation_id)
    to drive session selection and downstream flows.
    """
    if not user.email:
        return []

    accepted: list[dict] = []
    has_default = Member.objects.filter(user=user, is_default_team=True).exists()

    pending_invites = Invitation.objects.filter(email__iexact=user.email, expires_at__gt=timezone.now()).select_related(
        "team"
    )

    for invitation in pending_invites:
        # Skip if already a member of this team
        if Member.objects.filter(user=user, team=invitation.team).exists():
            invitation.delete()
            continue

        can_add, error_msg = can_add_user_to_team(invitation.team)
        if not can_add:
            logger.warning(
                "Skipping invitation %s for user %s due to limit: %s", invitation.id, user.username, error_msg
            )
            continue

        membership = Member.objects.create(
            user=user,
            team=invitation.team,
            role=invitation.role,
            is_default_team=not has_default,
        )
        has_default = has_default or membership.is_default_team
        accepted.append(
            {"team_key": invitation.team.key, "invitation_id": invitation.id, "invitation_token": str(invitation.token)}
        )
        invitation.delete()

    if request is not None and accepted:
        request.session["auto_accepted_invites"] = accepted
        request.session.modified = True

    return accepted


@receiver(user_logged_in)
def user_logged_in_handler(sender: Model, user: User, request: HttpRequest, **kwargs):
    request.session["user_photo"] = ""
    social_account = SocialAccount.objects.filter(user=user, provider="keycloak").first()
    if social_account:
        request.session["user_photo"] = social_account.extra_data.get("picture", "")

    # Auto-accept pending invitations so invite-only signups land in the invited workspace
    joined_invites = _accept_pending_invitations(user, request)

    # Get user teams and store them in session
    user_teams = get_user_teams(user)
    request.session["user_teams"] = user_teams

    if request.session.get("current_team", None) is None and user_teams:
        # Prefer an explicit default workspace; otherwise fall back to first
        default_team_key = next((key for key, data in user_teams.items() if data.get("is_default_team")), None)
        active_team_key = (
            (joined_invites[0]["team_key"] if joined_invites else None)
            or default_team_key
            or next(iter(user_teams))
        )
        request.session["current_team"] = {"key": active_team_key, **user_teams[active_team_key]}
        request.session.modified = True

    # Fallback safety net: Ensure every user has a team
    # NOTE: This should rarely be needed now that both adapters create teams during signup.
    # This exists only for edge cases (manual user creation, data migrations, etc.)
    if not Team.objects.filter(members=user).exists():
        has_pending_invite = Invitation.objects.filter(email__iexact=user.email, expires_at__gt=timezone.now()).exists()

        if has_pending_invite and not joined_invites:
            logger.warning(
                "User %s has pending invitations but none were accepted; creating personal workspace fallback",
                user.username,
            )
        else:
            logger.warning(
                f"User {user.username} has no team on login - creating via fallback handler. "
                f"This should not happen for normal signups."
            )

        from sbomify.apps.teams.utils import create_user_team_and_subscription

        created_team = create_user_team_and_subscription(user)
        if created_team:
            user_teams = get_user_teams(user)
            request.session["user_teams"] = user_teams
            if user_teams:
                request.session["current_team"] = {
                    "key": created_team.key,
                    **user_teams.get(created_team.key, {}),
                }
            request.session.modified = True
