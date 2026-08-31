from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils import timezone

from sbomify.apps.core.domain.exceptions import PermissionDeniedError

from .models import Invitation, Member, Team

if TYPE_CHECKING:
    from sbomify.apps.core.models import User


def count_team_members(team_id: int | str) -> int:
    # Exclude synthetic ``bot`` Members provisioned by OIDC bindings —
    # they're not human seats and must not inflate the billing counter
    # or any UI that surfaces "members" to workspace admins.
    return Member.objects.filter(team_id=team_id).exclude(role="bot").count()


def count_team_owners(team_id: int | str) -> int:
    return Member.objects.filter(team_id=team_id, role="owner").count()


def count_team_pending_invites(team_id: int | str) -> int:
    return Invitation.objects.filter(team_id=team_id, expires_at__gt=timezone.now()).count()


def get_team_user_counts(team_id: int | str) -> tuple[int, int, int]:
    members = count_team_members(team_id)
    pending = count_team_pending_invites(team_id)
    return members, pending, members + pending


def get_member_role(user_id: int, team_id: str) -> str | None:
    return Member.objects.filter(user_id=user_id, team_id=team_id).values_list("role", flat=True).first()


def get_member_role_by_key(user: Any, team_key: str | None) -> str | None:
    """The user's live role in a workspace, by workspace key.

    Use this for anything that decides what to render. ``session["current_team"]["role"]``
    is a cache with a 300s TTL, so a demoted user keeps seeing controls they can
    no longer use (and a promoted one keeps missing controls they can) until it
    refreshes — while the handler behind the control enforces the real answer and
    returns 403. The role here comes from the ``Member`` row.
    """
    if not team_key or not getattr(user, "is_authenticated", False):
        return None
    return Member.objects.filter(user=user, team__key=team_key).values_list("role", flat=True).first()


def has_pending_invitation(email: str) -> bool:
    """Is there a live invitation for this address?

    "Pending" means unexpired. Kept beside get_pending_invitations_for_email so
    the two cannot disagree about what pending means — a caller that filters on
    neither expiry nor case ends up honouring an invitation that lapsed months
    ago.
    """
    if not email:
        return False
    return Invitation.objects.filter(email__iexact=email, expires_at__gt=timezone.now()).exists()


def get_pending_invitations_for_email(email: str) -> list[Invitation]:
    """Return non-expired pending invitations matching the given email."""
    return list(
        Invitation.objects.filter(email__iexact=email, expires_at__gt=timezone.now())
        .select_related("team")
        .order_by("-created_at")
    )


def get_pending_invitations_for_user(user: User) -> list[dict[str, object]]:
    """Return pending invitations as dicts suitable for template context."""
    if not user.email:
        return []
    return [
        {
            "id": inv.id,
            "team_name": inv.team.display_name,
            "role": inv.role,
            "created_at": inv.created_at,
            "expires_at": inv.expires_at,
        }
        for inv in get_pending_invitations_for_email(user.email)
    ]


def require_team_member(user: User, team: Team, allowed_roles: list[str] | None = None) -> Member:
    member = Member.objects.filter(user=user, team=team).first()
    if not member:
        raise PermissionDeniedError("Access denied")
    if allowed_roles and member.role not in allowed_roles:
        raise PermissionDeniedError("You don't have sufficient permissions to access this page")
    return member
