from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect

from sbomify.apps.core.authz import ADMINISTER, ROLE_ADMIN, ROLE_OWNER
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

        # Admins can't quietly remove themselves — unless they're leaving for a
        # workspace they've been invited to.
        if target.user_id == getattr(actor, "id", None):
            from sbomify.apps.teams.models import Invitation

            if not Invitation.objects.filter(email=actor.email).exists():
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


class TeamRoleRequiredMixin(AccessMixin):
    allowed_roles: list[str] = []

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Check authentication first - let LoginRequiredMixin handle redirect if not authenticated
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc, no-any-return]

        current_team: dict[str, Any] = request.session.get("current_team", {})

        team_key = current_team.get("key", None)
        if team_key is None:
            return error_response(request, HttpResponseForbidden("You are not a member of any team"))

        try:
            Member.objects.get(user=request.user, team__key=team_key, role__in=self.allowed_roles)
        except Member.DoesNotExist:
            # Check if user has ANY membership in this team (just not the right role)
            has_any_membership = Member.objects.filter(user=request.user, team__key=team_key).exists()

            if has_any_membership:
                # User is a member but doesn't have the required role
                return error_response(
                    request, HttpResponseForbidden("You don't have sufficient permissions to access this page")
                )

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
            current_team: dict[str, Any] = request.session.get("current_team", {})
            team_key = current_team.get("key")
            if team_key:
                try:
                    Member.objects.get(user=request.user, team__key=team_key, role="guest")
                    # Redirect guest members to public workspace page
                    return redirect("core:workspace_public", workspace_key=team_key)
                except Member.DoesNotExist:
                    pass
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc, no-any-return]
