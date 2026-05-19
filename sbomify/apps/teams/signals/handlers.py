from __future__ import annotations

import logging
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

    from sbomify.apps.core.models import User

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.utils import can_add_user_to_team, get_user_teams, update_user_teams_session

logger = logging.getLogger(__name__)


def _accept_pending_invitations(user: User, request: HttpRequest | None = None) -> list[dict[str, Any]]:
    """
    Accept any pending invitations for the user automatically on login.

    Only auto-accepts for NEW users (no existing team memberships).
    Existing users will see pending invitations in their settings page
    and can choose to accept or reject them manually.

    Returns a list of dicts with accepted invitation metadata (team_key, invitation_id)
    to drive session selection and downstream flows.
    """
    if not user.email:
        return []

    # Skip auto-accept for existing users who already have workspaces
    # They will see pending invitations in /settings and can accept/reject manually
    existing_memberships = Member.objects.filter(user=user).exists()
    if existing_memberships:
        logger.info("User %s has existing workspaces; skipping auto-accept for pending invitations", user.username)
        return []

    accepted: list[dict[str, Any]] = []
    has_default = Member.objects.filter(user=user, is_default_team=True).exists()

    pending_invites = Invitation.objects.filter(email__iexact=user.email, expires_at__gt=timezone.now()).select_related(
        "team"
    )

    for invitation in pending_invites:
        # Skip if already a member of this team
        if Member.objects.filter(user=user, team=invitation.team).exists():
            invitation.delete()
            continue

        can_add, error_msg = can_add_user_to_team(invitation.team, is_joining_via_invite=True)
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

        if request is not None:
            # Capture into locals BEFORE invitation.delete() below; the
            # deferred ``on_commit`` lambda reads these by closure.
            captured_role = invitation.role
            captured_team_key = invitation.team.key
            transaction.on_commit(
                lambda: capture_for_request(
                    request,
                    "team:member_invitation_accepted",
                    {"role": captured_role},
                    team_key=captured_team_key,
                )
            )

        invitation.delete()

    if request is not None and accepted:
        request.session["auto_accepted_invites"] = accepted
        request.session.modified = True

    return accepted


def _invalidate_pending_invites_cache(email: str | None) -> None:
    if not email:
        return

    from django.core.cache import cache

    from sbomify.apps.core.utils import sanitize_email_for_cache_key

    sanitized_email = sanitize_email_for_cache_key(email)
    if not sanitized_email:
        return

    cache.delete(f"pending_invitations:{sanitized_email}")


# Sentinel attached to a Member instance in pre_save so the post_save
# handler can compare against the prior role. Lives on the instance
# (not a module-level dict) so it:
#   * is thread-safe — each save call has its own Member instance
#   * is leak-proof — if save() raises after pre_save, the snapshot is
#     garbage-collected with the instance instead of leaving an entry
#     behind in a process-wide dict
#   * doesn't bleed across requests in long-lived processes
_OLD_ROLE_ATTR = "_sbomify_old_role"


@receiver(pre_save, sender=Member)
def snapshot_member_role_for_change_detection(sender: type, instance: Member, **kwargs: Any) -> None:
    if not instance.pk:
        return

    # When ``save(update_fields=[...])`` is called and ``role`` isn't in
    # the list, skip the DB lookup entirely — the role cannot change on
    # this save, so the snapshot would never be consulted by post_save.
    # This avoids an extra query on every Member.save() that touches a
    # different field (last_login_team, is_default_team, etc.).
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "role" not in set(update_fields):
        return

    try:
        previous = Member.objects.only("role").get(pk=instance.pk)
    except Member.DoesNotExist:
        return
    setattr(instance, _OLD_ROLE_ATTR, previous.role)


@receiver(post_save, sender=Member)
def capture_role_change(sender: type, instance: Member, created: bool, **kwargs: Any) -> None:
    """Emit ``team:role_changed`` when an existing membership's role transitions.

    Skips: creations (covered by ``team:member_invited`` / invitation-accepted
    flows), no-op saves where role is unchanged, and any path where the
    pre_save snapshot didn't run (e.g. raw SQL update or
    ``update_fields`` that excluded ``role``).

    Also early-returns when the caller passed ``update_fields`` excluding
    ``role`` even if a prior save on the same instance set
    ``_sbomify_old_role`` — otherwise a stale snapshot from an earlier
    role-change save would fire ``team:role_changed`` again for a write
    that didn't touch ``role``. The snapshot is also cleared at the end
    so subsequent saves on the same instance start from a clean slate.
    """
    if created:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "role" not in set(update_fields):
        return

    # Pop the snapshot unconditionally before any branch — this is what
    # makes "subsequent saves start clean" actually true. If we only
    # cleared on the fire path, a no-op save (role unchanged) would
    # leave the attribute behind and a later legitimate change could
    # observe stale state.
    old_role = getattr(instance, _OLD_ROLE_ATTR, None)
    try:
        delattr(instance, _OLD_ROLE_ATTR)
    except AttributeError:
        pass

    if old_role is None or old_role == instance.role:
        return

    from sbomify.apps.core.posthog_service import capture

    workspace_key = instance.team.key or ""
    distinct_id = workspace_key or "system"
    captured_old_role = old_role
    captured_new_role = instance.role
    transaction.on_commit(
        lambda: capture(
            distinct_id,
            "team:role_changed",
            {"from_role": captured_old_role, "to_role": captured_new_role},
            groups={"workspace": workspace_key} if workspace_key else None,
        )
    )


@receiver(post_save, sender=Invitation)
def invalidate_pending_invites_on_save(sender: type, instance: Invitation, **kwargs: Any) -> None:
    _invalidate_pending_invites_cache(instance.email)


@receiver(post_delete, sender=Invitation)
def invalidate_pending_invites_on_delete(sender: type, instance: Invitation, **kwargs: Any) -> None:
    _invalidate_pending_invites_cache(instance.email)


@receiver(user_logged_in)
def user_logged_in_handler(sender: type, user: User, request: HttpRequest, **kwargs: Any) -> None:
    request.session["user_photo"] = ""
    social_account = SocialAccount.objects.filter(user=user, provider="keycloak").first()
    if social_account:
        request.session["user_photo"] = social_account.extra_data.get("picture", "")

    # Auto-accept pending invitations so invite-only signups land in the invited workspace
    joined_invites = _accept_pending_invitations(user, request)

    # Get user teams and store them in session
    user_teams = update_user_teams_session(request, user)

    if request.session.get("current_team", None) is None and user_teams:
        # Prefer an explicit default workspace; otherwise fall back to first
        default_team_key = next((key for key, data in user_teams.items() if data.get("is_default_team")), None)
        active_team_key = (
            (joined_invites[0]["team_key"] if joined_invites else None) or default_team_key or next(iter(user_teams))
        )
        request.session["current_team"] = {"key": active_team_key, **user_teams[active_team_key]}
        request.session.modified = True

    # Fallback safety net: Ensure every user has a team
    # Note: This should rarely be needed now that both adapters create teams during signup.
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
        if created_team and created_team.key:
            user_teams = get_user_teams(user)
            request.session["user_teams"] = user_teams
            if user_teams:
                request.session["current_team"] = {
                    "key": created_team.key,
                    **user_teams.get(created_team.key, {}),
                }
            request.session.modified = True
