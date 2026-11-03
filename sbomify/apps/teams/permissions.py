from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect

from sbomify.apps.core.authz import (
    ADMINISTER,
    ROLE_ADMIN,
    ROLE_BOT,
    ROLE_GUEST,
    ROLE_MEMBER,
    ROLE_OPERATOR,
    ROLE_OWNER,
)
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.models import Member


@dataclass(frozen=True)
class MemberRemovalDenial:
    """Why a member removal was refused.

    ``forbidden`` distinguishes an authorization failure (the caller should
    answer 403) from a policy refusal the user can act on (show a message and
    send them back to the members tab). ``level`` is the Django messages level
    for the latter — the last-owner refusal is advisory ("assign another owner
    first"), not an error, and reads as a warning.
    """

    message: str
    forbidden: bool = False
    level: int = messages.ERROR


def check_member_removal(actor: Any, target: Member) -> MemberRemovalDenial | None:
    """Can ``actor`` remove the ``target`` membership? ``None`` means yes.

    The owner-protection rules live here rather than at the call sites because
    there are two removal paths — the bare-PK ``teams.views.delete_member`` and
    the settings members tab — and they had already drifted apart: the settings
    path was missing the admin self-removal rule entirely.

    Note the first rule is *relational*: whether an actor may remove a member
    depends on the target's role, not just the actor's, which is why it cannot
    be expressed as a capability tier in ``authz``.
    """
    actor_membership = Member.objects.filter(user=actor, team=target.team).first()
    if actor_membership is None or actor_membership.role not in ADMINISTER:
        return MemberRemovalDenial("You don't have permission to manage this workspace's members", forbidden=True)

    if actor_membership.role == ROLE_ADMIN:
        # The defining owner/admin boundary.
        if target.role == ROLE_OWNER:
            return MemberRemovalDenial("Admins cannot remove workspace owners.")

        # Admins are peers: only an owner manages them. Without this, the rule
        # that an admin may not demote another admin (check_role_change) would
        # be one click from meaningless, since removing is the stronger act.
        if target.role == ROLE_ADMIN and target.user_id != getattr(actor, "id", None):
            return MemberRemovalDenial("Only workspace owners can remove admins.")

        # Admins can't quietly remove themselves — unless they're leaving for a
        # workspace they've been invited to.
        if target.user_id == getattr(actor, "id", None):
            from sbomify.apps.teams.queries import has_pending_invitation, invitation_email

            # Pending means unexpired. The original check was ``exists()`` over
            # every Invitation ever addressed to them — under a variable named
            # has_pending_invites — so an invitation that lapsed months ago
            # still bought a way out of this rule.
            if not has_pending_invitation(invitation_email(actor)):
                return MemberRemovalDenial(
                    "Admins cannot remove their own membership. Only workspace owners can remove members.",
                    forbidden=True,
                )

    if target.role == ROLE_OWNER:
        from sbomify.apps.teams.queries import count_team_owners

        if count_team_owners(target.team_id) <= 1:
            return MemberRemovalDenial(
                "Cannot delete the only owner of the workspace. Please assign another owner first.",
                level=messages.WARNING,
            )

    return None


# Roles a person can be moved between from the members page. ``guest`` comes and
# goes through trust-center access requests and ``bot`` belongs to an OIDC
# trusted-publisher binding, so neither is assignable, and a membership holding
# either is not changed here.
ASSIGNABLE_ROLES: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER, ROLE_OPERATOR)

# What an admin may change: the roles below their own. Owners and other admins
# are managed by owners only.
ADMIN_MANAGEABLE_ROLES: tuple[str, ...] = (ROLE_MEMBER, ROLE_OPERATOR)


def assignable_roles_for(actor_role: str | None, actor_id: Any, target_role: str, target_user_id: Any) -> list[str]:
    """The roles a target holding ``target_role`` can be moved to by the actor.

    Empty when the actor may not change the target at all. Mirrors
    ``check_role_change`` so the members page only offers what the server will
    accept; ``check_role_change`` stays the authority, and still refuses
    demoting the only owner.
    """
    if target_role in (ROLE_GUEST, ROLE_BOT):
        return []
    if actor_role == ROLE_OWNER:
        offered = ASSIGNABLE_ROLES
    elif actor_role == ROLE_ADMIN and target_role in ADMIN_MANAGEABLE_ROLES and target_user_id != actor_id:
        offered = tuple(role for role in ASSIGNABLE_ROLES if role != ROLE_OWNER)
    else:
        return []
    return [role for role in offered if role != target_role]


def check_role_change(actor: Any, target: Member, new_role: str) -> MemberRemovalDenial | None:
    """Can ``actor`` move ``target`` to ``new_role``? ``None`` means yes.

    Relational, like ``check_member_removal``: the answer depends on the
    target's role as well as the actor's.

    * Owners can change anyone's role, their own included, as long as the
      workspace keeps at least one owner.
    * Admins can change the role of members and operators, up to admin. They
      cannot touch an owner or another admin (themselves included), and cannot
      make anyone an owner — the same line ``member:grant_owner`` draws for
      invitations.
    * Guest and bot memberships are never changed here.

    The last-owner check counts owners at call time; callers that write the
    change must hold a lock on the workspace's owner rows while they do.
    """
    actor_membership = Member.objects.filter(user=actor, team=target.team).first()
    if actor_membership is None or actor_membership.role not in ADMINISTER:
        return MemberRemovalDenial("You don't have permission to manage this workspace's members", forbidden=True)

    if target.role in (ROLE_GUEST, ROLE_BOT):
        return MemberRemovalDenial("This membership's role cannot be changed here.", forbidden=True)

    if new_role not in ASSIGNABLE_ROLES:
        return MemberRemovalDenial(f"Role must be one of: {', '.join(ASSIGNABLE_ROLES)}")

    if actor_membership.role == ROLE_ADMIN:
        if target.role == ROLE_OWNER:
            return MemberRemovalDenial("Only workspace owners can change an owner's role.")
        if target.role == ROLE_ADMIN:
            return MemberRemovalDenial("Only workspace owners can change an admin's role.")
        if new_role == ROLE_OWNER:
            return MemberRemovalDenial("Only workspace owners can make someone an owner.")

    if target.role == ROLE_OWNER and new_role != ROLE_OWNER:
        from sbomify.apps.teams.queries import count_team_owners

        if count_team_owners(target.team_id) <= 1:
            return MemberRemovalDenial(
                "Cannot change the role of the only owner of the workspace. Please assign another owner first.",
                level=messages.WARNING,
            )

    return None


class TeamRoleRequiredMixin(AccessMixin):
    allowed_roles: list[str] = []

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Check authentication first - let LoginRequiredMixin handle redirect if not authenticated
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc, no-any-return]

        current_team: dict[str, Any] = request.session.get("current_workspace", {})

        # Authorize the workspace the URL names, not the one in the session.
        # These are not the same thing: the handlers below act on the URL's
        # workspace, so checking the session's granted whatever role the user
        # happened to hold *somewhere else*. Being an owner of A is not a claim
        # about B. Guests were turned away by other gates, so until `member`
        # existed there was no role below ADMINISTER left to fall through this.
        url_team_key = kwargs.get("workspace_key")
        workspace_key = url_team_key or current_team.get("key", None)
        if workspace_key is None:
            return error_response(request, HttpResponseForbidden("You are not a member of any team"))

        try:
            Member.objects.get(user=request.user, team__key=workspace_key, role__in=self.allowed_roles)
        except Member.DoesNotExist:
            # Check if user has ANY membership in this team (just not the right role)
            has_any_membership = Member.objects.filter(user=request.user, team__key=workspace_key).exists()

            if has_any_membership:
                # User is a member but doesn't have the required role
                return error_response(
                    request, HttpResponseForbidden("You don't have sufficient permissions to access this page")
                )

            if url_team_key:
                # Asked for a workspace they do not belong to. Not the same as
                # the case below: their session is fine, so recovering it would
                # silently move them to another workspace instead of answering
                # the question they asked.
                return error_response(request, HttpResponseForbidden("You are not a member of this workspace"))

            # User is not a member of this workspace at all - they may have been removed
            # Try to switch to another workspace they are a member of
            from sbomify.apps.teams.utils import recover_workspace_session

            return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc, no-any-return]


class GuestAccessBlockedMixin(AccessMixin):
    """Mixin that blocks guest members from accessing internal app views.

    Guest members are redirected to the public workspace page instead.
    Guest members should only have access to public pages and gated documents.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Check if user is authenticated and is a guest member
        if request.user.is_authenticated:
            current_team: dict[str, Any] = request.session.get("current_workspace", {})
            workspace_key = current_team.get("key")
            if workspace_key:
                try:
                    Member.objects.get(user=request.user, team__key=workspace_key, role="guest")
                    # Redirect guest members to public workspace page
                    return redirect("core:workspace_public", workspace_key=workspace_key)
                except Member.DoesNotExist:
                    pass
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc, no-any-return]
